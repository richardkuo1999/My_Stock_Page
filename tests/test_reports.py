"""Tests for tools/analysis/reports.py — 研究報告清單整理（推播/Agent 用）。"""

from unittest.mock import AsyncMock, patch

import pytest

from tools.analysis.reports import get_reports, list_latest_reports


@pytest.mark.asyncio
async def test_list_latest_reports_success():
    """全站最新（推播用）：整理出 id/stock_code/title/date，data:{data:[...]} 形態。"""
    raw = {"status": "OK", "data": {"data": [
        {"id": 101, "name": "2330", "stock_name": "台積電",
         "question_type": "法說會重點", "content_date": "2026-09-10T00:00", "summary": "…"},
    ]}}
    with patch("tools.analysis.reports.raw_uanalyze.fetch_raw_report_summaries",
               new=AsyncMock(return_value=raw)):
        r = await list_latest_reports()
    assert r["reports"][0]["id"] == 101
    assert r["reports"][0]["stock_code"] == "2330"
    assert r["reports"][0]["title"] == "法說會重點"
    assert r["reports"][0]["date"] == "2026-09-10"


@pytest.mark.asyncio
async def test_list_latest_reports_flat_list():
    """data:[...] 扁平形態也支援。"""
    raw = {"data": [{"id": 5, "name": "2317", "question_type": "T"}]}
    with patch("tools.analysis.reports.raw_uanalyze.fetch_raw_report_summaries",
               new=AsyncMock(return_value=raw)):
        r = await list_latest_reports()
    assert r["reports"][0]["id"] == 5


@pytest.mark.asyncio
async def test_list_latest_reports_error():
    with patch("tools.analysis.reports.raw_uanalyze.fetch_raw_report_summaries",
               new=AsyncMock(return_value={"error": "登入失敗"})):
        r = await list_latest_reports()
    assert "error" in r


@pytest.mark.asyncio
async def test_get_reports_single_stock():
    raw = {"data": {"data": [{"id": 7, "question_type": "個股分析", "content_date": "2026-09-01"}]}}
    with patch("tools.analysis.reports.raw_uanalyze.fetch_raw_report_summaries",
               new=AsyncMock(return_value=raw)):
        r = await get_reports("2330")
    assert r["symbol"] == "2330"
    assert r["reports"][0]["id"] == 7
