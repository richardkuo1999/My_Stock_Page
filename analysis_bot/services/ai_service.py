import google.genai as genai
from google.genai import types
from typing import List, Optional, Union, Any
import random
import logging
from pathlib import Path
from enum import Enum
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
    """Service for AI interactions with key rotation using Gemini."""
    
    def __init__(self):
        self.gemini_keys = settings.GEMINI_API_KEYS or []
        self.current_key_idx = 0
        
        # Initialize Gemini Clients
        self.gemini_clients = [self._create_gemini_client(key) for key in self.gemini_keys]
        
        # Models
        self.gemini_model = "gemini-2.0-flash-exp" # Default strong model

    def _create_gemini_client(self, key: str):
        return genai.Client(api_key=key)

    async def generate_content(self, prompt: str) -> str:
        """Simple text generation (legacy support)"""
        return await self.call(RequestType.TEXT, contents=prompt)

    async def call(self, req_type: RequestType, contents: Union[str, List[Any], Path], prompt: str = None) -> str:
        """
        Unified interface for AI generation with retries and fallbacks.
        """
        if not self.gemini_clients:
            return "Error: No Gemini keys configured."

        # Models to try in order
        models_to_try = ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-pro"]
        
        # Retry parameters
        max_total_attempts = 10 
        attempt = 0
        
        import asyncio
        
        while attempt < max_total_attempts:
            client = self.gemini_clients[self.current_key_idx]
            current_model = models_to_try[0] # Always try the best available first? Or sticky?
            # Let's try iterating models if one fails consistently? 
            # Simplified: Use one model, if it fails with specific error, switch model?
            # Actually, let's try the primary model with rotation, if all fail, try secondary.
            
            # Better strategy: Loop through keys. If all keys fail for a model, switch model.
            # But the loop structure here is 'while attempt'.
            # Let's determine model based on overall attempts? No.
            
            # Let's keep it simple: Try current model. If 429, rotate key.
            # If 404/400 (invalid model), switch model permanent for this call?
            
            # Refined Loop logic:
            try:
                # Select model: If we failed many times, maybe downgrade?
                if attempt > len(self.gemini_clients) * 2:
                    current_model = models_to_try[1] # Downgrade to flash 1.5
                if attempt > len(self.gemini_clients) * 4:
                    current_model = models_to_try[2] # Downgrade to pro 1.5
                
                # If specifically 2.0, be careful?
                
                response_text = ""
                
                if req_type == RequestType.TEXT:
                    final_prompt = prompt + "\n" + contents if prompt and isinstance(contents, str) else str(contents)
                    response = client.models.generate_content(
                        model=current_model,
                        contents=final_prompt
                    )
                    response_text = response.text

                elif req_type in [RequestType.FILE, RequestType.IMAGE, RequestType.AUDIO]:
                    parts = []
                    
                    # Handle different content input types
                    if isinstance(contents, list):
                        # List of (mime, data) tuples
                        for mime, data in contents:
                             parts.append(types.Part.from_bytes(data=data, mime_type=mime))
                    
                    elif isinstance(contents, Path) or isinstance(contents, str):
                        # File path string or Path object
                         p = Path(contents)
                         if p.exists():
                             # Determine mime type based on extension if possible, or default
                             mime = "application/pdf" # Default fallback
                             if p.suffix.lower() == ".mp3":
                                 mime = "audio/mp3"
                             elif p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                                 mime = "image/jpeg"
                             elif p.suffix.lower() in [".wav"]:
                                 mime = "audio/wav"
                                 
                             # Read bytes
                             with open(p, "rb") as f:
                                 parts.append(types.Part.from_bytes(data=f.read(), mime_type=mime))
                    
                    if prompt: parts.append(prompt)
                    else: parts.append("請分析這份檔案/多媒體內容。")

                    response = client.models.generate_content(
                        model=current_model,
                        contents=parts
                    )
                    response_text = response.text

                return response_text

            except Exception as e:
                error_str = str(e)
                logger.warning(f"Gemini Attempt {attempt+1}/{max_total_attempts} failed (Key {self.current_key_idx}, Model {current_model}): {error_str}")
                
                # Check for 429 (Resource Exhausted)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    # Rotate key
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.gemini_clients)
                    
                    # Backoff
                    wait_time = 2 * (1.5 ** attempt) + random.uniform(0, 1)
                    if wait_time > 15: wait_time = 15
                    logger.info(f"Rate limit hit. Rotating key and waiting {wait_time:.2f}s...")
                    await asyncio.sleep(wait_time)
                    
                # Check for Model Not Found / Not Supported (404 or 400)
                elif "404" in error_str or "not found" in error_str.lower() or "400" in error_str:
                     # If model problem, remove it from list or switch to next
                     logger.warning(f"Model {current_model} failed. Switching fallback...")
                     if current_model in models_to_try:
                         # Move to next model preference globally for this call?
                         # Simple hack: just rely on the 'attempt count' logic above to pick next model
                         pass
                     # Don't rotate key, just retry (which will switch model due to attempt increment)
                     await asyncio.sleep(1)
                else:
                    # Other errors (auth, network), rotate key
                    self.current_key_idx = (self.current_key_idx + 1) % len(self.gemini_clients)
                    await asyncio.sleep(1)
                
                attempt += 1
        
        return "Error: All attempts failed. Service unavailable."


