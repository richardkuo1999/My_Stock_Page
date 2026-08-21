"""Agent bridge abstraction."""

from abc import ABC, abstractmethod


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
    """Bridge to Antigravity CLI agent.

    TODO: Ticket 03 - Implement actual CLI integration.
    """

    async def send(self, prompt: str) -> str:
        raise NotImplementedError("AntigravityCLIBridge not yet implemented")

    async def is_available(self) -> bool:
        raise NotImplementedError("AntigravityCLIBridge not yet implemented")
