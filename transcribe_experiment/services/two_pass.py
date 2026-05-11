import json
import os
from itertools import groupby

from audio_splitter import concat_audio_files, split_audio_by_duration

from .base import BaseSTTService

LANGUAGE_ALIASES = {
    "japanese": "ja",
    "english": "en",
    "chinese": "zh",
    "korean": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "portuguese": "pt",
    "italian": "it",
    "russian": "ru",
    "dutch": "nl",
}


def normalize_language_code(lang: str | None) -> str | None:
    if lang is None:
        return None
    lang = lang.strip().lower()
    return LANGUAGE_ALIASES.get(lang, lang)


def inject_language_hint(settings: dict, language: str, service_name: str) -> dict:
    patched = dict(settings)
    if service_name == "elevenlabs":
        patched["language_code"] = language
    else:
        patched["language"] = language
    return patched


class TwoPassService(BaseSTTService):
    needs_splitting = False

    def __init__(self, config: dict, api_key: str, *, services_config: dict, auth: dict):
        super().__init__(config, api_key)
        self.services_config = services_config
        self.auth = auth
        self.output_dir: str | None = None
        self._pass1_service = None
        self._pass2_service = None
        self._last_detections: list[dict] = []

    def _get_service(self, service_name: str) -> BaseSTTService:
        from . import create_service
        return create_service(service_name, self.services_config, self.auth[service_name])

    @property
    def last_detections(self) -> list[dict]:
        return self._last_detections

    def _ensure_services(self, settings: dict):
        if self._pass1_service is None:
            pass1_cfg = settings["pass1"]
            self._pass1_service = self._get_service(pass1_cfg["service"])
            self._pass1_name = pass1_cfg["service"]
        if self._pass2_service is None:
            pass2_cfg = settings["pass2"]
            self._pass2_service = self._get_service(pass2_cfg["service"])
            self._pass2_name = pass2_cfg["service"]

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        self._ensure_services(settings)

        segment_seconds = settings.get("segment_seconds", 30)
        confidence_threshold = settings.get("confidence_threshold", 0.7)
        fallback_language = settings.get("fallback_language")
        pass1_settings = settings.get("pass1", {}).get("settings", {})
        pass2_settings = settings.get("pass2", {}).get("settings", {})

        base_dir = self.output_dir or os.path.dirname(chunk_path)
        segments_dir = os.path.join(base_dir, "two_pass_segments")

        print(f"    [two-pass] Splitting into {segment_seconds}s segments...")
        segment_paths = split_audio_by_duration(
            chunk_path, segment_seconds, output_dir=segments_dir
        )
        print(f"    [two-pass] Created {len(segment_paths)} segment(s)")

        # --- Pass 1: Language detection ---
        print(f"    [two-pass] Pass 1: detecting language per segment...")
        detections: list[dict] = []
        for i, seg_path in enumerate(segment_paths):
            result = self._pass1_service.transcribe_chunk_detailed(seg_path, pass1_settings)
            lang = normalize_language_code(result.get("language"))
            prob = result.get("language_probability")

            if prob is not None and prob < confidence_threshold and fallback_language:
                lang = fallback_language

            if lang is None and fallback_language:
                lang = fallback_language

            detections.append({
                "segment_index": i,
                "segment_path": seg_path,
                "detected_language": lang,
                "language_probability": prob,
                "pass1_text": result.get("text", ""),
            })
            print(f"      segment {i}: {lang} (prob={prob})")

        lang_json_dir = os.path.join(segments_dir, "lang_cache")
        os.makedirs(lang_json_dir, exist_ok=True)
        self._last_detections = detections

        for det in detections:
            cache_path = os.path.join(lang_json_dir, f"segment_{det['segment_index']:03d}.lang.json")
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(det, f, ensure_ascii=False, indent=2)

        # --- Merge consecutive same-language segments ---
        print(f"    [two-pass] Merging consecutive same-language segments...")
        groups: list[dict] = []
        for lang, group_iter in groupby(detections, key=lambda d: d["detected_language"]):
            members = list(group_iter)
            group_paths = [m["segment_path"] for m in members]

            if len(group_paths) == 1:
                merged_path = group_paths[0]
            else:
                merged_dir = os.path.join(segments_dir, "merged")
                os.makedirs(merged_dir, exist_ok=True)
                ext = os.path.splitext(group_paths[0])[1]
                merged_path = os.path.join(merged_dir, f"group_{len(groups):03d}{ext}")
                concat_audio_files(group_paths, merged_path)

            groups.append({
                "group_index": len(groups),
                "language": lang,
                "segment_indices": [m["segment_index"] for m in members],
                "merged_path": merged_path,
            })

        print(f"    [two-pass] {len(groups)} group(s) after merging")
        for g in groups:
            print(f"      group {g['group_index']}: {g['language']} (segments {g['segment_indices']})")

        # --- Pass 2: Transcribe with language hints ---
        print(f"    [two-pass] Pass 2: transcribing with language hints...")
        max_bytes = 24 * 1024 * 1024 if self._pass2_service.needs_splitting else None
        transcripts: list[str] = []
        for g in groups:
            lang = g["language"]
            if lang:
                patched_settings = inject_language_hint(pass2_settings, lang, self._pass2_name)
            else:
                patched_settings = dict(pass2_settings)

            merged = g["merged_path"]
            if max_bytes and os.path.getsize(merged) > max_bytes:
                sub_chunks = split_audio_by_duration(
                    merged, segment_seconds,
                    output_dir=os.path.join(segments_dir, f"group_{g['group_index']:03d}_splits"),
                )
                parts = []
                for sc in sub_chunks:
                    parts.append(self._pass2_service.transcribe_chunk(sc, patched_settings))
                text = "\n".join(parts)
            else:
                text = self._pass2_service.transcribe_chunk(merged, patched_settings)

            transcripts.append(text)
            print(f"      group {g['group_index']} ({lang}): {len(text)} chars")

        return "\n".join(transcripts)
