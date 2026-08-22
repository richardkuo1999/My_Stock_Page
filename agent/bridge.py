"""Agent bridge abstraction."""

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120  # seconds

# Repo root = parent of the `agent/` package. Used as the working directory for
# the agy subprocess so the Agent can run tools via relative paths (tools/xxx.py).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AgentBridge(ABC):
    """Abstract base class for agent communication."""

    @abstractmethod
    async def send(self, prompt: str) -> str:
        """Send a prompt to the agent and return its response."""
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
        """Send prompt to agy CLI and return response.

        Raises:
            TimeoutError: if process exceeds timeout
            RuntimeError: if process exits with non-zero code
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "agy", "-p", prompt,
                "--output-format", "json",
                # SECURITY / TEMPORARY: auto-approve all tool permissions so the
                # Agent can run tools/*.py in headless mode. This grants the Agent
                # UNRESTRICTED command execution — a prompt-injection risk if the
                # bot is exposed to untrusted users. Planned proper fix: expose the
                # 6 tools as an MCP server (agy mcp) so the Agent can ONLY call
                # those tools and never arbitrary shell. See ticket 03 / ARCHITECTURE.
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

        try:
            result = json.loads(stdout.decode())
            return result.get("response", stdout.decode().strip())
        except json.JSONDecodeError:
            # If not JSON, return raw stdout
            return stdout.decode().strip()

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
