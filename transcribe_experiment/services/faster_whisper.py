import os

import httpx

from .base import BaseSTTService


class FasterWhisperService(BaseSTTService):
    needs_splitting = False

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        url = self.config["base_url"]
        model = self.config["model"]

        data: dict[str, str] = {"model": model}
        if settings.get("language"):
            data["language"] = settings["language"]
        if settings.get("prompt"):
            data["prompt"] = settings["prompt"]
        if settings.get("temperature") is not None:
            data["temperature"] = str(settings["temperature"])
        if "condition_on_previous_text" in settings:
            data["condition_on_previous_text"] = str(settings["condition_on_previous_text"]).lower()

        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=600.0,
            )
        response.raise_for_status()
        return response.json()["text"]

    def transcribe_chunk_detailed(self, chunk_path: str, settings: dict) -> dict:
        url = self.config["base_url"]
        model = self.config["model"]

        data: dict[str, str] = {"model": model, "response_format": "verbose_json"}
        if settings.get("language"):
            data["language"] = settings["language"]
        if settings.get("prompt"):
            data["prompt"] = settings["prompt"]
        if settings.get("temperature") is not None:
            data["temperature"] = str(settings["temperature"])
        if "condition_on_previous_text" in settings:
            data["condition_on_previous_text"] = str(settings["condition_on_previous_text"]).lower()

        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=600.0,
            )
        response.raise_for_status()
        body = response.json()
        return {
            "text": body.get("text", ""),
            "language": body.get("language"),
            "language_probability": None,
        }
