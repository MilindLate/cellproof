# Postgres target (1.0)

## Goal

`cellproof convert book.xlsx --target postgres` proves the workbook on Postgres, not only on DuckDB: every formula cell
is computed by SQL that ran on a real Postgres and compared with Excel's saved value, and the dbt project targets
`dbt-postgres`.

## Principles

- **DuckDB stays the reference.** The compiler keeps generating DuckDB SQL; that SQL is what Excel's saved values
  checked first, cell by cell. Postgres SQL is derived from it, never written separately per function.
- **The target is verified again.** Translated SQL runs on Postgres and each cell is compared with Excel's value a
  second time. A wrong translation can only be a FAIL. A batch that does not translate or does not run makes its
  cells - and every cell reading them, transitively - UNRESOLVED ("not yet on Postgres: <reason>"): no cell may read
  a value Postgres did not compute.
- **Nothing stays behind in the user's database.** The cells table is a temporary table; helper functions live in
  `pg_temp` (session-scoped). The dbt project creates its helpers in its own schema through a macro.

## Translation

1. `sqlglot.transpile(sql, read="duckdb", write="postgres")` for syntax.
2. Rewrites on sqlglot's tree for constructs it does not map (for example `arg_max(v, k)` in a one-column subquery ->
   `ORDER BY k DESC LIMIT 1`).
3. A prelude of Postgres functions with DuckDB's semantics where a rewrite is not enough (number -> text the Excel
   way, `%` on doubles, ...).
4. Where it is cheap and exactly equal in both engines, the compiler emits portable SQL instead (a boolean as a number
   is `CAST(CAST(b AS INTEGER) AS DOUBLE)`), re-verified by the whole suite and the corpus.

## Measuring

`docs/...` probe: compile workbooks, translate each verified batch, run on Postgres, compare with DuckDB. Baseline on
the example workbooks and five pycel fixtures (276 batches, 1,486 cells): 472 cells ran with DuckDB's values, ~1,000
did not run, 15 differed (all reading cells whose batch had failed: the dependents rule above). Failure classes by
cells blocked: boolean -> double casts 549, `printf` (number -> text) 215, `arg_max`/`arg_min` 121, `right`/`substring`
argument types 40, `%` on doubles 26, date building 25.

## Testing

- `pgserver` (a pip-installable Postgres) in the `postgres` extra for local runs; CI uses a Postgres service.
- Tests skip without Postgres, like the dbt tests skip without dbt.
