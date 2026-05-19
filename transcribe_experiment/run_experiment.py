import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from audio_splitter import split_audio_ffmpeg
from comparison import generate_comparison
from services import RunResult, ChunkResult, create_service


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_auth(services_config: dict, needed_services: set[str]) -> dict[str, str]:
    auth: dict[str, str] = {}

    if "faster_whisper" in needed_services:
        key = os.environ.get("FASTER_WHISPER_API_KEY")
        if not key:
            try:
                result = subprocess.run(
                    [
                        "kubectl",
                        "-n",
                        "stt-api",
                        "get",
                        "secret",
                        "stt-api-key",
                        "-o",
                        "jsonpath={.data.api-key}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
                key = subprocess.run(
                    ["base64", "-d"],
                    input=result.stdout,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
        if not key:
            raise ValueError(
                "faster_whisper API key not found. "
                "Set FASTER_WHISPER_API_KEY or ensure kubectl access."
            )
        auth["faster_whisper"] = key

    if "openai_transcribe" in needed_services:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY environment variable is required.")
        auth["openai_transcribe"] = key

    if "openai_chat" in needed_services:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY environment variable is required.")
        auth["openai_chat"] = key

    if "elevenlabs" in needed_services:
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("ELEVENLABS_API_KEY environment variable is required.")
        auth["elevenlabs"] = key

    if "gemini" in needed_services:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) environment variable is required."
            )
        auth["gemini"] = key

    return auth


def filter_runs(
    runs: list[dict],
    run_ids: list[str] | None,
    service_filters: list[str] | None,
) -> list[dict]:
    filtered = runs
    if run_ids:
        filtered = [r for r in filtered if r["id"] in run_ids]
    if service_filters:
        filtered = [r for r in filtered if r["service"] in service_filters]
    return filtered


def execute_run(
    service,
    run_cfg: dict,
    chunk_paths: list[str],
    original_file: str,
) -> RunResult:
    paths = chunk_paths if service.needs_splitting else [original_file]

    chunk_results: list[ChunkResult] = []
    total_start = time.monotonic()

    for i, path in enumerate(paths):
        print(f"  [{run_cfg['id']}] chunk {i + 1}/{len(paths)}: {os.path.basename(path)}")
        chunk_start = time.monotonic()
        try:
            text = service.transcribe_chunk(path, run_cfg.get("settings", {}))
            error = None
        except Exception as e:
            text = ""
            error = str(e)
            print(f"  [{run_cfg['id']}] ERROR on chunk {i}: {error}")

        elapsed = time.monotonic() - chunk_start
        chunk_result = ChunkResult(
            chunk_index=i,
            chunk_path=path,
            text=text,
            elapsed_seconds=round(elapsed, 2),
            error=error,
        )

        if hasattr(service, "last_detections") and service.last_detections:
            from collections import Counter
            langs = Counter(d["detected_language"] for d in service.last_detections)
            chunk_result.detected_language = "/".join(
                f"{lang}({n})" for lang, n in langs.most_common()
            )

        chunk_results.append(chunk_result)

    total_elapsed = time.monotonic() - total_start

    verbose_chunks = getattr(service, "last_verbose_chunks", None) or None

    return RunResult(
        run_id=run_cfg["id"],
        service=run_cfg["service"],
        settings=run_cfg.get("settings", {}),
        chunks=chunk_results,
        total_elapsed_seconds=round(total_elapsed, 2),
        verbose_chunks=verbose_chunks,
    )


def _merge_verbose_chunks(payloads: list[dict]) -> dict:
    from collections import Counter

    merged_segments: list[dict] = []
    cumulative_offset = 0.0
    total_duration = 0.0
    texts: list[str] = []
    languages: list[str] = []
    next_id = 0
    for payload in payloads:
        duration = float(payload.get("duration") or 0.0)
        for seg in payload.get("segments") or []:
            merged_segments.append(
                {
                    "id": next_id,
                    "start": float(seg.get("start") or 0.0) + cumulative_offset,
                    "end": float(seg.get("end") or 0.0) + cumulative_offset,
                    "text": seg.get("text", ""),
                }
            )
            next_id += 1
        cumulative_offset += duration
        total_duration += duration
        if payload.get("text"):
            texts.append(payload["text"])
        if payload.get("language"):
            languages.append(payload["language"])

    language = ""
    if languages:
        language = Counter(languages).most_common(1)[0][0]

    return {
        "task": "transcribe",
        "language": language,
        "duration": total_duration,
        "text": "\n".join(texts),
        "segments": merged_segments,
    }


def save_result(result: RunResult, output_dir: str, audio_file: str):
    run_dir = os.path.join(output_dir, result.run_id)
    os.makedirs(run_dir, exist_ok=True)

    with open(os.path.join(run_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write(result.full_text)

    if result.verbose_chunks:
        merged = _merge_verbose_chunks(result.verbose_chunks)
        with open(os.path.join(run_dir, "transcript.json"), "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)

    chunks_dir = os.path.join(run_dir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)
    for chunk in result.chunks:
        chunk_file = os.path.join(chunks_dir, f"chunk_{chunk.chunk_index:03d}.txt")
        with open(chunk_file, "w", encoding="utf-8") as f:
            f.write(chunk.text)

    meta = {
        "run_id": result.run_id,
        "service": result.service,
        "settings": result.settings,
        "audio_file": audio_file,
        "total_elapsed_seconds": result.total_elapsed_seconds,
        "total_char_count": result.char_count,
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "chunk_path": c.chunk_path,
                "elapsed_seconds": c.elapsed_seconds,
                "char_count": len(c.text),
                "error": c.error,
                "detected_language": c.detected_language,
                "language_probability": c.language_probability,
            }
            for c in result.chunks
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"  [{result.run_id}] saved to {run_dir}/")


def main():
    parser = argparse.ArgumentParser(
        description="Run STT comparison experiments across multiple services"
    )
    parser.add_argument(
        "config", nargs="?", default="config.yaml", help="Path to config YAML"
    )
    parser.add_argument(
        "--run-ids",
        help="Comma-separated list of run IDs to execute",
    )
    parser.add_argument(
        "--service",
        help="Comma-separated list of services to run (e.g. faster_whisper,elevenlabs)",
    )
    parser.add_argument(
        "--skip-split",
        action="store_true",
        help="Reuse existing audio chunks from a prior run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run without executing",
    )
    args = parser.parse_args()

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)

    config = load_config(config_path)
    audio_file = config["audio_file"]
    split_cfg = config.get("split", {})
    output_dir = config.get("output_dir", "./output")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(config_path), output_dir)

    run_ids = args.run_ids.split(",") if args.run_ids else None
    service_filters = args.service.split(",") if args.service else None
    runs = filter_runs(config["runs"], run_ids, service_filters)

    if not runs:
        print("No runs matched the filter criteria.")
        return

    if args.dry_run:
        print("=== DRY RUN ===")
        for run in runs:
            print(f"  {run['id']} ({run['service']}): {run.get('settings', {})}")
        print(f"\nTotal: {len(runs)} run(s)")
        return

    if not os.path.exists(audio_file):
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    splitting_services = {"openai_transcribe", "openai_chat"}
    needs_splitting = any(run["service"] in splitting_services for run in runs)
    chunks_dir = os.path.join(output_dir, "chunks")

    if needs_splitting and not args.skip_split:
        print(f"Splitting audio for OpenAI (chunk_size={split_cfg.get('chunk_size_mb', 20)}MB)...")
        chunk_paths = split_audio_ffmpeg(
            audio_file,
            chunk_size_mb=split_cfg.get("chunk_size_mb", 20),
            output_dir=chunks_dir,
        )
        print(f"  Created {len(chunk_paths)} chunk(s)")
    elif needs_splitting and args.skip_split:
        chunk_paths = sorted(
            str(p) for p in Path(chunks_dir).glob("chunk_*")
        )
        if not chunk_paths:
            raise FileNotFoundError(
                f"No existing chunks found in {chunks_dir}. Run without --skip-split first."
            )
        print(f"  Reusing {len(chunk_paths)} existing chunk(s)")
    else:
        chunk_paths = []

    needed_services = {r["service"] for r in runs}
    auth = resolve_auth(config.get("services", {}), needed_services)
    services_config = config.get("services", {})

    results: list[RunResult] = []
    print(f"\nRunning {len(runs)} experiment(s)...\n")

    for run_cfg in runs:
        print(f"--- {run_cfg['id']} ({run_cfg['service']}) ---")
        service = create_service(
            run_cfg["service"], services_config,
            auth.get(run_cfg["service"], ""),
        )
        if hasattr(service, "output_dir"):
            service.output_dir = os.path.join(output_dir, run_cfg["id"])
        result = execute_run(service, run_cfg, chunk_paths, audio_file)
        save_result(result, output_dir, audio_file)
        results.append(result)
        print(
            f"  Done: {result.total_elapsed_seconds}s, "
            f"{result.char_count} chars\n"
        )

    if results:
        generate_comparison(results, output_dir)
        print(f"\nAll done. Results in {output_dir}/")


if __name__ == "__main__":
    main()
