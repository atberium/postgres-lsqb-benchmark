# LSQB on PostgreSQL 19: SQL/PGQ against explicit joins

## 📄 The full report: [`paper.pdf`](paper.pdf)

**[`paper.pdf`](paper.pdf) is the study itself** — 71 pages covering what SQL/PGQ in PostgreSQL 19 could
and could not execute on the LSQB benchmark, how fast, and why. Every figure in it is traceable to a file
in this repository. Read that first; this README describes the data behind it.

> **Status of the feature.** SQL/PGQ was reverted from PostgreSQL after beta 3 and **will not ship in
> version 19**. Beta 3 is the code measured here: `src/backend/rewrite/rewriteGraphTable.c` exists at tag
> `REL_19_BETA3` and not on `master`. Section 6.5 of the report separates the findings that belonged to
> that implementation from those that belong to PostgreSQL's planner and executor, and so still apply to
> whatever arrives next.

---

This repository holds the measurements behind the report: the harness, the query texts, the schema
definitions, and every raw result and query plan it cites, so that any figure quoted can be traced back to
the file it came from. The benchmark is [LSQB](https://github.com/ldbc/lsqb), the Labelled Subgraph Query
Benchmark of the Linked Data Benchmark Council.

The question the measurements address is narrow and practical. Matching a graph pattern in SQL takes one
`JOIN` per edge, written out explicitly, and grows with the pattern: nine edges mean a nine-way join
written out in full. SQL/PGQ lets the pattern be written instead. The PostgreSQL 19 betas were the first
place it appeared in PostgreSQL — other implementations exist, DuckPGQ over DuckDB among them — and this
is an attempt to find out what that implementation could and could not do.

## What is measured

Nine LSQB queries, expressed two ways over the same data:

- **the SQL/PGQ approach** — each query written as a `GRAPH_TABLE` pattern over a declared property graph;
- **the relational approach** — each query written with explicit `JOIN` operations, using LSQB's own
  reference implementations unchanged.

Both are run at six scale factors, SF 0.1 to SF 30, under three ways of supplying the derived relations that
the LSQB schema needs but the source data does not provide: plain tables (**PT**), non-materialised views
(**RV**), and materialised views (**MV**). That is 9 × 6 × 3 = 162 cells per approach, each run five times.

SF 100 sits outside that series: it was measured for SQL/PGQ only, in the first campaign, on a larger
instance and a longer timeout. It is not a seventh point on the same axis, and the report excludes it from
every cross-approach figure.

Each configuration records query latency, peak resident memory, on-disk footprint, load time, the returned
count for every query, and the query plan.

## Layout

```
queries/
  pgq/q1.sql … q9.sql        the nine queries as GRAPH_TABLE patterns
  sql/q1.sql … q9.sql        the nine queries as explicit joins, from LSQB unchanged
ddl/
  pgq/data-plain-tables.sql        schema and load for each storage strategy,
  pgq/data-regular-views.sql       over the projected layout the SQL/PGQ queries need
  pgq/data-materialized-views.sql
  sql/data-plain-tables.sql        the same three, over the merged layout the
  sql/data-regular-views.sql       relational queries need
  sql/data-materialized-views.sql
runs/
  campaign-1-initial/
    protocol.yaml            the conditions this campaign was run under
    harness.py               the harness that produced it
    {version}/{approach}/{STRATEGY}-sf{N}{projection}.txt
    {version}/{approach}/analyze/{STRATEGY}-sf{N}/q{1..9}.json
    {version}/{approach}/analyze/{STRATEGY}-sf{N}/_state.json
  campaign-2-controlled/
    protocol.yaml
    harness.py
    …same layout as above
```

`{version}` is `beta1`, `beta2` or `beta3`; `{approach}` is `pgq` or `sql`; `{projection}` is `projected`
for the SQL/PGQ schema and `merged` for the relational one.

The six DDL scripts are not six spellings of one schema. The two layouts differ in which relations exist
at all, in whether `Person_knows_Person` holds one row per undirected edge or two, and in whether anything
carries a primary key: every table in `ddl/pgq/` does, and no table in `ddl/sql/` does, the latter
following LSQB's own reference configuration. Within each layout the three scripts differ only in whether
the five derived relations are tables, views or materialised views.

**Read `protocol.yaml` before reading any data file.** The two campaigns were run under different
conditions, and the file states them: repetitions, whether `ANALYZE` was run, query order, timeouts,
instance flavours, and the exceptions that apply to particular versions or scale factors.

## The two campaigns

| | campaign 1, initial | campaign 2, controlled |
|---|---|---|
| Repetitions | 3 | 5 |
| `ANALYZE` before the queries | no | yes |
| Query order | filesystem, varies between configurations | sorted, identical everywhere |
| Per-repetition times | not recorded | recorded, timeouts marked |
| Plans | captured separately, in a different statistics state | captured per query, in the same state as the timings |
| Instance flavour | `2cpu-16ram` at SF 0.1, `8cpu-32ram` from SF 0.3 up, `20cpu-320ram` at SF 100 | `8cpu-32ram` at every scale factor |
| SF 100 | measured, SQL/PGQ only | not measured |

Campaign 2 is the one the report draws on. Campaign 1 is kept for two reasons: its SF 100 rows exist
nowhere else, and it is the only campaign measured without `ANALYZE`, which makes it the reference point
for what collecting statistics changed.

Because the two differ in more than one condition, **coverage may be compared across them and latency may
not**. Whether a query returns within the timeout is robust to repetition count and query order; how long
it takes is not, since query order determines cache state.

## Result file format

One line per query, then a summary line:

```
2026-08-21 02:37:09.176,q3.sql,[(30456,)],8.159,8.204,197432,[8.159;8.204;timeout;8.140;8.191]
failure_rate,4.444%
```

The fields are the timestamp, the query file, the returned count, the median and mean over the
repetitions, peak resident memory in kB, and — in campaign 2 only — the individual repetition times, with
`timeout` marking a cancelled run.

The trailing field is the reason to prefer campaign 2 for anything sensitive to dispersion: in campaign 1
a cell that lost repetitions reports a median computed over zeros, and the surviving runs can only be
recovered arithmetically.

## Query plans

Every plan is `EXPLAIN (VERBOSE, COSTS ON, SETTINGS ON, FORMAT JSON)` output, taken without executing the
query, so that a plan exists even for the queries that never finish. Beside each set sits `_state.json`,
which records the server settings and the contents of `pg_class` and `pg_stat_user_tables` before and
after `ANALYZE`. Without it a plan cannot be interpreted, because there is no way to tell what the planner
knew when it chose.

In campaign 2 the harness also fingerprints the statistics state before and after the run and warns if it
changed, so the claim that a plan and a timing share one state is checked rather than assumed.

## Running it

Load the dataset with the DDL script for the approach and storage strategy you want, substituting the
CSV directory for `PATHVAR`:

```sh
psql -f ddl/pgq/data-plain-tables.sql
```

Then measure:

```sh
python runs/campaign-2-controlled/harness.py \
  --queries-path ./queries/pgq \
  --result-path ./out/beta3-pgq-PT-sf1.txt \
  --times 5 \
  --timeout-millis 600000
```

Results go to `--result-path`; plans and `_state.json` go to a sibling directory named after it. The
harness runs `ANALYZE` itself, walks the queries in sorted order, and captures each plan immediately
before the repetitions of that query.

Requires Python 3.13, `psycopg2-binary` and `pydantic`. The datasets are the pre-generated LSQB ones from
the [SURF repository](https://repository.surfsara.nl/datasets/cwi/lsqb); the download scripts are
LSQB's own.

## What the measurements are not

They are a comparison of **two implementations**, not of two query languages. The two approaches differ in
physical schema, in indexing, in how `Person_knows_Person` is represented, and in where the query texts
came from: the relational ones are LSQB's, the SQL/PGQ ones were written for this work and may not be the
best available expression of these patterns.

The server ran on packaged defaults throughout, including `shared_buffers` at 128 MB and `work_mem` at
4 MB. No run was made under tuned configuration.

Two further limits are worth knowing before quoting a number. The PT-versus-MV comparison mixes
materialisation with indexing and element-key declaration, so it is a null result on these definitions
rather than a finding that the two are equivalent. And the association between `knows` edges and coverage
is a separation over nine queries, not a complexity criterion.

## References

- Mhedhbi, Lissandrini, Kuiper, Waudby, Szárnyas. *LSQB: a large-scale subgraph query benchmark.*
  GRADES-NDA '21. [10.1145/3461837.3464516](https://doi.org/10.1145/3461837.3464516)
- LSQB: [github.com/ldbc/lsqb](https://github.com/ldbc/lsqb)
- ISO/IEC 9075-16:2023, *SQL — Part 16: Property Graph Queries (SQL/PGQ)*
- "PostgreSQL to pull property graphs from v19 after design flaws", freenode.net, September 2026:
  [the revert discussion](https://freenode.net/article/postgresql-to-pull-property-graphs-from-v19-after-design-flaws)
