import argparse
import gc
import json
import re
import statistics
import time
from contextlib import contextmanager
from datetime import datetime
from os import makedirs, path, walk
from typing import Any, Final, Generator

import psycopg2
from psycopg2 import errors
from psycopg2.extensions import connection as PgConnection
from pydantic import BaseModel

args_parser = argparse.ArgumentParser(description="Process command-line arguments.")
args_parser.add_argument('--queries-path', type=str, help='Path to directory with LSQB queries')
args_parser.add_argument("--path-ddl-query", type=str, help="Path to DDL query")
args_parser.add_argument('--times', type=int, default=1, help='Times to run each query')
args_parser.add_argument('--timeout-millis', type=int, default=60000, help='SQL query execution timeout in milliseconds')
args_parser.add_argument('--result-path', type=str, help='Path to output result file')
args_parser.add_argument("--db-host", type=str, default='localhost', help="PostgresQL host")
args_parser.add_argument("--db-port", type=int, default=5432, help="PostgresQL port")
args_parser.add_argument("--db-user", type=str, default='postgres', help="PostgresQL username")
args_parser.add_argument("--path-to-data", type=str, default="./csv", help="Path to directory with csv-files for load data")
args_parser.add_argument("--analyze", action="store_true", help="Collect query plans instead of timings")
args = args_parser.parse_args()

MEM_KEY_RSS: Final = 'VmRSS'
MEM_KEY_HWM: Final = 'VmHWM'

EXPLAIN_RUN: Final = "EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, VERBOSE, SETTINGS ON, FORMAT JSON)"
EXPLAIN_EST: Final = "EXPLAIN (VERBOSE, COSTS ON, SETTINGS ON, FORMAT JSON)"

STATS_SQL: Final = """
    SELECT c.relname, c.reltuples, c.relpages, s.n_live_tup, s.last_analyze, s.last_autoanalyze
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
    ORDER BY c.relname
"""

SETTINGS_SQL: Final = """
    SELECT name, setting, unit, source
    FROM pg_settings
    WHERE name IN ('server_version', 'work_mem', 'shared_buffers', 'effective_cache_size',
                'max_parallel_workers', 'max_parallel_workers_per_gather', 'jit',
                'statement_timeout', 'autovacuum_naptime', 'random_page_cost')
    ORDER BY name
"""


class BenchmarkResult(BaseModel):
    result: Any | None = None
    median: float = 0.0
    mean: float = 0.0
    memory: float = 0.0
    count_failed: int = 0

class PlanResult(BaseModel):
    query: str
    executed: bool
    plan: Any | None = None
    error: str | None = None

class MemoryResult(BaseModel):
    peak: int
    baseline: int

def read_memory(pid: int, mem_key: str) -> int:
    with open(f"/proc/{pid}/status") as f: 
        rss = [int(v.replace(' kB', '').strip()) for _, v  in [a.split("\t") for a in f.read().split("\n") if re.match(rf"{mem_key}", a)]]
        if len(rss) == 0:
            return 0
        
        return rss[0]

def run_query(query: str, result: BenchmarkResult, host: str, port: int, user: str, timeout: int) -> float:
    with get_connection(host, port, user, timeout) as connection:

        pid = get_pid(connection)
        baseline = read_memory(pid, MEM_KEY_RSS)

        with connection.cursor() as cursor:
            try:
                t0 = time.perf_counter()  
                cursor.execute(query)
                result.result = cursor.fetchall()
                elapsed = time.perf_counter() - t0

                peak = read_memory(pid, MEM_KEY_HWM)
                result.memory = max(result.memory, peak - baseline)

                return elapsed

            except errors.QueryCanceled as e:
                result.count_failed += 1
                print(f"Query failed: {e}")

    return 0.0


def execute_and_fetch(connection: PgConnection, query: str) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchone()[0]


def execute_and_fetch_all(connection: PgConnection, query: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def execute_no_result(connection: PgConnection, query: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(query)
        return str(cursor.statusmessage)


def get_pid(connection: PgConnection) -> int:
    return int(execute_and_fetch(connection, "SELECT pg_backend_pid();"))


def profile_metric(query: str, host: str, port: int, user: str, timeout: int, times_query: int) -> BenchmarkResult:
    result = BenchmarkResult()

    try:
        elapsed = []
        for _ in range(times_query):
            elapsed.append(run_query(query, result, host, port, user, timeout))
    except Exception as e:
        print(f"Query failed: {e}")
        return result

    result.median = statistics.median(elapsed)
    result.mean = statistics.mean(elapsed)

    gc.collect()

    return result


def collect_stats(connection: PgConnection) -> list[dict]:
    rows = execute_and_fetch_all(connection, STATS_SQL)
    return [
        {
            "relname": r[0],
            "reltuples": float(r[1]),
            "relpages": int(r[2]),
            "n_live_tup": None if r[3] is None else int(r[3]),
            "last_analyze": None if r[4] is None else r[4].isoformat(),
            "last_autoanalyze": None if r[5] is None else r[5].isoformat(),
        }
        for r in rows
    ]


def collect_settings(connection: PgConnection) -> list[dict]:
    rows = execute_and_fetch_all(connection, SETTINGS_SQL)
    return [{"name": r[0], "setting": r[1], "unit": r[2], "source": r[3]} for r in rows]


def run_analyze(connection: PgConnection) -> dict:
    """Run ANALYZE VERBOSE and keep what it reports.

    ANALYZE returns no rows at all: its output arrives as NOTICE messages, which
    psycopg2 appends to connection.notices. The default deque keeps only the last
    50, so it is replaced by a plain list first.
    """
    connection.notices = []
    status = execute_no_result(connection, "ANALYZE VERBOSE;")
    return {"status": status, "notices": [n.rstrip() for n in connection.notices]}


def explain_query(connection: PgConnection, name: str, sql: str) -> PlanResult:
    
    try:
        plan = execute_and_fetch(connection, f"{EXPLAIN_RUN} {sql}")
        return PlanResult(query=name, executed=True, plan=plan)
    except errors.QueryCanceled as e:
        print(f"  {name}: cancelled after the timeout, falling back to an estimate-only plan")
        fallback_error = str(e).strip()
    except Exception as e:
        print(f"  {name}: {e}")
        fallback_error = str(e).strip()

    try:
        plan = execute_and_fetch(connection, f"{EXPLAIN_EST} {sql}")
        return PlanResult(query=name, executed=False, plan=plan, error=fallback_error)
    except Exception as e:
        print(f"  {name}: planning failed: {e}")
        return PlanResult(query=name, executed=False, plan=None, error=str(e).strip())


def analyze(host: str, port: int, user: str, timeout: int, path_to_query: str, path_to_output: str) -> None:
    plan_dir = path.splitext(path_to_output)[0]
    makedirs(plan_dir, exist_ok=True)

    try:
        with get_connection(host, port, user, timeout) as connection:
            connection.autocommit = True

            before = collect_stats(connection)
            settings = collect_settings(connection)
            analyze_report = run_analyze(connection)
            after = collect_stats(connection)

            with open(path.join(plan_dir, "_state.json"), 'w') as s:
                json.dump({
                    "captured_at": datetime.now().isoformat(),
                    "settings": settings,
                    "analyze": analyze_report,
                    "stats_before_analyze": before,
                    "stats_after_analyze": after,
                }, s, indent=1, default=str)

            analysed = sum(1 for r in after if r["last_analyze"] is not None)
            print(f"ANALYZE: {analyze_report['status']}, "
                  f"{analysed} of {len(after)} relations now carry statistics")

            with open(path_to_output, 'a') as o:
                for file in next(walk(path_to_query))[2]:
                    with open(f"{path_to_query}/{file}") as f:
                        sql = f.read().strip().rstrip(';')

                    print(f"Planning {file}")
                    result = explain_query(connection, file, sql)

                    plan_file = path.join(plan_dir, f"{path.splitext(file)[0]}.json")
                    with open(plan_file, 'w') as p:
                        json.dump({
                            "query": file,
                            "executed": result.executed,
                            "error": result.error,
                            "plan": result.plan,
                        }, p, indent=1, default=str)

                    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    o.write(f"{stamp},{file},executed={result.executed},plan={plan_file}\n")

    except Exception as e:
        print(f"Analyze failed: {e}")
        return


def benchmark(host: str, port: int, user: str, timeout: int, path_to_query: str, path_to_output: str, times_query: int) -> None:
    try:
        total_timeout = 0
        with open(path_to_output, 'a') as o:
            for file in next(walk(path_to_query))[2]:
                if not file.endswith('.sql'):
                    continue

                with open(f"{path_to_query}/{file}", 'r') as f:
                    print (f"Running query of {file}")
                    result = profile_metric(f.read(), host, port, user, timeout, times_query)
                    o.write(f"{datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]},{file},{result.result},{result.median},{result.mean},{result.memory}\n")
                    total_timeout += result.count_failed

        with open(path_to_output, 'a') as o:
            o.write(f"failure_rate,{total_timeout / (9 * times_query) * 100:.3f}%\n")

    except Exception as e:
        print(f"Benchmark failed: {e}")
        return


@contextmanager
def get_connection(host: str, port: int, user: str, timeout: int) -> Generator[PgConnection]:
    connection = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        options=f"-c statement_timeout={timeout}"
    )

    try:
        yield connection
    finally:
        connection.close()


if __name__ == "__main__":
    if args.analyze:
        analyze(
            args.db_host,
            args.db_port,
            args.db_user,
            args.timeout_millis,
            args.queries_path,
            args.result_path
        )
    else:
        benchmark(
            args.db_host,
            args.db_port,
            args.db_user,
            args.timeout_millis,
            args.queries_path,
            args.result_path,
            args.times
        )