# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A YAML-driven experiment runner that compares transcription accuracy across multiple STT services for the same audio file. Each "run" in `config.yaml` defines a service + settings combination; results are saved per-run and aggregated into a comparison report.

## Commands

```bash
# Dry run — shows which experiments would execute
python run_experiment.py --dry-run

# Run all experiments
python run_experiment.py

# Filter by service (comma-separated)
python run_experiment.py --service faster_whisper,elevenlabs

# Filter by run ID (comma-separated)
python run_experiment.py --run-ids fw-ja-prompted,gpt4o-auto

# Reuse audio chunks from a prior run (skips ffmpeg splitting)
python run_experiment.py --skip-split
```

## Architecture

`run_experiment.py` is the CLI entry point. It loads `config.yaml`, resolves API keys, optionally splits the audio, then runs each experiment sequentially.

**Service abstraction:** Each STT provider lives in `services/` and extends `BaseSTTService`. The key contract is `transcribe_chunk(chunk_path, settings) -> str`. A service's `needs_splitting` flag controls whether it receives split chunks or the full file.

**Audio splitting:** `audio_splitter.py` uses `ffmpeg -c copy` (stream copy, no re-encode). Only services with `needs_splitting = True` (currently just OpenAI due to its 25MB limit) receive chunks; others get the original file.

**Comparison output:** `comparison.py` generates `summary.tsv` (machine-readable) and `comparison.md` (human-readable) from all run results.

**Auth resolution:** API keys come from env vars (`FASTER_WHISPER_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`). faster-whisper falls back to `kubectl` secret lookup. Auth is only resolved for services actually used in the selected runs.

## Adding a New Experiment Run

Add an entry to the `runs` list in `config.yaml`. No code changes needed. The `settings` dict is passed through to the service's `transcribe_chunk` as-is.

## Adding a New STT Service

1. Create `services/<name>.py` implementing `BaseSTTService.transcribe_chunk`
2. Register it in `services/__init__.py` `SERVICE_REGISTRY`
3. Add auth resolution in `run_experiment.py:resolve_auth`

## Dependencies

All already installed — no pip install needed: `httpx`, `pyyaml`, system `ffmpeg`.
