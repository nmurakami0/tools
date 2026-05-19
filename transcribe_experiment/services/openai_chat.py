import base64
import json
import re
import sys

import httpx

from ._audio_utils import convert_to_mp3_bytes
from .base import BaseSTTService


VERBOSE_SCHEMA_DESCRIPTION = """\
{
  "task": "transcribe",
  "language": "<ISO-639-1 code, e.g. ja or en>",
  "duration": <total clip length in seconds, number>,
  "text": "<full transcription, no extra formatting>",
  "segments": [
    {
      "id": <0-based integer>,
      "start": <seconds from clip start, number>,
      "end": <seconds from clip start, number>,
      "text": "<segment transcription>"
    }
  ]
}"""

VERBOSE_SYSTEM_INSTRUCTION = (
    "Transcribe the audio. Respond with ONLY a single JSON object — no prose, no code fences, "
    "no leading or trailing text — matching exactly this shape:\n\n"
    f"{VERBOSE_SCHEMA_DESCRIPTION}\n\n"
    'Use ISO-639-1 codes for "language" (e.g. "ja", "en"). '
    'Express "duration" and segment "start"/"end" as seconds (floats) relative to the start of this audio clip. '
    "Produce one segment per natural utterance or sentence."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verbose_payload(raw_text: str) -> dict:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(stripped)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {
        "task": "transcribe",
        "language": "",
        "duration": 0.0,
        "text": raw_text,
        "segments": [],
    }


class OpenAIChatService(BaseSTTService):
    needs_splitting = True

    def __init__(self, config: dict, api_key: str):
        super().__init__(config, api_key)
        self.last_verbose_chunks: list[dict] = []

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        model = settings.get("model") or self.config.get("model", "gpt-audio")
        url = self.config.get(
            "base_url", "https://api.openai.com/v1/chat/completions"
        )
        verbose = settings.get("response_format") == "verbose_json"

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
        if verbose:
            messages.append({"role": "system", "content": VERBOSE_SYSTEM_INSTRUCTION})
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
        if "frequency_penalty" in settings:
            body["frequency_penalty"] = settings["frequency_penalty"]
        if "presence_penalty" in settings:
            body["presence_penalty"] = settings["presence_penalty"]

        response = httpx.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=600.0,
        )
        if response.status_code >= 400:
            print(
                f"  OpenAI API {response.status_code}: {response.text[:1000]}",
                file=sys.stderr,
            )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content")
        if isinstance(content, str):
            raw_text = content
        elif isinstance(content, list):
            raw_text = "".join(
                part.get("text", "") for part in content if part.get("type") == "text"
            )
        else:
            raw_text = ""

        if not verbose:
            return raw_text

        payload = _parse_verbose_payload(raw_text)
        self.last_verbose_chunks.append(payload)
        return payload.get("text") or raw_text
