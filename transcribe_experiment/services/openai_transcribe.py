import os

import httpx

from .base import BaseSTTService


class OpenAITranscribeService(BaseSTTService):
    needs_splitting = True

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        url = "https://api.openai.com/v1/audio/transcriptions"
        model = self.config.get("model", "gpt-4o-transcribe")

        data: dict[str, str] = {"model": model}
        if settings.get("language"):
            data["language"] = settings["language"]
        if settings.get("prompt"):
            data["prompt"] = settings["prompt"]

        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=300.0,
            )
        response.raise_for_status()
        return response.json()["text"]
