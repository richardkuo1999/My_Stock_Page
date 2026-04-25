import logging
import random
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any

from google.genai import Client as GeminiClient
from google.genai import types
from ollama import AsyncClient as OllamaClient

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class RequestType(Enum):
    TEXT = 1
    IMAGE = 2
    FILE = 3
    AUDIO = 4
    VIDEO = 5


async def ensure_ollama() -> bool:
    """Check Ollama service is running and the configured model is available.

    Starts the service if not running, pulls the model if missing.
    Returns True if ready, False otherwise.
    """
    if settings.AI_PROVIDER.lower() != "ollama":
        return True

    model = settings.OLLAMA_MODEL
    base_url = settings.OLLAMA_BASE_URL

    # 1. Check if Ollama service is reachable
    client = OllamaClient(host=base_url)
    try:
        await client.list()
        logger.info("Ollama service is running at %s", base_url)
    except Exception:
        # Try to start ollama serve in background
        if not shutil.which("ollama"):
            logger.error("Ollama is not installed. Please install from https://ollama.com")
            return False
        logger.info("Starting Ollama service...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for it to be ready
        import asyncio
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                await client.list()
                logger.info("Ollama service started successfully")
                break
            except Exception:
                continue
        else:
            logger.error("Failed to start Ollama service")
            return False

    # 2. Check if model is available, pull if missing
    try:
        resp = await client.list()
        installed = {m.model for m in resp.models}
        # Also match without tag (e.g. "qwen2.5:7b" matches "qwen2.5:7b")
        if model not in installed:
            logger.info("Model %s not found locally. Pulling...", model)
            print(f"⬇️  Pulling Ollama model: {model} (this may take a while)")
            await client.pull(model)
            logger.info("Model %s pulled successfully", model)
            print(f"✅ Model {model} ready")
        else:
            logger.info("Model %s is available", model)
    except Exception as e:
        logger.error("Failed to pull model %s: %s", model, e)
        return False

    return True


class AIService:
    """Service for AI interactions using Gemini or Ollama."""

    def __init__(self):
        self.provider = settings.AI_PROVIDER.lower()

        # Gemini
        self.gemini_keys = settings.GEMINI_API_KEYS or []
        self.current_key_idx = 0
        self.gemini_clients = [self._create_gemini_client(key) for key in self.gemini_keys]
        self.gemini_model = "gemini-3-flash"

        # Ollama
        self.ollama_client = OllamaClient(host=settings.OLLAMA_BASE_URL)
        self.ollama_model = settings.OLLAMA_MODEL

        logger.info("AIService initialized with provider: %s", self.provider)

    def _create_gemini_client(self, key: str):
        return GeminiClient(api_key=key).aio

    async def generate_content(self, prompt: str) -> str:
        """Simple text generation (legacy support)"""
        return await self.call(RequestType.TEXT, contents=prompt)

    # ========== Ollama ==========
    async def _call_ollama(
        self,
        req_type: RequestType,
        contents,
        prompt: str = None,
        use_search: bool = False,
    ) -> str:
        """Call Ollama local model."""
        if req_type == RequestType.TEXT:
            final_prompt = (
                prompt + "\n" + contents
                if prompt and isinstance(contents, str)
                else str(contents)
            )
            response = await self.ollama_client.chat(
                model=self.ollama_model,
                messages=[{"role": "user", "content": final_prompt}],
            )
            return response.message.content

        elif req_type in (RequestType.IMAGE, RequestType.FILE, RequestType.AUDIO):
            # Ollama multimodal: images via base64, audio via base64
            images = []
            audio_list = []
            text_parts = []

            if isinstance(contents, list):
                for mime, data in contents:
                    if mime.startswith("image/"):
                        import base64
                        images.append(base64.b64encode(data).decode())
                    elif mime.startswith("audio/"):
                        import base64
                        audio_list.append(base64.b64encode(data).decode())
                    else:
                        text_parts.append(f"[Attached file: {mime}]")
            elif isinstance(contents, (Path, str)):
                p = Path(contents)
                if p.exists():
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                        import base64
                        with open(p, "rb") as f:
                            images.append(base64.b64encode(f.read()).decode())
                    elif p.suffix.lower() in (".mp3", ".wav", ".ogg", ".flac", ".m4a"):
                        import base64
                        with open(p, "rb") as f:
                            audio_list.append(base64.b64encode(f.read()).decode())
                    elif p.suffix.lower() == ".pdf":
                        try:
                            import fitz
                            doc = fitz.open(p)
                            pdf_text = "\n".join(page.get_text() for page in doc)
                            doc.close()
                            text_parts.append(pdf_text)
                        except Exception:
                            text_parts.append(f"[PDF file: {p.name}]")

            msg_content = prompt or "請分析這份檔案/多媒體內容。"
            if text_parts:
                msg_content = "\n".join(text_parts) + "\n\n" + msg_content

            message = {"role": "user", "content": msg_content}
            if images:
                message["images"] = images
            if audio_list:
                message["audio"] = audio_list

            response = await self.ollama_client.chat(
                model=self.ollama_model,
                messages=[message],
            )
            return response.message.content

        return "Error: Unsupported request type for Ollama."

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
        """Unified AI dispatch — routes to Ollama or Gemini based on AI_PROVIDER."""
        # Google Search is Gemini-only; force fallback
        if use_search and self.provider == "ollama":
            logger.info("use_search requested — falling back to Gemini")
            try:
                return await self._call_gemini(req_type, contents, prompt, use_search)
            except Exception as e:
                logger.error(f"Gemini fallback for search failed: {e}")
                return f"Error: Google Search requires Gemini — {e}"

        if self.provider == "ollama":
            try:
                return await self._call_ollama(req_type, contents, prompt, use_search)
            except Exception as e:
                logger.error(f"Ollama failed: {type(e).__name__} - {e}")
                return f"Error: Ollama service unavailable - {e}"
        else:
            try:
                return await self._call_gemini(req_type, contents, prompt, use_search)
            except Exception as e:
                logger.error(f"Gemini failed: {type(e).__name__} - {e}")
                return f"Error: AI service unavailable - {e}"
