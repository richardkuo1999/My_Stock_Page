import logging
import random
from enum import Enum
from pathlib import Path
from typing import Any

from google.genai import Client as GeminiClient
from google.genai import types

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class RequestType(Enum):
    TEXT = 1
    IMAGE = 2
    FILE = 3
    AUDIO = 4
    VIDEO = 5


class AIService:
    """Service for AI interactions using Gemini."""

    def __init__(self):
        self.gemini_keys = settings.GEMINI_API_KEYS or []
        self.current_key_idx = 0

        # Initialize Gemini Clients
        self.gemini_clients = [self._create_gemini_client(key) for key in self.gemini_keys]
        self.gemini_model = "gemini-3-flash"

        logger.info("AIService initialized with provider: gemini")

    def _create_gemini_client(self, key: str):
        return GeminiClient(api_key=key).aio

    async def generate_content(self, prompt: str) -> str:
        """Simple text generation (legacy support)"""
        return await self.call(RequestType.TEXT, contents=prompt)

    # ========== Gemini ==========
    async def _call_gemini(
        self,
        req_type: RequestType,
        contents,
        prompt: str = None,
        use_search: bool = False,
    ) -> str:
        """Call Gemini with key rotation and model fallback."""
        if not self.gemini_clients:
            raise RuntimeError("No Gemini keys configured.")

        models_to_try = [
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-3-flash-lite",
            "gemini-2.5-flash-lite",
        ]
        max_total_attempts = 10
        attempt = 0

        import asyncio

        while attempt < max_total_attempts:
            client = self.gemini_clients[self.current_key_idx]
            # Cycle through models if we keep failing
            current_model = models_to_try[attempt % len(models_to_try)]

            try:
                config = None
                if use_search:
                    config = types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                    )

                if req_type == RequestType.TEXT:
                    final_prompt = (
                        prompt + "\n" + contents
                        if prompt and isinstance(contents, str)
                        else str(contents)
                    )
                    response = await client.models.generate_content(
                        model=current_model,
                        contents=final_prompt,
                        config=config,
                    )
                    return response.text

                elif req_type in [
                    RequestType.FILE,
                    RequestType.IMAGE,
                    RequestType.AUDIO,
                ]:
                    parts = []
                    if isinstance(contents, list):
                        for mime, data in contents:
                            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
                    elif isinstance(contents, (Path, str)):
                        p = Path(contents)
                        if p.exists():
                            mime = "application/pdf"
                            if p.suffix.lower() == ".mp3":
                                mime = "audio/mp3"
                            elif p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                                mime = "image/jpeg"
                            elif p.suffix.lower() == ".wav":
                                mime = "audio/wav"
                            with open(p, "rb") as f:
                                parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime))

                    parts.append(prompt if prompt else "請分析這份檔案/多媒體內容。")
                    response = await client.models.generate_content(
                        model=current_model,
                        contents=parts,
                        config=config,
                    )
                    return response.text

            except Exception as e:
                error_str = str(e)
                logger.warning(
                    f"Gemini Attempt {attempt + 1}/{max_total_attempts} failed (Key {self.current_key_idx}, Model {current_model}): {error_str}"
                )

                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.gemini_clients)
                    wait_time = min(2 * (1.5**attempt) + random.uniform(0, 1), 15)
                    logger.info(f"Rate limit hit. Rotating key, waiting {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                elif "404" in error_str or "not found" in error_str.lower() or "400" in error_str:
                    logger.warning(f"Model {current_model} failed. Switching fallback...")
                    await asyncio.sleep(1)
                else:
                    # For other errors, rotate key anyway as a precaution
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.gemini_clients)
                    await asyncio.sleep(1)

                attempt += 1

        raise RuntimeError("Gemini: All attempts failed.")

    # ========== Unified Dispatch ==========
    async def call(
        self,
        req_type: RequestType,
        contents: str | list[Any] | Path,
        prompt: str = None,
        use_search: bool = False,
    ) -> str:
        """Unified AI dispatch — always uses Gemini."""
        try:
            return await self._call_gemini(req_type, contents, prompt, use_search)
        except Exception as e:
            logger.error(f"Gemini failed: {type(e).__name__} - {e}")
            return f"Error: AI service unavailable - {e}"
