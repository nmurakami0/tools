import base64

import httpx

from ._audio_utils import convert_to_mp3_bytes
from .base import BaseSTTService


class GeminiService(BaseSTTService):
    needs_splitting = False

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        model = settings.get("model") or self.config.get(
            "model", "gemini-3.1-flash-preview"
        )
        base_url = self.config.get(
            "base_url", "https://generativelanguage.googleapis.com/v1beta/models"
        )
        url = f"{base_url}/{model}:generateContent"

        prompt = settings.get("prompt") or ""

        mp3_bytes = convert_to_mp3_bytes(chunk_path)
        audio_b64 = base64.b64encode(mp3_bytes).decode("ascii")

        parts: list[dict] = []
        if prompt:
            parts.append({"text": prompt})
        parts.append(
            {
                "inlineData": {
                    "mimeType": "audio/mp3",
                    "data": audio_b64,
                }
            }
        )

        body: dict = {"contents": [{"parts": parts}]}

        generation_config: dict = {}
        if "temperature" in settings:
            generation_config["temperature"] = settings["temperature"]
        if "max_output_tokens" in settings:
            generation_config["maxOutputTokens"] = settings["max_output_tokens"]
        if "thinking_level" in settings:
            generation_config["thinkingConfig"] = {
                "thinkingLevel": settings["thinking_level"]
            }
        if generation_config:
            body["generationConfig"] = generation_config

        if settings.get("system_instruction"):
            body["systemInstruction"] = {
                "parts": [{"text": settings["system_instruction"]}]
            }

        response = httpx.post(
            url,
            json=body,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=600.0,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts_out = candidates[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts_out)
