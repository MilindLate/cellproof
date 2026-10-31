"""The Postgres target (cellproof.postgres): every cell verified again on a real Postgres."""
import json

import pytest

pytest.importorskip("sqlglot")
pytest.importorskip("psycopg")
pgserver = pytest.importorskip("pgserver")

from xlsxkit import book_of, write_xlsx  # noqa: E402

from cellproof import postgres  # noqa: E402
from cellproof.cli import main  # noqa: E402
from cellproof.compiler import compile_book  # noqa: E402


@pytest.fixture(scope="module")
def con():
    with postgres.connect() as c:
        yield c


def test_a_workbook_verifies_on_postgres(con):
    book = book_of({"S": {"A1": 2.0, "A2": 3.0, "B1": ("=A1*A2+1", 7.0), "B2": ('=IF(B1>5,"big","small")', "big"),
                          "B3": ("=SUM(A1:A2)", 5.0), "B4": ("=B1/0", "#DIV/0!")}})
    got = {v.key: v.status for v in postgres.verify(book, compile_book(book), con)}
    assert set(got.values()) == {"PASS"}


def test_what_postgres_cannot_run_is_unresolved_with_every_cell_reading_it(con, monkeypatch):
    book = book_of({"S": {"A1": 2.0, "B1": ("=A1*3", 6.0), "C1": ("=B1+1", 7.0), "D1": ("=A1+10", 12.0)}})
    import cellproof.compiler as compiler
    monkeypatch.setattr(compiler, "BATCH", 1)
    compiled = compile_book(book)
    real = postgres.translate
    monkeypatch.setattr(postgres, "translate",
                        lambda sql: real(sql).replace("3.0", "no_such_column") if "3.0" in sql else real(sql))
    got = {v.key: v for v in postgres.verify(book, compiled, con)}
    assert got[("S", 1, 2)].status == "UNRESOLVED" and "Postgres refused" in got[("S", 1, 2)].reason
    assert got[("S", 1, 3)].status == "UNRESOLVED" and "depends on S!B1" in got[("S", 1, 3)].reason
    assert got[("S", 1, 4)].status == "PASS"


def test_cli_target_postgres(tmp_path):
    wb = tmp_path / "b.xlsx"
    write_xlsx(wb, {"S": {"A1": 2.0, "B1": ("=A1*3", 6.0)}})
    assert main(["convert", str(wb), "--out", str(tmp_path / "out"), "--target", "postgres"]) == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert any("verified on Postgres" in f for f in report["findings"])


def test_list_indexes_survive_translation(con):
    # sqlglot's index offsets once turned xs[LEAST(i + 1, n)] into xs[LEAST(...) + -1]: PERCENTILE took the wrong
    # element on Postgres (formulas' test.xlsx, caught by the second verification)
    book = book_of({"S": {"A1": 1.0, "A2": 3.0, "A3": 2.0, "A4": 4.0, "B1": ("=PERCENTILE(A1:A4,0.3)", 1.9),
                          "B2": ("=QUARTILE(A1:A4,3)", 3.25), "B3": ("=LARGE(A1:A4,2)", 3.0),
                          "B4": ('=SUBSTITUTE("a-b-c","-","+",2)', "a-b+c")}})
    got = {v.key: (v.status, v.actual) for v in postgres.verify(book, compile_book(book), con)}
    assert {s for s, _ in got.values()} == {"PASS"}, got


def test_duckdb_substr_semantics_on_postgres(con):
    import duckdb
    con.execute(postgres.PRELUDE)
    for a, n in [(3, -1), (3, 0), (0, 2), (-1, 2), (-3, 2), (1, -5), (2, 10), (6, 2), (0, -1), (-10, 3), (2, None)]:
        q = f"SELECT substr('hello', {a}, {n})" if n is not None else f"SELECT substr('hello', {a})"
        assert con.execute(postgres.translate(q)).fetchone()[0] == duckdb.sql(q).fetchall()[0][0], (a, n)


def test_rounding_ties_go_away_from_zero_on_postgres(con):
    # Postgres's round(double) rounds 100.5 to 100 (ties to even); Excel, DuckDB and these cells go away from zero
    book = book_of({"S": {"A1": ("=ROUND(2.5,0)", 3.0), "A2": ("=ROUND(-2.5,0)", -3.0), "A3": ("=ROUND(1.005,2)", 1.01),
                          "A4": ("=ROUND(2.675,2)", 2.68), "A5": ("=MROUND(5,2)", 6.0), "A6": ("=ROUND(0.5,0)", 1.0)}})
    got = {v.key: (v.status, v.actual) for v in postgres.verify(book, compile_book(book), con)}
    assert {s for s, _ in got.values()} == {"PASS"}, got
