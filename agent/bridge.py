"""Agent bridge abstraction."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # seconds (10 min) — @mention Agent 可能跑多個工具，需較長上限

# Repo root = parent of the `agent/` package. Used as the working directory for
# the agy subprocess so the Agent can run tools via relative paths (tools/xxx.py).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `/usage` 額度查詢用的較短逾時（只是查表，不該拖住回覆）。
QUOTA_TIMEOUT = 30  # seconds

# `/usage` 回傳的英文標籤 → 顯示用短名（對不到就保留原文）。
_QUOTA_GROUPS = {
    "Gemini Models": "Gemini",
    "Claude and GPT models": "Claude·GPT",
}
_QUOTA_WINDOWS = {
    "Weekly Limit Remaining": "週",
    "Five Hour Limit Remaining": "5 小時",
}


@dataclass
class ToolCall:
    """A single tool invocation the Agent made during a turn."""

    name: str
    parameters: dict = field(default_factory=dict)

    def summary(self) -> str:
        """One-line human-readable summary, e.g. `run_command(python tools/analysis/get_stock_price.py 2330)`.

        指令（CommandLine/Command）**完整顯示不截斷**，只把換行/多重空白壓成
        單一空白，讓每筆呼叫維持一行。非指令類工具取前兩個純量參數（如檔案路徑），
        同樣不截斷。
        """
        if not self.parameters:
            return self.name

        # 優先取 CommandLine / Command
        cmd = self.parameters.get("CommandLine") or self.parameters.get("Command")
        if cmd and isinstance(cmd, str):
            # 移除為了編碼加的前綴，保留乾淨的指令
            clean_cmd = (
                cmd.replace('$env:PYTHONIOENCODING="utf-8"; ', "")
                .replace("$env:PYTHONIOENCODING='utf-8'; ", "")
                .replace('export PYTHONIOENCODING="utf-8" && ', "")
                .replace("export PYTHONIOENCODING='utf-8' && ", "")
            ).strip()
            # 完整顯示（不截斷）；多行指令（python -c "..."）壓成單行，
            # 讓每筆呼叫各佔一行、清單仍好讀。
            clean_cmd = " ".join(clean_cmd.split())
            return f"{self.name}({clean_cmd})"

        # 其他工具走一般純量值挑選，優先跳過 metadata 欄位（如 toolAction, toolSummary）
        parts = []
        for k, v in self.parameters.items():
            if k in ("toolAction", "toolSummary"):
                continue
            if isinstance(v, (str, int, float, bool)):
                parts.append(" ".join(str(v).split()))
            if len(parts) >= 2:
                break

        if not parts:
            for k, v in self.parameters.items():
                if isinstance(v, (str, int, float, bool)):
                    parts.append(" ".join(str(v).split()))
                if len(parts) >= 2:
                    break

        return f"{self.name}({', '.join(parts)})" if parts else self.name


@dataclass
class AgentResult:
    """Structured result of one Agent turn.

    `response` is the final answer text (same as the old `send()` return).
    `tools` is the ordered list of tool calls the Agent made — this is what
    lets us show, in dev, *which tools the Agent actually used*.
    """

    response: str
    tools: list[ToolCall] = field(default_factory=list)
    status: str = ""
    conversation_id: str = ""
    usage: dict = field(default_factory=dict)

    def tools_line(self) -> str:
        """完整工具呼叫清單（不截斷），一筆一行並編號。

        例：
            🔧 本次用了（3 次呼叫）：
            1. run_command(.venv/bin/python tools/analysis/get_stock_price.py 2330)
            2. view_file(/path/to/file.py)
            3. ...

        呼叫次數多時整段會很長，text 模式由 handlers 依 Telegram 上限自動分段送出。
        """
        if not self.tools:
            return ""
        lines = [f"{i}. {t.summary()}" for i, t in enumerate(self.tools, 1)]
        return f"🔧 本次用了（{len(self.tools)} 次呼叫）：\n" + "\n".join(lines)

    def usage_line(self) -> str:
        """Token 用量一行（數量 + 佔比），無 usage 資料時回空字串。

        例：
            📊 Token：442,814（輸入 417,499・94.3%／輸出 25,315・5.7%／思考 13,661・3.1%）
            ｜快取讀 3,638,703（命中 89.7%）

        佔比為各項對 total_tokens 的比例；快取命中率 =
        cache_read /（cache_read + input），可看出重複 context 被快取省下多少。
        agy 未回 usage（或欄位缺）時只顯示拿得到的部分。
        """
        u = self.usage or {}
        total = u.get("total_tokens") or 0
        inp = u.get("input_tokens") or 0
        out = u.get("output_tokens") or 0
        think = u.get("thinking_tokens") or 0
        cache = u.get("cache_read_tokens") or 0
        if not any((total, inp, out, think, cache)):
            return ""

        def pct(n: int) -> str:
            return f"・{n / total * 100:.1f}%" if total else ""

        parts = []
        if inp:
            parts.append(f"輸入 {inp:,}{pct(inp)}")
        if out:
            parts.append(f"輸出 {out:,}{pct(out)}")
        if think:
            parts.append(f"思考 {think:,}{pct(think)}")

        line = f"📊 Token：{total:,}" if total else "📊 Token"
        if parts:
            line += "（" + "／".join(parts) + "）"
        if cache:
            hit = cache / (cache + inp) * 100 if (cache + inp) else 0
            line += f"｜快取讀 {cache:,}（命中 {hit:.1f}%）"
        return line


def _parse_usage_tsv(raw: str) -> list[dict]:
    """解析 `/usage` 的 TSV → [{group, window, remaining_pct, reset_at}]。

    只收「群組＋視窗＋百分比」都在的行；群組/視窗名做中文化對應，
    對不到就保留原文（agy 改字樣時仍可用，只是顯示英文）。
    """
    items = []
    for line in raw.strip().splitlines():
        cols = [c.strip() for c in line.split("\t")]
        if len(cols) < 3 or not cols[2].endswith("%"):
            continue
        try:
            remaining = int(cols[2].rstrip("%"))
        except ValueError:
            continue
        items.append({
            "group": _QUOTA_GROUPS.get(cols[0], cols[0]),
            "window": _QUOTA_WINDOWS.get(cols[1], cols[1]),
            "remaining_pct": remaining,
            "reset_at": cols[3] if len(cols) > 3 else "",
        })
    return items


def diff_quota(before: list[dict], after: list[dict]) -> list[dict]:
    """在 `after` 上標記本次消耗（`delta_pct` = before 剩餘 − after 剩餘）。

    `/usage` 只給**整數百分比**，所以單次 /ask 的差值通常是 0（額度沒掉到
    下一個整數）。故只在差值 > 0 時才標記，讓顯示端可以「有才寫」。
    配不到對應項（群組/視窗對不上）就原樣保留。
    """
    if not before or not after:
        return after
    prev = {(b.get("group"), b.get("window")): b.get("remaining_pct") for b in before}
    out = []
    for item in after:
        merged = dict(item)
        old = prev.get((item.get("group"), item.get("window")))
        new = item.get("remaining_pct")
        if isinstance(old, int) and isinstance(new, int) and old - new > 0:
            merged["delta_pct"] = old - new
        out.append(merged)
    return out


def format_quota_line(limits: list[dict]) -> str:
    """把額度資料排成可讀區塊；空資料回空字串。

    例：
        🎟️ 額度（已用／剩餘）
        Gemini：週 2%／98%・5 小時 3%／97%（重置 04:52）
        Claude·GPT：週 19%／81%・5 小時 0%／100%（重置 05:25）

    `limits` 為 `AgentBridge.fetch_usage_limits()` 的回傳（group/window/
    remaining_pct/reset_at）。群組與視窗名稱不寫死，照來源給的順序呈現。
    """
    if not limits:
        return ""

    grouped: dict[str, list[dict]] = {}
    for item in limits:
        grouped.setdefault(item.get("group", "?"), []).append(item)

    lines = ["🎟️ 額度（已用／剩餘）"]
    for group, items in grouped.items():
        segs = []
        for it in items:
            remaining = it.get("remaining_pct")
            if remaining is None:
                continue
            window = it.get("window", "")
            seg = f"{window} {100 - remaining}%／{remaining}%"
            # 本次消耗與重置時間合併成一組括號（避免「（本次 -2%）（重置 04:52）」相連）
            notes = []
            delta = it.get("delta_pct")
            if delta:
                notes.append(f"本次 -{delta}%")
            reset = _format_reset(it.get("reset_at", ""))
            if reset:
                notes.append(f"重置 {reset}")
            if notes:
                seg += "（" + "・".join(notes) + "）"
            segs.append(seg)
        if segs:
            lines.append(f"{group}：" + "・".join(segs))
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_reset(reset_at: str) -> str:
    """ISO8601（UTC）→ 本地時間短字串（跨月顯示日期）；無法解析回空字串。"""
    if not reset_at:
        return ""
    try:
        dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    now = datetime.now().astimezone()
    return dt.strftime("%H:%M") if dt.date() == now.date() else dt.strftime("%m/%d %H:%M")


class AgentBridge(ABC):
    """Abstract base class for agent communication."""

    @abstractmethod
    async def send(self, prompt: str) -> str:
        """Send a prompt to the agent and return its response text."""
        ...

    @abstractmethod
    async def send_detailed(self, prompt: str) -> AgentResult:
        """Send a prompt and return the full result (response + tool calls)."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the agent is reachable."""
        ...

    async def fetch_usage_limits(self) -> list[dict]:
        """剩餘額度（best-effort）。不支援的 bridge 回空 list。

        回傳 [{"group","window","remaining_pct","reset_at"}, ...]。
        """
        return []


class AntigravityCLIBridge(AgentBridge):
    """Bridge to Antigravity CLI agent via subprocess."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    async def send(self, prompt: str) -> str:
        """Send prompt to agy CLI and return just the response text.

        Thin wrapper over `send_detailed()` so existing callers that only want
        the answer string keep working.
        """
        return (await self.send_detailed(prompt)).response

    async def send_detailed(self, prompt: str) -> AgentResult:
        """Send prompt to agy CLI and return response + the tools it used.

        Uses `--output-format stream-json` (NDJSON): the CLI emits one event
        per line. `step_update` events with `step_type=tool` carry the tool
        name/params; the final `result` event carries the answer + usage.

        暫時性失敗（agy 回非 0 exit code，非 timeout）會自動重試一次——實測相同
        prompt 有時瞬時失敗、重跑即成功（agy 內部/網路抖動）。

        Raises:
            TimeoutError: if process exceeds timeout
            RuntimeError: if process exits with non-zero code（重試後仍失敗）
        """
        last_error = ""
        for attempt in range(1, 3):  # 最多兩次（首次 + 重試一次）
            try:
                return await self._run_once(prompt)
            except TimeoutError:
                raise  # 逾時不重試（可能本來就跑很久，重試只會再等一輪）
            except RuntimeError as e:
                last_error = str(e)
                if attempt == 1:
                    logger.warning("Agent 第 %d 次失敗，重試一次：%s", attempt, e)
        raise RuntimeError(last_error)

    async def _run_once(self, prompt: str) -> AgentResult:
        """實際呼叫一次 agy 子程序並解析結果。

        prompt 走 stdin（--input-format stream-json，一行 NDJSON），而非命令列參數。
        原本用 `agy -p <prompt>` 會把整段 prompt 當命令列參數；長 prompt（如 log
        稽核含上萬字 log）在 Windows 會超過命令列長度上限而報 WinError 206「檔名或副
        檔名太長」。改由 stdin 餵入即無長度限制、跨平台一致。stdin 訊息格式（實測）：
        {"event":"user","message":{"role":"user","content":<prompt>}}
        """
        stdin_msg = json.dumps(
            {"event": "user", "message": {"role": "user", "content": prompt}},
            ensure_ascii=False,
        ) + "\n"
        # agy 內層有自己的 --print-timeout（預設 5 分鐘）；若比外層 asyncio.wait_for
        # 短，會「內層先爆」→ log 出現 agy 的「timeout waiting for response」而外層的
        # self.timeout 根本用不到。故由 self.timeout 動態推導 agy 的 print-timeout，
        # 設為略短於外層（留 BUFFER 秒緩衝，讓外層 asyncio 當最後防線），下限 30s。
        _PRINT_TIMEOUT_BUFFER = 30
        agy_print_timeout = max(30, int(self.timeout) - _PRINT_TIMEOUT_BUFFER)
        try:
            proc = await asyncio.create_subprocess_exec(
                # -p 仍需帶值（agy 要求），給空字串；真正的 prompt 走 stdin。
                "agy", "-p", "",
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                # agy 內層 print 逾時，與外層 self.timeout 對齊（略短，見上）。
                "--print-timeout", f"{agy_print_timeout}s",
                # SCOPE: declare the repo as the Agent's workspace and run in a
                # sandbox with terminal restrictions. Together these confine file
                # search / access to the project — the Agent can still run
                # `python tools/xxx.py` (verified) but cannot `find` / read files
                # outside REPO_ROOT (verified: returns "被限制"). This fixes the
                # "agy scans the whole machine" problem.
                "--sandbox",
                "--add-dir", REPO_ROOT,
                # SECURITY / TEMPORARY: auto-approve all tool permissions so the
                # Agent can run tools/*.py in headless mode. Even with --sandbox
                # this still auto-approves in-workspace tool calls. It does NOT
                # widen the sandbox boundary (out-of-workspace access stays
                # blocked), but it does skip per-tool prompting — a prompt-
                # injection surface if the bot is exposed to untrusted users.
                # Planned proper fix: expose the tools as an MCP server (agy mcp)
                # so the Agent can ONLY call those tools. See ARCHITECTURE.
                "--dangerously-skip-permissions",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=REPO_ROOT,  # tools are referenced as tools/xxx.py relative to here
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_msg.encode("utf-8")), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error("Agent timed out after %ds", self.timeout)
            raise TimeoutError(f"Agent timed out after {self.timeout}s")

        out = stdout.decode() if stdout else ""
        err = stderr.decode().strip() if stderr else ""

        if proc.returncode != 0:
            # agy 常把錯誤細節寫在 stdout（stream-json 的 result event 或純文字），
            # stderr 可能是空的。合併兩者，優先取 stdout 裡可解析的錯誤，讓 log 有
            # 實際線索、而非只有 "Unknown error"。
            detail = self._extract_error(out) or err or "Unknown error"
            logger.error(
                "Agent exited with code %d: %s", proc.returncode, detail
            )
            raise RuntimeError(f"Agent error (code {proc.returncode}): {detail}")

        return self._parse_stream(out)

    @staticmethod
    def _extract_error(raw: str) -> str:
        """從 agy stdout 抽出可讀的錯誤訊息（供非 0 exit 時診斷用）。

        優先找 stream-json 裡 status 非 SUCCESS 的 result/error 事件；找不到就
        回傳去空白後的原始輸出尾段（截斷避免灌爆 log）。
        """
        if not raw:
            return ""
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            res = event.get("result")
            if isinstance(res, dict) and res.get("status") not in (None, "SUCCESS"):
                msg = res.get("error") or res.get("response") or res.get("status")
                if msg:
                    return str(msg)[:500]
            if event.get("event") == "error" or "error" in event:
                msg = event.get("error") or event.get("message")
                if msg:
                    return str(msg)[:500]
        # 無結構化錯誤：回原始輸出尾段當線索。
        tail = raw.strip()[-300:]
        return tail if tail else ""

    @staticmethod
    def _parse_stream(raw: str) -> AgentResult:
        """Parse agy stream-json (NDJSON) into an AgentResult.

        Tolerant of unexpected lines: skips anything that is not valid JSON.
        Falls back to treating the whole output as the response if no `result`
        event is found (e.g. plain-text output).
        """
        tools: list[ToolCall] = []
        result_event: dict | None = None

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            step = event.get("step_update")
            if isinstance(step, dict):
                # Record each tool call once, at its ACTIVE (start) event.
                if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
                    info = step.get("tool_info") or {}
                    tools.append(
                        ToolCall(
                            name=step.get("tool_name") or info.get("name") or "unknown",
                            parameters=info.get("parameters") or {},
                        )
                    )

            if "result" in event and isinstance(event["result"], dict):
                result_event = event["result"]

        if result_event is not None:
            return AgentResult(
                response=result_event.get("response", "").strip(),
                tools=tools,
                status=result_event.get("status", ""),
                conversation_id=result_event.get("conversation_id", ""),
                usage=result_event.get("usage") or {},
            )

        # No structured result — treat raw output as the response.
        return AgentResult(response=raw.strip(), tools=tools)

    async def is_available(self) -> bool:
        """Check if agy CLI is available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "agy", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError):
            return False

    async def fetch_usage_limits(self) -> list[dict]:
        """跑 `agy -p "/usage"` 取剩餘額度（best-effort，失敗回空 list）。

        agy 沒有 quota 子指令，額度只能靠內建 slash command `/usage`，它回 TSV：
            Gemini Models\\tWeekly Limit Remaining\\t98%\\t2026-09-18T14:17:59Z
        欄位＝群組、視窗、剩餘百分比、重置時間（UTC ISO8601）。

        約需數秒，故呼叫端應與主要 agent 呼叫**並行**執行、別串在後面。
        任何失敗（agy 不存在／逾時／格式變動）都只記 debug log 並回 []，
        不影響 /ask 回覆。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "agy", "-p", "/usage",
                "--print-timeout", f"{QUOTA_TIMEOUT}s",
                cwd=REPO_ROOT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=QUOTA_TIMEOUT + 5
            )
        except (FileNotFoundError, asyncio.TimeoutError, OSError) as e:
            logger.debug("fetch_usage_limits failed: %s", e)
            return []

        if proc.returncode != 0:
            return []
        return _parse_usage_tsv(stdout.decode("utf-8", errors="replace"))
