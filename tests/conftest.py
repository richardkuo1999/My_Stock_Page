"""Shared test fixtures.

主要目的：**避免測試寫進真實的 `data/` 執行期檔案**。額度帳本
（`agent/quota_ledger.py`）會被 handlers 在 `/ask` 流程中寫入，若測試用到真實
路徑，假資料（例如 mock 的 98%→96% 掉點）會汙染真實校準結果。
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_quota_ledger(tmp_path, monkeypatch):
    """把額度帳本預設路徑導到暫存目錄（所有測試自動套用）。"""
    from agent import quota_ledger

    monkeypatch.setattr(
        quota_ledger, "DEFAULT_PATH", tmp_path / "quota_ledger.jsonl"
    )
