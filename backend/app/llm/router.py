"""
LLM Router — production-grade multi-provider router.

Priority order:
  1. Local Ollama (if reachable)
  2. Groq API (if GROQ_API_KEY set) — FREE tier: 14,400 req/day
  3. OpenRouter API (if OPENROUTER_API_KEY set) — free models available
  4. RAISE RuntimeError — never return mock data

Changes from original:
  - Removed _generate_mock_json_for_schema (mock data is banned)
  - Added availability check cache (ollama ping at startup)
  - Added retry with exponential backoff on each provider
  - Proper JSON extraction from LLM response (strip markdown fences)
  - Groq model updated to use llama-3.3-70b-versatile (best free model)
  - OpenRouter uses free google/gemma-3-27b-it model
  - clear error if all providers unavailable
"""
import json
import logging
import time
import asyncio
from typing import Optional, Dict, Any, Type
import httpx
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger("autoapply_ai.llm")

# ---------------------------------------------------------------------------
# Availability cache — probe each provider once per process lifetime
# ---------------------------------------------------------------------------
_ollama_available: Optional[bool] = None
_ollama_models: list = []

def _check_ollama_sync() -> bool:
    """Synchronous probe of Ollama — called once at module load."""
    try:
        import requests
        r = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            data = r.json()
            models = [m["name"] for m in data.get("models", [])]
            logger.info(f"Ollama is available. Models: {models}")
            return True
    except Exception as e:
        logger.warning(f"Ollama not reachable at startup: {e}")
    return False


def _probe_ollama_once() -> bool:
    global _ollama_available
    if _ollama_available is None:
        _ollama_available = _check_ollama_sync()
    return _ollama_available


def _extract_json(text: str) -> str:
    """Strip markdown code fences and extract raw JSON."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


class LLMRouter:
    def __init__(self):
        self.ollama_url = settings.OLLAMA_BASE_URL
        self.default_model = settings.OLLAMA_DEFAULT_MODEL
        self.groq_key = settings.GROQ_API_KEY
        self.openrouter_key = settings.OPENROUTER_API_KEY

    async def think(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        response_model: Optional[Type[BaseModel]] = None,
        temperature: float = 0.2,
        max_retries: int = 2
    ) -> str:
        """
        Core LLM call dispatching: Ollama → Groq → OpenRouter.
        
        NEVER returns mock data.
        Raises RuntimeError if all providers fail.
        """
        target_model = model or self.default_model
        errors = []

        # ── 1. Local Ollama ──────────────────────────────────────────────────
        if _probe_ollama_once():
            for attempt in range(max_retries):
                try:
                    content = await asyncio.wait_for(
                        self._call_ollama(
                            target_model, prompt, system_prompt,
                            response_model, temperature
                        ),
                        timeout=15.0
                    )
                    if content:
                        logger.info(f"Ollama answered. model='{target_model}' attempt={attempt+1}")
                        return _extract_json(content) if response_model else content
                except Exception as e:
                    wait = 0.5 * (2 ** attempt)
                    logger.warning(f"Ollama attempt {attempt+1} failed: {e}. Retry in {wait}s")
                    await asyncio.sleep(wait)
                    errors.append(f"Ollama[{attempt+1}]: {e}")
            logger.warning("Ollama failed all retries. Trying cloud fallback.")
        else:
            errors.append("Ollama: not reachable (offline or not installed)")

        if not settings.LLM_FALLBACK_ENABLED:
            raise RuntimeError(f"LLM fallback disabled. Ollama failed: {errors}")

        # ── 2. Groq API ──────────────────────────────────────────────────────
        if self.groq_key:
            groq_delays = [1.0, 2.0, 4.0]
            groq_attempts = 4  # Initial attempt + 3 retries
            
            for attempt in range(groq_attempts):
                try:
                    logger.info(f"Groq API call: attempt {attempt+1}/{groq_attempts}")
                    content = await asyncio.wait_for(
                        self._call_groq(
                            prompt, system_prompt, response_model, temperature
                        ),
                        timeout=15.0
                    )
                    
                    if not content:
                        raise ValueError("Empty response received from Groq API")
                        
                    # Validate JSON structure if a response model is expected
                    if response_model:
                        clean_json = _extract_json(content)
                        json.loads(clean_json)
                        
                    logger.info(f"Groq answered successfully on attempt {attempt+1}")
                    return _extract_json(content) if response_model else content
                    
                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError, 
                        json.JSONDecodeError, KeyError, ValueError, asyncio.TimeoutError) as e:
                    
                    # Identify the error category
                    is_429 = False
                    if isinstance(e, httpx.HTTPStatusError):
                        is_429 = (e.response.status_code == 429)
                        err_msg = f"HTTP status {e.response.status_code}"
                    elif isinstance(e, asyncio.TimeoutError) or isinstance(e, httpx.TimeoutException):
                        err_msg = "Timeout"
                    elif isinstance(e, httpx.ConnectError):
                        err_msg = "Connection error"
                    else:
                        err_msg = f"Invalid response: {e}"
                        
                    if attempt < len(groq_delays):
                        wait = groq_delays[attempt]
                        logger.warning(f"Groq attempt {attempt+1} failed due to {err_msg}. Retrying in {wait}s...")
                        await asyncio.sleep(wait)
                        errors.append(f"Groq[attempt={attempt+1}]: {err_msg} (retrying)")
                    else:
                        logger.warning(f"Groq attempt {attempt+1} failed due to {err_msg}. No retries left.")
                        errors.append(f"Groq[attempt={attempt+1}]: {err_msg} (failed)")
            logger.warning("Groq failed all attempts. Switching to OpenRouter.")
        else:
            errors.append("Groq: no API key configured (set GROQ_API_KEY in .env)")

        # ── 3. OpenRouter API ────────────────────────────────────────────────
        if self.openrouter_key:
            for attempt in range(max_retries):
                try:
                    content = await asyncio.wait_for(
                        self._call_openrouter(
                            prompt, system_prompt, response_model, temperature
                        ),
                        timeout=15.0
                    )
                    if content:
                        logger.info(f"OpenRouter answered. attempt={attempt+1}")
                        return _extract_json(content) if response_model else content
                except Exception as e:
                    wait = 1.0 * (2 ** attempt)
                    logger.warning(f"OpenRouter attempt {attempt+1} failed: {e}. Retry in {wait}s")
                    await asyncio.sleep(wait)
                    errors.append(f"OpenRouter[{attempt+1}]: {e}")
        else:
            errors.append("OpenRouter: no API key configured (set OPENROUTER_API_KEY in .env)")

        # ── 4. ALL FAILED — raise, never mock ────────────────────────────────
        error_summary = " | ".join(errors)
        logger.error(f"ALL LLM providers failed: {error_summary}")
        raise RuntimeError(
            f"All LLM providers failed. Errors: {error_summary}. "
            "To fix: (1) Start Ollama, OR (2) Set GROQ_API_KEY in .env "
            "(free at https://console.groq.com), OR (3) Set OPENROUTER_API_KEY."
        )

    # ── Provider implementations ─────────────────────────────────────────────

    async def _call_ollama(
        self, model: str, prompt: str, system_prompt: Optional[str],
        response_model: Optional[Type[BaseModel]], temperature: float
    ) -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)) as client:
            url = f"{self.ollama_url}/api/chat"
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "options": {"temperature": temperature},
                "stream": False
            }
            if response_model:
                payload["format"] = "json"

            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")

    async def _call_groq(
        self, prompt: str, system_prompt: Optional[str],
        response_model: Optional[Type[BaseModel]], temperature: float
    ) -> str:
        # Best free Groq model: llama-3.3-70b-versatile (131k context, fast)
        groq_model = "llama-3.3-70b-versatile"
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json"
            }
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload: Dict[str, Any] = {
                "model": groq_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048
            }
            if response_model:
                payload["response_format"] = {"type": "json_object"}

            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json().get("choices", [{}])[0].get("message", {}).get("content", "")

    async def _call_openrouter(
        self, prompt: str, system_prompt: Optional[str],
        response_model: Optional[Type[BaseModel]], temperature: float
    ) -> str:
        # Use a reliable free model: google/gemma-3-27b-it:free
        or_model = "google/gemma-3-27b-it:free"
        async with httpx.AsyncClient(timeout=45.0) as client:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openrouter_key}",
                "HTTP-Referer": "https://autoapplyai.com",
                "X-Title": "AutoApply AI",
                "Content-Type": "application/json"
            }
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload: Dict[str, Any] = {
                "model": or_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2048
            }
            if response_model:
                # Instruct JSON output for models that support it
                payload["response_format"] = {"type": "json_object"}

            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json().get("choices", [{}])[0].get("message", {}).get("content", "")

    def reset_availability_cache(self):
        """Force re-probe of Ollama on next call. Useful for testing."""
        global _ollama_available
        _ollama_available = None


# Global router instance
llm_router = LLMRouter()
