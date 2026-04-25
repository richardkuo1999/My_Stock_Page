# AI Service

## Overview
**Location:** `analysis_bot/services/ai_service.py`

## Architecture

The `AIService` class provides AI operations using Google Gemini (primary) or Ollama (local fallback) with automatic key rotation and model fallback.

## Configuration

Configuration is loaded from `Settings` class in `config.py`:

```python
class Settings(BaseSettings):
    GEMINI_API_KEYS: list[str] = []  # Multiple keys for rotation
    OLLAMA_MODEL: str = ""           # e.g. "llama3.2", empty = disabled
```

## Ollama Integration (`_call_ollama`)

**Features:**
- Local model support via Ollama HTTP API (`http://localhost:11434`)
- Auto-start: `ensure_ollama()` checks/starts Ollama service and pulls model at app startup
- Used when `OLLAMA_MODEL` is set and Gemini keys are unavailable

## Gemini Integration (`_call_gemini`)

**Features:**
- Multiple API key rotation (handles rate limits)
- Model fallback chain:
  ```
  gemini-3-flash → gemini-2.5-flash → gemini-3-flash-lite → gemini-2.5-flash-lite
  ```
- Google Search grounding (`use_search=True`)

**Key Rotation Logic:**
```python
if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
    self.current_key_idx = (self.current_key_idx + 1) % len(self.gemini_clients)
    wait_time = min(2 * (1.5**attempt) + random.uniform(0, 1), 15)
    await asyncio.sleep(wait_time)
```

## Request Types

```python
class RequestType(Enum):
    TEXT = 1
    IMAGE = 2
    FILE = 3
    AUDIO = 4
    VIDEO = 5
```

## Usage Examples

**Text Generation:**
```python
ai = AIService()
response = await ai.call(RequestType.TEXT, contents="Analyze this stock", use_search=True)
```

**File Analysis:**
```python
# contents is List[Tuple[mime_type, bytes]]
response = await ai.call(RequestType.FILE, contents=[("application/pdf", pdf_bytes)], prompt=prompt)
```

## Key Use Cases in Codebase

| Feature | File | RequestType | Notes |
|---------|------|-------------|-------|
| Stock Info Summary | handlers.py | TEXT | with search |
| Research Analysis | handlers.py | FILE | multimodal |
| Chat Mode | handlers.py | TEXT | with search |
| News Summary | jobs.py | TEXT | text only |

## Adding a New AI Feature

1. Import `AIService` and `RequestType` in your handler/service
2. Create instance: `ai = AIService()`
3. Call with appropriate request type
4. Handle potential exceptions (network timeout, rate limits)