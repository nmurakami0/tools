import json
import os

import httpx

from .base import BaseSTTService


class ElevenLabsService(BaseSTTService):
    needs_splitting = False

    def _build_form_data(self, settings: dict) -> dict[str, str]:
        data: dict[str, str] = {
            "model_id": settings.get("model_id", "scribe_v1"),
        }
        if settings.get("language_code"):
            data["language_code"] = settings["language_code"]
        if settings.get("no_verbatim") is not None:
            data["no_verbatim"] = str(settings["no_verbatim"]).lower()
        if settings.get("keyterms"):
            data["keyterms"] = json.dumps(settings["keyterms"])
        if settings.get("diarize") is not None:
            data["diarize"] = str(settings["diarize"]).lower()
        if settings.get("num_speakers") is not None:
            data["num_speakers"] = str(settings["num_speakers"])
        return data

    def _post(self, chunk_path: str, settings: dict) -> dict:
        url = self.config.get(
            "base_url", "https://api.elevenlabs.io/v1/speech-to-text"
        )
        data = self._build_form_data(settings)
        with open(chunk_path, "rb") as f:
            response = httpx.post(
                url,
                data=data,
                files={"file": (os.path.basename(chunk_path), f, "audio/mp4")},
                headers={"xi-api-key": self.api_key},
                timeout=600.0,
            )
        response.raise_for_status()
        return response.json()

    def _render_text(self, body: dict, settings: dict) -> str:
        if settings.get("diarize"):
            formatted = _format_diarized(body)
            if formatted:
                return formatted
        return body.get("text", "")

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        body = self._post(chunk_path, settings)
        return self._render_text(body, settings)

    def transcribe_chunk_detailed(self, chunk_path: str, settings: dict) -> dict:
        body = self._post(chunk_path, settings)
        return {
            "text": self._render_text(body, settings),
            "language": body.get("language_code"),
            "language_probability": body.get("language_probability"),
        }


def _format_diarized(body: dict) -> str:
    words = body.get("words") or []
    if not words:
        return ""

    lines: list[str] = []
    cur_speaker: str | None = None
    cur_start: float | None = None
    cur_buf: list[str] = []

    def flush() -> None:
        if not cur_buf:
            return
        text = "".join(cur_buf).strip()
        if not text:
            return
        lines.append(f"[{_fmt_ts(cur_start or 0.0)}] {_speaker_label(cur_speaker)}: {text}")

    for w in words:
        speaker = w.get("speaker_id")
        if speaker != cur_speaker:
            flush()
            cur_speaker = speaker
            cur_start = w.get("start", 0.0)
            cur_buf = []
        cur_buf.append(w.get("text", ""))
    flush()

    return "\n".join(lines)


def _fmt_ts(seconds: float) -> str:
    total = int(seconds or 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _speaker_label(sid: str | None) -> str:
    if not sid:
        return "Speaker ?"
    if sid.startswith("speaker_"):
        return f"Speaker {sid.split('_', 1)[1]}"
    return sid
