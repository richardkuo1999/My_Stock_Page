"""Tests for agent/quota_ledger.py — 額度帳本與 token→% 校準。"""

import json

import pytest

from agent import quota_ledger


@pytest.fixture
def ledger(tmp_path):
    """指向暫存檔的帳本路徑（不碰真實 data/logs）。"""
    return tmp_path / "quota_ledger.jsonl"


def _limits(pct: int, group: str = "Gemini", window: str = "週") -> list[dict]:
    return [{"group": group, "window": window, "remaining_pct": pct, "reset_at": ""}]


def test_record_appends_one_line_per_turn(ledger):
    quota_ledger.record(1000, _limits(98), path=ledger)
    quota_ledger.record(2000, _limits(98), path=ledger)

    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tokens"] == 1000
    assert first["turns"] == 1
    assert first["remaining"] == {"Gemini|週": 98}
    assert "timestamp" in first


def test_record_noop_without_limits(ledger):
    """拿不到額度時不寫入（避免記一堆沒有 remaining 的空觀測）。"""
    quota_ledger.record(1000, [], path=ledger)
    assert not ledger.exists()


def test_record_never_raises_on_bad_path(tmp_path):
    """記帳失敗只記 log、不拋例外（不能影響回覆）。"""
    bad = tmp_path / "not_a_dir"
    bad.write_text("x", encoding="utf-8")
    quota_ledger.record(1, _limits(98), path=bad / "ledger.jsonl")  # 不應拋


def test_record_with_before_enables_same_turn_calibration(ledger):
    """關鍵行為：把呼叫前快照一起記，本輪造成的下降立刻成為校準樣本。

    （實測發現的缺陷：只記呼叫後快照時，明明量到「本次 -2%」卻仍顯示「校準中」，
    白丟一個完美樣本。）
    """
    quota_ledger.record(
        202_455, _limits(95), before=_limits(97), path=ledger
    )
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2                       # pre + post
    pre = json.loads(lines[0])
    assert pre["phase"] == "pre" and pre["tokens"] == 0 and pre["turns"] == 0

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 1
    assert cal["tokens_per_pct"] == 202_455 / 2  # 一輪 2 個百分點


def test_record_skips_pre_entry_when_no_change(ledger):
    """沒有下降時不寫前置觀測（避免帳本充滿無意義的行）。"""
    quota_ledger.record(1000, _limits(98), before=_limits(98), path=ledger)
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_calibrate_ignores_drops_with_no_tracked_tokens(ledger):
    """外部消耗（直接用 agy CLI）造成的下降不當樣本，否則換算率會被壓成 0。"""
    # 兩筆都 tokens=0，但百分比掉了 → 不是我們造成的
    quota_ledger.record(0, _limits(98), path=ledger)
    quota_ledger.record(0, _limits(96), path=ledger)
    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 0
    assert "tokens_per_pct" not in cal

    # 之後有真實 token 的下降才算樣本
    quota_ledger.record(150_000, _limits(95), path=ledger)
    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 1
    assert cal["tokens_per_pct"] == 150_000


def test_calibrate_learns_tokens_per_pct(ledger):
    """掉 1 點前累積的 token 就是 1% 的成本（跨多次累積）。"""
    # 三次呼叫共 120k token 後，剩餘 98 → 97（掉 1 點）
    quota_ledger.record(50_000, _limits(98), path=ledger)
    quota_ledger.record(40_000, _limits(98), path=ledger)
    quota_ledger.record(30_000, _limits(97), path=ledger)

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 1
    assert cal["tokens_per_pct"] == 120_000      # 50k+40k+30k 對應 1 點
    assert cal["turns_per_pct"] == 3             # 也記次數（額度可能按次計）
    assert cal["pending_tokens"] == 0            # 掉點後歸零


def test_calibrate_averages_multiple_drops(ledger):
    """多次掉點取總量/總點數。"""
    quota_ledger.record(100_000, _limits(98), path=ledger)
    quota_ledger.record(100_000, _limits(97), path=ledger)   # 掉1 → 200k/1
    quota_ledger.record(100_000, _limits(95), path=ledger)   # 掉2 → 100k/2

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 2
    # 總計 300k tokens 對應 3 點 → 100k/點
    assert cal["tokens_per_pct"] == 100_000


def test_calibrate_treats_increase_as_window_reset(ledger):
    """剩餘 % 上升＝視窗重置，累積歸零、不產生樣本。"""
    quota_ledger.record(80_000, _limits(50), path=ledger)
    quota_ledger.record(80_000, _limits(100), path=ledger)   # 重置
    quota_ledger.record(20_000, _limits(99), path=ledger)    # 掉1 → 只算 20k

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["samples"] == 1
    assert cal["tokens_per_pct"] == 20_000


def test_calibrate_without_drop_reports_pending_only(ledger):
    """還沒掉點 → 無換算率，只有待歸屬累積量。"""
    quota_ledger.record(10_000, _limits(98), path=ledger)
    quota_ledger.record(10_000, _limits(98), path=ledger)

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert "tokens_per_pct" not in cal
    assert cal["samples"] == 0
    assert cal["pending_tokens"] == 20_000
    assert cal["pending_turns"] == 2


def test_calibrate_skips_corrupt_lines(ledger):
    quota_ledger.record(100_000, _limits(98), path=ledger)
    with ledger.open("a", encoding="utf-8") as f:
        f.write("{not json\n\n")
    quota_ledger.record(100_000, _limits(97), path=ledger)

    cal = quota_ledger.calibrate(path=ledger)["Gemini|週"]
    assert cal["tokens_per_pct"] == 200_000


def test_calibrate_empty_when_no_file(tmp_path):
    assert quota_ledger.calibrate(path=tmp_path / "nope.jsonl") == {}


def test_estimate_line_shows_pct_and_remaining_turns(ledger):
    """有校準後：本次約幾 % + 還可跑幾次。"""
    quota_ledger.record(100_000, _limits(98), path=ledger)
    quota_ledger.record(100_000, _limits(97), path=ledger)   # 1% ≈ 200k

    line = quota_ledger.estimate_line(50_000, _limits(97), path=ledger)
    assert "本次 ≈ Gemini 週額度 0.25%" in line       # 50k / 200k
    assert "校準 1% ≈ 200k tokens・樣本 1" in line
    assert "剩 97% 約可再跑 388 次" in line            # 97 / 0.25


def test_estimate_line_reports_calibrating_before_first_drop(ledger):
    """尚無掉點事件時說明在校準中，而不是給假數字。"""
    quota_ledger.record(10_000, _limits(98), path=ledger)
    line = quota_ledger.estimate_line(10_000, _limits(98), path=ledger)
    assert "額度校準中" in line
    assert "已記錄 1 次" in line


def test_estimate_line_empty_without_ledger(tmp_path):
    assert quota_ledger.estimate_line(1000, _limits(98), path=tmp_path / "x.jsonl") == ""


def test_human_readable_token_counts():
    assert quota_ledger._human(126_432) == "126k"
    assert quota_ledger._human(1_234_567) == "1.2M"
    assert quota_ledger._human(999) == "999"
