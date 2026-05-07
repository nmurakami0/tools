import os

import httpx

from .base import BaseSTTService


class ElevenLabsService(BaseSTTService):
    needs_splitting = False

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        url = self.config.get(
            "base_url", "https://api.elevenlabs.io/v1/speech-to-text"
        )

        data: dict[str, str] = {
            "model_id": settings.get("model_id", "scribe_v1"),
        }
        if settings.get("language_code"):
            data["language_code"] = settings["language_code"]

        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"xi-api-key": self.api_key},
                timeout=600.0,
            )
        response.raise_for_status()
        return response.json()["text"]

    def transcribe_chunk_detailed(self, chunk_path: str, settings: dict) -> dict:
        url = self.config.get(
            "base_url", "https://api.elevenlabs.io/v1/speech-to-text"
        )

        data: dict[str, str] = {
            "model_id": settings.get("model_id", "scribe_v1"),
        }
        if settings.get("language_code"):
            data["language_code"] = settings["language_code"]

        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"xi-api-key": self.api_key},
                timeout=600.0,
            )
        response.raise_for_status()
        body = response.json()
        return {
            "text": body.get("text", ""),
            "language": body.get("language_code"),
            "language_probability": body.get("language_probability"),
        }
