"""
Pinterest Realism Engine — LLM Provider Layer.

Configured with OpenCode AI as the primary provider:
  • Text / Structured Output ──► OpenCode AI (DeepSeek v4 Flash)
  • Multimodal Vision Analysis ─► OpenCode AI (MiMo V2.5)

Also includes automatic fallback routing to Gemini / OpenRouter if configured.
All providers include timeout, retry with exponential backoff, and robust JSON parsing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("pre.llm")

MAX_RETRIES = 3
BASE_TIMEOUT = 120.0  # seconds — vision calls can take longer on high-res images


# ─────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────
# These exist so that a provider failure is never silently replaced by
# invented data. Every caller must either handle them or let them surface.
class LLMError(RuntimeError):
    """Base class for LLM layer failures."""


class LLMUnavailableError(LLMError):
    """Every configured provider failed (auth, network, quota, timeout)."""


class LLMParseError(LLMError):
    """A provider replied, but the reply was not usable JSON."""

    def __init__(self, raw: str) -> None:
        preview = raw.strip().replace("\n", " ")[:300]
        super().__init__(f"LLM did not return valid JSON. First 300 chars: {preview!r}")
        self.raw = raw


# ─────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────
class LLMProvider(ABC):
    """Base interface for LLM providers."""

    @abstractmethod
    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        """Plain text generation."""
        ...

    @abstractmethod
    async def structured_output(
        self, prompt: str, system: str | None = None
    ) -> dict[str, Any]:
        """Generate and parse JSON output."""
        ...

    @abstractmethod
    async def analyze_image(
        self, prompt: str, image_path: str, system: str | None = None
    ) -> dict[str, Any]:
        """Vision analysis — send image + prompt, get structured JSON back."""
        ...


# ─────────────────────────────────────────────────
# OpenCode AI Provider (Text + Vision)
# ─────────────────────────────────────────────────
class OpenCodeProvider(LLMProvider):
    """
    OpenAI-compatible client for OpenCode AI (https://opencode.ai/).
    Supports both text (DeepSeek v4 Flash) and vision (MiMo V2.5).
    """

    def __init__(self, text_model: str | None = None, vision_model: str | None = None) -> None:
        self.api_key = settings.opencode_api_key
        self.base_url = settings.opencode_base_url.rstrip("/")
        self.text_model = text_model or settings.opencode_text_model
        self.vision_model = vision_model or settings.opencode_vision_model
        self._client = httpx.AsyncClient(timeout=BASE_TIMEOUT)

    async def _chat_completion(
        self,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
    ) -> str:
        """Fire an OpenAI-compatible chat completion request with exponential backoff retries."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
        }
        if response_format:
            body["response_format"] = response_format

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectError, KeyError) as exc:
                if attempt == MAX_RETRIES:
                    logger.error("OpenCode AI call [%s] failed after %d retries: %s", model, MAX_RETRIES, exc)
                    raise
                wait = 2 ** attempt
                logger.warning("OpenCode AI attempt %d failed (%s), retrying in %ds…", attempt, exc, wait)
                await asyncio.sleep(wait)
        return ""

    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat_completion(self.text_model, messages)

    async def structured_output(
        self, prompt: str, system: str | None = None
    ) -> dict[str, Any]:
        messages: list[dict] = []
        system_instruction = (system or "") + "\nYou MUST reply with a valid JSON object only. Do NOT include any markdown formatting, preamble, or conversational commentary."
        messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        raw = await self._chat_completion(
            self.text_model,
            messages,
            response_format={"type": "json_object"},
        )
        return _parse_json(raw)

    async def analyze_image(
        self, prompt: str, image_path: str, system: str | None = None
    ) -> dict[str, Any]:
        """
        Multimodal image analysis via OpenCode AI (MiMo V2.5).
        Encodes image as Base64 data URL in standard OpenAI vision format.
        """
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        img_bytes = img_path.read_bytes()
        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        suffix = img_path.suffix.lower()
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        mime = mime_map.get(suffix, "image/jpeg")
        data_url = f"data:{mime};base64,{img_b64}"

        messages: list[dict] = []
        system_instruction = (system or "") + "\nYou MUST return a valid JSON object only."
        messages.append({"role": "system", "content": system_instruction})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                }
            ]
        })

        raw = await self._chat_completion(
            self.vision_model,
            messages,
            response_format={"type": "json_object"},
        )
        return _parse_json(raw)


# ─────────────────────────────────────────────────
# OpenRouter Provider (Fallback)
# ─────────────────────────────────────────────────
class OpenRouterProvider(LLMProvider):
    """Calls OpenRouter's OpenAI-compatible chat/completions endpoint."""

    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.model = settings.openrouter_model
        self._client = httpx.AsyncClient(timeout=BASE_TIMEOUT)

    async def _chat(self, messages: list[dict], response_format: dict | None = None, max_tokens: int = 1024) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                if attempt == MAX_RETRIES:
                    raise
                await asyncio.sleep(2 ** attempt)
        return ""

    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def structured_output(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        is_nvidia = "nvidia" in self.base_url.lower()
        raw = await self._chat(messages, response_format=None if is_nvidia else {"type": "json_object"})
        return _parse_json(raw)

    async def analyze_image(self, prompt: str, image_path: str, system: str | None = None) -> dict[str, Any]:
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        try:
            import io
            from PIL import Image
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
            mime = "image/jpeg"
        except Exception:
            img_bytes = img_path.read_bytes()
            img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            suffix = img_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime = mime_map.get(suffix, "image/jpeg")
        data_url = f"data:{mime};base64,{img_b64}"
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system + "\nYou MUST return a valid JSON object only."})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        })
        # NVIDIA vision model hangs on response_format json_object — send without it and rely on system prompt + _parse_json
        is_nvidia = "nvidia" in self.base_url.lower()
        raw = await self._chat(messages, response_format=None if is_nvidia else {"type": "json_object"})
        return _parse_json(raw)


# ─────────────────────────────────────────────────
# Gemini Provider (Fallback)
# ─────────────────────────────────────────────────
class GeminiProvider(LLMProvider):
    """Calls Google Gemini via AI Studio API."""

    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self._client = httpx.AsyncClient(timeout=BASE_TIMEOUT)

    def _url(self, action: str = "generateContent") -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{action}?key={self.api_key}"

    async def _generate(self, contents: list[dict], system: str | None = None) -> str:
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        body["generationConfig"] = {
            "temperature": 0.3,
            "responseMimeType": "application/json",
        }

        for attempt in range(1, 5):
            try:
                resp = await self._client.post(self._url(), json=body)
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 4:
                    wait = 2.5 * attempt
                    logger.warning("Gemini 429 rate limit hit; waiting %.1fs before retry %d/4...", wait, attempt)
                    await asyncio.sleep(wait)
                    continue
                if attempt == 4:
                    raise
                await asyncio.sleep(2 ** attempt)
            except Exception as exc:
                if attempt == 4:
                    raise
                await asyncio.sleep(2 ** attempt)
        return ""

    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        return await self._generate([{"role": "user", "parts": [{"text": prompt}]}], system)

    async def structured_output(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        raw = await self.generate_text(prompt, system)
        return _parse_json(raw)

    async def analyze_image(self, prompt: str, image_path: str, system: str | None = None) -> dict[str, Any]:
        img_path = Path(image_path)
        try:
            import io
            from PIL import Image
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
            mime = "image/jpeg"
        except Exception:
            img_bytes = img_path.read_bytes()
            img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            suffix = img_path.suffix.lower()
            mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime = mime_map.get(suffix, "image/jpeg")

        contents = [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": mime, "data": img_b64}},
                {"text": prompt},
            ],
        }]
        raw = await self._generate(contents, system)
        return _parse_json(raw)


# ─────────────────────────────────────────────────
# Unified Engine Provider Manager
# ─────────────────────────────────────────────────
class UnifiedLLMProvider:
    """
    Primary routing engine:
      • If OpenCode AI key is present: Uses OpenCode AI (DeepSeek v4 Flash for text, MiMo V2.5 for vision)
      • Otherwise: Uses OpenRouter for text and Gemini for vision.
    """

    def __init__(self) -> None:
        self._openrouter = OpenRouterProvider() if settings.openrouter_api_key else None
        self._gemini = GeminiProvider() if settings.gemini_api_key else None
        self._opencode = OpenCodeProvider() if settings.opencode_api_key else None

        if self._openrouter:
            logger.info("Using OpenRouter (NVIDIA NIM: %s) as primary provider", settings.openrouter_model)
        elif self._gemini:
            logger.info("Using Google Gemini as primary provider (Model: %s)", settings.gemini_model)
        elif self._opencode:
            logger.info("Using OpenCode AI as primary provider (Text: %s, Vision: %s)", settings.opencode_text_model, settings.opencode_vision_model)

    async def generate_text(self, prompt: str, system: str | None = None) -> str:
        errors: list[str] = []
        if self._openrouter:
            try:
                return await asyncio.wait_for(self._openrouter.generate_text(prompt, system), timeout=45)
            except asyncio.TimeoutError:
                errors.append("OpenRouter text: timeout 45s")
                logger.warning("OpenRouter text timed out (45s)")
            except Exception as e:
                errors.append(f"OpenRouter: {e}")
                logger.warning("OpenRouter text failed: %s. Trying fallback...", e)
        if self._gemini:
            try:
                return await asyncio.wait_for(self._gemini.generate_text(prompt, system), timeout=45)
            except asyncio.TimeoutError:
                errors.append("Gemini text: timeout 45s")
                logger.warning("Gemini text timed out (45s)")
            except Exception as e:
                errors.append(f"Gemini: {e}")
                logger.warning("Gemini text failed: %s. Trying fallback...", e)
        if self._opencode:
            try:
                return await asyncio.wait_for(self._opencode.generate_text(prompt, system), timeout=45)
            except asyncio.TimeoutError:
                errors.append("OpenCode text: timeout 45s")
                logger.warning("OpenCode text timed out")
            except Exception as e:
                errors.append(f"OpenCode: {e}")
                logger.warning("OpenCode text failed: %s", e)
        if any("429" in e or "quota" in e.lower() for e in errors):
            raise LLMUnavailableError(
                "API key quota / rate limit reached (429). Please replace the API key in .env (OPENROUTER_API_KEY / GEMINI_API_KEY) or wait ~60s. Details: " + "; ".join(errors)
            )
        raise LLMUnavailableError(
            "All text providers failed or none configured. " + "; ".join(errors or ["no provider configured"])
        )

    async def structured_output(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        if self._openrouter:
            try:
                return await asyncio.wait_for(self._openrouter.structured_output(prompt, system), timeout=75)
            except asyncio.TimeoutError:
                errors.append("OpenRouter structured: timeout 75s")
                logger.warning("OpenRouter structured timed out (75s)")
            except Exception as e:
                errors.append(f"OpenRouter: {e}")
                logger.warning("OpenRouter structured output failed: %s. Trying fallback...", e)
        if self._gemini:
            try:
                return await asyncio.wait_for(self._gemini.structured_output(prompt, system), timeout=75)
            except asyncio.TimeoutError:
                errors.append("Gemini structured: timeout 75s")
                logger.warning("Gemini structured timed out (75s)")
            except Exception as e:
                errors.append(f"Gemini: {e}")
                logger.warning("Gemini structured output failed: %s. Trying fallback...", e)
        if self._opencode:
            try:
                return await asyncio.wait_for(self._opencode.structured_output(prompt, system), timeout=75)
            except asyncio.TimeoutError:
                errors.append("OpenCode structured: timeout 75s")
                logger.warning("OpenCode structured timed out (75s)")
            except Exception as e:
                errors.append(f"OpenCode: {e}")
                logger.warning("OpenCode structured output failed: %s", e)
        if any("429" in e or "quota" in e.lower() for e in errors):
            raise LLMUnavailableError(
                "API key quota / rate limit reached (429). Please replace the API key in .env (OPENROUTER_API_KEY / GEMINI_API_KEY) or wait ~60s. Details: " + "; ".join(errors)
            )
        raise LLMUnavailableError(
            "All structured-output providers failed or none configured. "
            + "; ".join(errors or ["no provider configured"])
        )

    async def analyze_image(self, prompt: str, image_path: str, system: str | None = None) -> dict[str, Any]:
        errors: list[str] = []
        if self._openrouter:
            try:
                return await asyncio.wait_for(self._openrouter.analyze_image(prompt, image_path, system), timeout=25)
            except asyncio.TimeoutError as e:
                errors.append(f"OpenRouter vision: timeout 25s")
                logger.warning("OpenRouter vision timed out (25s): %s", e)
            except Exception as e:
                errors.append(f"OpenRouter vision: {e}")
                logger.warning("OpenRouter Vision provider failed: %s. Trying fallback...", e)
        if self._gemini:
            try:
                return await asyncio.wait_for(self._gemini.analyze_image(prompt, image_path, system), timeout=30)
            except asyncio.TimeoutError as e:
                errors.append(f"Gemini vision: timeout 30s")
                logger.warning("Gemini vision timed out (30s): %s", e)
            except Exception as e:
                errors.append(f"Gemini vision: {e}")
                logger.warning("Gemini Vision provider failed: %s. Trying fallback...", e)
        if self._opencode:
            try:
                return await asyncio.wait_for(self._opencode.analyze_image(prompt, image_path, system), timeout=30)
            except asyncio.TimeoutError as e:
                errors.append(f"OpenCode vision: timeout 30s")
                logger.warning("OpenCode vision timed out: %s", e)
            except Exception as e:
                errors.append(f"OpenCode vision: {e}")
                logger.warning("OpenCode vision fallback failed: %s", e)
        if any("429" in e or "quota" in e.lower() or "rate limit" in e.lower() for e in errors):
            raise LLMUnavailableError(
                "API key quota / rate limit reached (429). Please replace the API key in .env (OPENROUTER_API_KEY / GEMINI_API_KEY) or wait ~60s. Details: " + "; ".join(errors)
            )
        raise LLMUnavailableError(
            "All vision providers failed or none configured. " + "; ".join(errors or ["no vision provider configured"])
        )


# ─────────────────────────────────────────────────
# Singleton instance
# ─────────────────────────────────────────────────
llm = UnifiedLLMProvider()


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────
def _parse_json(raw: str) -> dict[str, Any]:
    """
    Robustly parse JSON from LLM output, handling markdown fences and commentary.

    Raises LLMParseError if the text cannot be parsed. It must NOT return a
    placeholder dict — a caller that receives a dict has to be able to trust it.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try finding JSON bracket bounds if extra commentary surrounds it
    if not (text.startswith("{") and text.endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON output: %s", exc)
        raise LLMParseError(raw) from exc

    if not isinstance(parsed, dict):
        raise LLMParseError(raw)
    return parsed
