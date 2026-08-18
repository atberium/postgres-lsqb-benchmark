import argparse
from contextlib import contextmanager
from os import walk
import re 

import time
import statistics

from typing import Any, Final, Generator
from pydantic import BaseModel

import gc
from datetime import datetime

import psycopg2
from psycopg2 import errors
from psycopg2.extensions import connection as PgConnection

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
args_parser.add_argument("--load-mode", type=str, help="Load mode: cold psql or cold (warm) load in python")
args = args_parser.parse_args()

PATTERN_PATH_TO_REPLACE: Final = 'PATHVAR'
PATTERN_COPY_TO_REPLACE: Final = '\\copy'
MEM_KEY_RSS: Final = 'VmRSS'
MEM_KEY_HWM: Final = 'VmHWM'
QUERY_GET_DB_SIZE: Final = "SELECT pg_size_pretty(pg_database_size(current_database()));"

class BenchmarkResult(BaseModel):
    result: Any | None = None
    median: float = 0.0
    mean: float = 0.0
    memory: float = 0.0
    count_failed: int = 0

class MemoryResult(BaseModel):
    peak: int
    baseline: int

def run_query_db_create(connecton: PgConnection, query: str) -> None:
    with connecton.cursor() as cursor:
        try:
        
            cursor.execute(query)
        
        except Exception as e:
            print(f"Problem with create DB: {e}")
            cursor.connection.rollback()
            raise
        
        finally:
            connecton.commit()

def create_db_with_copy(
        connection: PgConnection, 
        path_to_query_ddl: str, 
        path_to_data: str, 
        path_to_output: str) -> None:
    
    with open(path_to_query_ddl) as reader:
        query = reader.read()
        query = query.replace(PATTERN_COPY_TO_REPLACE, 'COPY')
        query = query.replace(PATTERN_PATH_TO_REPLACE, path_to_data)

        with connection.cursor() as cursor:
            try:
                cursor.execute(QUERY_GET_DB_SIZE)
                db_size_before = cursor.fetchall()[0][0]

                start_db = time.time()
                run_query_db_create(connection, query=query)
                end_db = time.time()
                
                cursor.execute(QUERY_GET_DB_SIZE)
                db_size_after = cursor.fetchall()[0][0]

                with open(path_to_output, 'w') as o:
                    o.write(f"Size DB BEFORE create schema and load data,{db_size_before}\n")
                    o.write(f"Size DB AFTER create schema and load data,{db_size_after}\n")
                    o.write(f"time_load,{end_db - start_db:.4f}\n")

            except Exception:
                cursor.connection.rollback()
                raise 

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

def get_pid(connection: PgConnection) -> int:
    with connection.cursor() as cursor:
        try:
            cursor.execute("SELECT pg_backend_pid();")
            return int(cursor.fetchone()[0])
        except Exception as e:
            cursor.connection.rollback()
            raise 

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
    if args.load_mode in ["cpython", "wpython"]:
        print(f"Create schema and load data ({args.load_mode})")
        
        with get_connection(args.db_host, args.db_port, args.db_user, args.timeout_millis) as connection:
            create_db_with_copy(
                connection, 
                path_to_query_ddl=args.path_ddl_query,
                path_to_data=args.path_to_data, 
                path_to_output=args.result_path
            )

    benchmark(
        args.db_host, 
        args.db_port, 
        args.db_user, 
        args.timeout_millis, 
        args.queries_path, 
        args.result_path, 
        args.times
    )
