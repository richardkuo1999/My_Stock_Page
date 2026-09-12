"""額度帳本：從自己的使用資料校準「1% 額度 ≈ 幾 tokens / 幾次呼叫」。

為什麼需要：`agy -p "/usage"` 只回**整數百分比**剩餘額度，單次 `/ask` 通常掉不到
1 個百分點，所以看不出「本次用掉額度幾 %」；反過來 token 數是精算的，但 token
與訂閱額度的換算率官方沒公開。

做法：每次 `/ask` 把（本次 token、當下各視窗剩餘 %）append 到
`data/logs/quota_ledger.jsonl`。當某個視窗的剩餘掉 1 點時，把「上次掉點之後累積的
token / 掉的點數」當成一個樣本，即得 1% ≈ N tokens。樣本越多越準。

⚠️ Antigravity 的額度**可能不是按 token 計**（也可能按請求次數）。因此帳本同時記
「次數」，`calibrate()` 兩種都算，日後可比對哪個關係穩定。不需要額外 API 呼叫——
資料來自 handlers already 取得的前後額度快照。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/logs/quota_ledger.jsonl")

# 校準用的最少樣本數（掉點事件數）；不足時只顯示「校準中」而不給假精度。
MIN_SAMPLES = 1


def _key(item: dict) -> str:
    """視窗鍵：`群組|視窗`，例 `Gemini|週`。"""
    return f"{item.get('group', '?')}|{item.get('window', '?')}"


def record(
    tokens: int,
    limits: list[dict],
    before: list[dict] | None = None,
    path: Path | None = None,
) -> None:
    """記一次觀測（本次 token + 當下各視窗剩餘 %）。

    Best-effort：永不拋例外（記帳失敗不能影響回覆）。

    Args:
        tokens: 這一輪的 total_tokens。
        limits: `AgentBridge.fetch_usage_limits()` 的回傳（呼叫**後**的快照）。
        before: 呼叫**前**的快照。有給且與 after 不同時會多寫一筆 `tokens=0`
            的前置觀測——這樣「同一輪內」的百分比下降就能立刻成為校準樣本
            （否則要等下一輪才有相鄰紀錄可比，等於白丟一個樣本）。
        path: 覆寫帳本路徑（測試用；None＝用 `DEFAULT_PATH`，於執行時解析，
            測試才能以 monkeypatch 換掉預設路徑）。
    """
    if not limits:
        return
    path = path or DEFAULT_PATH
    try:
        def _snapshot(items: list[dict]) -> dict:
            return {
                _key(i): i["remaining_pct"]
                for i in items
                if isinstance(i.get("remaining_pct"), int)
            }

        now = datetime.now(timezone.utc).isoformat()
        entries = []
        after_snap = _snapshot(limits)
        if before:
            before_snap = _snapshot(before)
            # 只有當本輪確實造成下降時才需要前置觀測（否則多寫沒意義的行）
            if before_snap != after_snap:
                entries.append({
                    "timestamp": now,
                    "tokens": 0,        # 前置觀測本身不代表任何消耗
                    "turns": 0,
                    "remaining": before_snap,
                    "phase": "pre",
                })
        entries.append({
            "timestamp": now,
            "tokens": int(tokens or 0),
            "turns": 1,
            "remaining": after_snap,
        })

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 — 記帳不能影響回覆
        logger.warning("Failed to record quota ledger: %s", e)


def _load(path: Path) -> list[dict]:
    """讀帳本（壞行跳過）；檔案不存在回空 list。"""
    if not path.exists():
        return []
    entries = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.debug("read quota ledger failed: %s", e)
        return []
    return entries


def calibrate(path: Path | None = None) -> dict[str, dict]:
    """從帳本算各視窗的換算率。

    掉點事件＝某視窗剩餘 % 下降。該事件的成本 = 上次掉點後（含本筆）累積的
    token 與次數，除以掉的點數。剩餘 % **上升**視為視窗重置，累積歸零。

    Returns:
        {視窗鍵: {"tokens_per_pct": float, "turns_per_pct": float,
                  "samples": int, "pending_tokens": int, "pending_turns": int}}
        沒有掉點事件的視窗只有 pending_*（尚無法校準）。
    """
    entries = _load(path or DEFAULT_PATH)
    stats: dict[str, dict] = {}
    prev: dict[str, int] = {}

    for e in entries:
        tokens = int(e.get("tokens") or 0)
        turns = int(e.get("turns") or 1)
        remaining = e.get("remaining") or {}
        if not isinstance(remaining, dict):
            continue

        for key, pct in remaining.items():
            if not isinstance(pct, int):
                continue
            s = stats.setdefault(
                key,
                {
                    "tokens_in_drops": 0,
                    "turns_in_drops": 0,
                    "pct_dropped": 0,
                    "samples": 0,
                    "pending_tokens": 0,
                    "pending_turns": 0,
                },
            )
            s["pending_tokens"] += tokens
            s["pending_turns"] += turns

            old = prev.get(key)
            if old is not None:
                drop = old - pct
                if drop > 0:
                    # 累積 token 為 0 的下降＝消耗發生在本專案之外（例如直接用
                    # agy CLI）。收下去會把換算率壓成 0，故只歸零累積、不當樣本。
                    if s["pending_tokens"] > 0:
                        s["tokens_in_drops"] += s["pending_tokens"]
                        s["turns_in_drops"] += s["pending_turns"]
                        s["pct_dropped"] += drop
                        s["samples"] += 1
                    s["pending_tokens"] = 0
                    s["pending_turns"] = 0
                elif drop < 0:      # 視窗重置 → 累積歸零，不當樣本
                    s["pending_tokens"] = 0
                    s["pending_turns"] = 0
            prev[key] = pct

    out = {}
    for key, s in stats.items():
        row = {
            "samples": s["samples"],
            "pending_tokens": s["pending_tokens"],
            "pending_turns": s["pending_turns"],
        }
        if s["pct_dropped"] > 0:
            row["tokens_per_pct"] = s["tokens_in_drops"] / s["pct_dropped"]
            row["turns_per_pct"] = s["turns_in_drops"] / s["pct_dropped"]
        out[key] = row
    return out


def estimate_line(
    tokens: int,
    limits: list[dict],
    path: Path | None = None,
) -> str:
    """「本次約用掉額度幾 %」+「還可跑幾次」；資料不足時回校準進度。

    只取有校準資料的視窗（實際在消耗的模型群組才會掉點），最多顯示兩個視窗，
    避免訊息過長。完全無資料時回空字串。
    """
    cal = calibrate(path)
    if not cal:
        return ""

    remaining_by_key = {
        _key(i): i["remaining_pct"]
        for i in limits
        if isinstance(i.get("remaining_pct"), int)
    }

    lines = []
    for key, row in cal.items():
        tpp = row.get("tokens_per_pct")
        if not tpp or row["samples"] < MIN_SAMPLES or key not in remaining_by_key:
            continue
        pct = tokens / tpp if tokens else 0.0
        group, _, window = key.partition("|")
        seg = (
            f"📐 本次 ≈ {group} {window}額度 {pct:.2f}%"
            f"（校準 1% ≈ {_human(tpp)} tokens・樣本 {row['samples']}）"
        )
        if pct > 0:
            left = int(remaining_by_key[key] / pct)
            seg += f"；剩 {remaining_by_key[key]}% 約可再跑 {left} 次"
        lines.append(seg)
        if len(lines) >= 2:
            break

    if lines:
        return "\n".join(lines)

    # 還沒有掉點事件 → 顯示校準進度，讓使用者知道在累積、不是壞了
    pending = max((r.get("pending_turns", 0) for r in cal.values()), default=0)
    if pending:
        return (
            f"📐 額度校準中（已記錄 {pending} 次；等某視窗掉 1% 後即可估算"
            f"本次佔額度幾 %）"
        )
    return ""


def _human(n: float) -> str:
    """126432.0 → '126k'；1234567 → '1.2M'。"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return f"{n:.0f}"
