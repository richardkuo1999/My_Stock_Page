"""Agent bridge abstraction."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # seconds (10 min) — @mention Agent 可能跑多個工具，需較長上限

# Repo root = parent of the `agent/` package. Used as the working directory for
# the agy subprocess so the Agent can run tools via relative paths (tools/xxx.py).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class ToolCall:
    """A single tool invocation the Agent made during a turn."""

    name: str
    parameters: dict = field(default_factory=dict)

    def summary(self) -> str:
        """One-line human-readable summary, e.g. `run_command(python tools/get_stock_price.py 2330)`.

        Picks a couple of representative parameter values so the dev can see
        *what* the tool was called with without dumping the whole payload.
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
            if len(clean_cmd) > 50:
                clean_cmd = clean_cmd[:47] + "..."
            return f"{self.name}({clean_cmd})"

        # 其他工具走一般純量值挑選，優先跳過 metadata 欄位（如 toolAction, toolSummary）
        parts = []
        for k, v in self.parameters.items():
            if k in ("toolAction", "toolSummary"):
                continue
            if isinstance(v, (str, int, float, bool)):
                s = str(v)
                if len(s) > 40:
                    s = s[:37] + "..."
                parts.append(s)
            if len(parts) >= 2:
                break

        if not parts:
            for k, v in self.parameters.items():
                if isinstance(v, (str, int, float, bool)):
                    s = str(v)
                    if len(s) > 40:
                        s = s[:37] + "..."
                    parts.append(s)
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
        """`🔧 本次用了：run_command(...), view_file(...)` or empty string."""
        if not self.tools:
            return ""
        return "🔧 本次用了：" + "、".join(t.summary() for t in self.tools)


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

        Raises:
            TimeoutError: if process exceeds timeout
            RuntimeError: if process exits with non-zero code
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "agy", "-p", prompt,
                "--output-format", "stream-json",
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
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=REPO_ROOT,  # tools are referenced as tools/xxx.py relative to here
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.error("Agent timed out after %ds", self.timeout)
            raise TimeoutError(f"Agent timed out after {self.timeout}s")

        if proc.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            logger.error("Agent exited with code %d: %s", proc.returncode, error_msg)
            raise RuntimeError(f"Agent error (code {proc.returncode}): {error_msg}")

        return self._parse_stream(stdout.decode())

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
