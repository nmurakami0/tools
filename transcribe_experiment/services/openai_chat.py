import base64

import httpx

from ._audio_utils import convert_to_mp3_bytes
from .base import BaseSTTService


class OpenAIChatService(BaseSTTService):
    needs_splitting = True

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        model = settings.get("model") or self.config.get("model", "gpt-audio")
        url = self.config.get(
            "base_url", "https://api.openai.com/v1/chat/completions"
        )

        prompt = settings.get("prompt") or ""

        mp3_bytes = convert_to_mp3_bytes(chunk_path)
        audio_b64 = base64.b64encode(mp3_bytes).decode("ascii")

        user_content: list[dict] = []
        if prompt:
            user_content.append({"type": "text", "text": prompt})
        user_content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": audio_b64, "format": "mp3"},
            }
        )

        messages: list[dict] = []
        if settings.get("system_instruction"):
            messages.append(
                {"role": "system", "content": settings["system_instruction"]}
            )
        messages.append({"role": "user", "content": user_content})

        body: dict = {
            "model": model,
            "modalities": ["text"],
            "messages": messages,
        }
        if "temperature" in settings:
            body["temperature"] = settings["temperature"]
        if "max_tokens" in settings:
            body["max_tokens"] = settings["max_tokens"]

        response = httpx.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=600.0,
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )
        return ""
