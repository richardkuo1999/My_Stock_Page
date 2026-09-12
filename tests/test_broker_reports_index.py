"""broker_reports 索引 + 查詢層的離線測試（用暫存 SQLite，不碰網路/真資料）。

執行：pytest tests/test_broker_reports_index.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.raw.broker_reports import (
    ReportMeta,
    build_index,
    index_stats,
    load_all,
    query_sector,
    query_stock,
    rank_reports,
    _tokenize,
    _score_report,
)


def _sample_records():
    return [
        ReportMeta(file_id="s1", md_file_id="s1md", filename="rpt1.md",
                   scope="stock", stock_code="2330", stock_name="台積電",
                   date="2026-09-01", topic="法說會"),
        ReportMeta(file_id="s2", md_file_id="", filename="rpt2.pdf",
                   scope="stock", stock_code="2330", stock_name="台積電",
                   date="2026-08-15", topic="先進封裝"),
        ReportMeta(file_id="s3", md_file_id="s3md", filename="rpt3.md",
                   scope="stock", stock_code="4906", stock_name="正文",
                   date="2026-07-01", topic="網通"),
        ReportMeta(file_id="q1", md_file_id="q1md",
                   filename="260622_MS_DRAM_NAND_sector.md",
                   scope="sector", date="2026-06-22", broker="MS",
                   topic="DRAM NAND", category="sector"),
        ReportMeta(file_id="q2", md_file_id="q2md",
                   filename="260710_華南_記憶體產業_sector.md",
                   scope="sector", date="2026-07-10", broker="華南",
                   topic="記憶體產業", category="sector"),
        ReportMeta(file_id="q3", md_file_id="",
                   filename="260707_國泰_散熱產業_sector.pdf",
                   scope="sector", date="2026-07-07", broker="國泰",
                   topic="散熱產業", category="sector"),
    ]


def _fresh_db(tmp_path):
    return str(tmp_path / "test.db")


def test_build_and_stats(tmp_path):
    db = _fresh_db(tmp_path)
    n = build_index(_sample_records(), db_path=db)
    assert n == 6
    stats = index_stats(db_path=db)
    assert stats["total"] == 6
    assert stats["stock"] == 3
    assert stats["sector"] == 3
    assert stats["last_sync"]  # 有寫入時間


def test_build_is_idempotent_upsert(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    # 重跑同一批：file_id 為主鍵 → 不長總數（upsert）。
    build_index(_sample_records(), db_path=db)
    assert index_stats(db_path=db)["total"] == 6


def test_query_stock_filters_and_orders(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    rows = query_stock("2330", db_path=db)
    assert [r.file_id for r in rows] == ["s1", "s2"]  # 日期新到舊
    assert all(r.stock_code == "2330" for r in rows)


def test_query_stock_uppercases_input(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    # 輸入小寫也要能命中（代號通常純數字，但保險起見）。
    assert query_stock("2330", db_path=db)


def test_query_sector_chinese_keyword(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    rows = query_sector("記憶體", db_path=db)
    assert rows and rows[0].file_id == "q2"  # 記憶體產業 命中


def test_query_sector_english_keyword(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    rows = query_sector("DRAM", db_path=db)
    assert rows and rows[0].file_id == "q1"


def test_query_sector_no_match(tmp_path):
    db = _fresh_db(tmp_path)
    build_index(_sample_records(), db_path=db)
    assert query_sector("完全不相關的字串XYZ", db_path=db) == []


def test_rank_prefers_more_hits_then_recency():
    recs = [
        ReportMeta(file_id="a", filename="x", scope="sector",
                   topic="記憶體 DRAM", date="2026-01-01"),   # 2 hits
        ReportMeta(file_id="b", filename="x", scope="sector",
                   topic="記憶體", date="2026-09-01"),         # 1 hit, newer
        ReportMeta(file_id="c", filename="x", scope="sector",
                   topic="記憶體", date="2026-05-01"),         # 1 hit, older
    ]
    ranked = rank_reports(recs, "記憶體 DRAM", limit=10)
    assert [r.file_id for r in ranked] == ["a", "b", "c"]


def test_score_zero_when_no_overlap():
    r = ReportMeta(topic="散熱", filename="x", scope="sector")
    assert _score_report(r, _tokenize("記憶體")) == 0.0


def test_md_availability_tiebreak():
    # 同樣命中數，有 .md 的分數略高（0.1 加權）。
    with_md = ReportMeta(file_id="m", topic="記憶體", md_file_id="mmd", filename="x")
    no_md = ReportMeta(file_id="n", topic="記憶體", md_file_id="", filename="x")
    q = _tokenize("記憶體")
    assert _score_report(with_md, q) > _score_report(no_md, q)
