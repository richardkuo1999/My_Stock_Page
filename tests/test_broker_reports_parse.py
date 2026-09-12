"""broker_reports 解析層的離線單元測試（不碰網路、不需憑證）。

用實際從朋友 Drive 觀察到的檔名/資料夾名當案例，鎖住解析行為。
執行：pytest tests/test_broker_reports_parse.py -q
"""

import sys
from pathlib import Path

# 讓測試能 import tools/raw/broker_reports.py（repo 根為 cwd 時 tools 是 package）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.raw.broker_reports import (
    ReportMeta,
    ext_of,
    parse_sector_filename,
    parse_stock_folder,
    stem_of,
    _yymmdd_to_iso,
)


def test_yymmdd_to_iso_normal():
    assert _yymmdd_to_iso("260911") == "2026-09-11"
    assert _yymmdd_to_iso("250101") == "2025-01-01"


def test_yymmdd_to_iso_month_unknown_day_zero():
    # '250900' 這種「月份確定、日不確定」寫法：保留年月、日補 01。
    assert _yymmdd_to_iso("250900") == "2025-09-01"


def test_yymmdd_to_iso_invalid():
    assert _yymmdd_to_iso("MS") == ""
    assert _yymmdd_to_iso("2609") == ""      # 太短
    assert _yymmdd_to_iso("261301") == ""    # 月份 13 非法


def test_parse_stock_folder_basic():
    assert parse_stock_folder("2330-台積電") == ("2330", "台積電")
    assert parse_stock_folder("4906-正文") == ("4906", "正文")


def test_parse_stock_folder_name_with_dash():
    # 名稱本身含 '-'（KY 股、TPK-KY）：只切第一個 '-'。
    assert parse_stock_folder("3673-TPK-KY") == ("3673", "TPK-KY")
    assert parse_stock_folder("2637-慧洋-KY") == ("2637", "慧洋-KY")


def test_parse_stock_folder_unknown_name():
    assert parse_stock_folder("4573-unknown") == ("4573", "unknown")


def test_parse_stock_folder_no_dash():
    assert parse_stock_folder("ETF清單") == ("ETF清單", "")


def test_parse_sector_filename_multiword_topic():
    r = parse_sector_filename("260911_中信_月營收評析_封測_半導體設備產業_sector.pdf")
    assert r["date"] == "2026-09-11"
    assert r["broker"] == "中信"
    assert r["category"] == "sector"
    assert r["ext"] == "pdf"
    assert "月營收評析" in r["topic"]
    assert "半導體設備產業" in r["topic"]


def test_parse_sector_filename_english_topic():
    r = parse_sector_filename("260622_MS_DRAM_NAND_sector.md")
    assert r["date"] == "2026-06-22"
    assert r["broker"] == "MS"
    assert r["topic"] == "DRAM NAND"
    assert r["category"] == "sector"
    assert r["ext"] == "md"


def test_parse_sector_filename_news_category():
    r = parse_sector_filename("260604_WSJ_Anthropic_AI_pause_news.md")
    assert r["date"] == "2026-06-04"
    assert r["broker"] == "WSJ"
    assert r["category"] == "news"
    assert "AI" in r["topic"]


def test_parse_sector_filename_unknown_category():
    # 最後一段非已知分類 → category='unknown'，該段保留在主題。
    r = parse_sector_filename("260729_工商時報_新聞_0000.pdf")
    assert r["date"] == "2026-07-29"
    assert r["broker"] == "工商時報"
    assert r["category"] == "unknown"


def test_parse_sector_filename_no_date():
    # 首段非日期 → date 留空，首段回歸主題當 broker。
    r = parse_sector_filename("財報狗_HDD產業_sector.html")
    assert r["date"] == ""
    assert r["broker"] == "財報狗"
    assert r["category"] == "sector"
    assert "HDD產業" in r["topic"]


def test_stem_pairs_md_and_pdf():
    # .md 與配對 .pdf 的 stem 相同 → 可辨識為同一份報告。
    assert stem_of("260622_MS_DRAM_NAND_sector.md") == stem_of(
        "260622_MS_DRAM_NAND_sector.pdf"
    )


def test_stem_with_dot_in_name():
    # 主幹含 '.'（罕見）：只切最後一個副檔名。
    assert stem_of("260804_MS_光模塊政策解讀.pdf_sector.md") == (
        "260804_MS_光模塊政策解讀.pdf_sector"
    )


def test_ext_of():
    assert ext_of("a.md") == "md"
    assert ext_of("a.PDF") == "pdf"
    assert ext_of("noext") == ""


def test_report_meta_to_dict_roundtrip():
    m = ReportMeta(file_id="x", scope="stock", stock_code="2330", stock_name="台積電")
    d = m.to_dict()
    assert d["file_id"] == "x"
    assert d["scope"] == "stock"
    assert d["stock_code"] == "2330"
    # 未設欄位為空字串（穩定 schema，方便序列化成 JSON）。
    assert d["broker"] == ""
