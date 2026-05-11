import csv
import os
from collections import Counter

from services.base import RunResult


def _detect_language_summary(r: RunResult) -> str:
    detected = [c.detected_language for c in r.chunks if c.detected_language]
    if not detected:
        return r.settings.get("language", r.settings.get("language_code", "auto"))
    counts = Counter(detected)
    parts = [f"{lang}({n})" for lang, n in counts.most_common()]
    return "/".join(parts)


def generate_comparison(results: list[RunResult], output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    _write_summary_tsv(results, output_dir)
    _write_comparison_md(results, output_dir)
    print(f"  Generated summary.tsv and comparison.md in {output_dir}/")


def _write_summary_tsv(results: list[RunResult], output_dir: str):
    path = os.path.join(output_dir, "summary.tsv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(
            [
                "run_id",
                "service",
                "language",
                "prompt_hint",
                "total_seconds",
                "char_count",
                "first_200_chars",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.run_id,
                    r.service,
                    _detect_language_summary(r),
                    _truncate(r.settings.get("prompt", "(none)"), 40),
                    r.total_elapsed_seconds,
                    r.char_count,
                    _truncate(r.full_text, 200),
                ]
            )


def _write_comparison_md(results: list[RunResult], output_dir: str):
    lines: list[str] = []
    lines.append("# STT Comparison Results\n")

    lines.append("## Overview\n")
    lines.append(
        "| Run ID | Service | Language | Time (s) | Chars | Prompt |"
    )
    lines.append("|--------|---------|----------|----------|-------|--------|")
    for r in results:
        lang = _detect_language_summary(r)
        prompt = _truncate(r.settings.get("prompt", "-"), 30)
        lines.append(
            f"| {r.run_id} | {r.service} | {lang} "
            f"| {r.total_elapsed_seconds} | {r.char_count} | {prompt} |"
        )
    lines.append("")

    lines.append("## Transcription Previews (first 500 chars)\n")
    for r in results:
        lines.append(f"### {r.run_id}\n")
        lines.append("```")
        lines.append(_truncate(r.full_text, 500))
        lines.append("```\n")

    chunked = [r for r in results if len(r.chunks) > 1]
    if chunked:
        lines.append("## Per-Chunk Comparison\n")
        max_chunks = max(len(r.chunks) for r in chunked)
        for ci in range(max_chunks):
            lines.append(f"### Chunk {ci}\n")
            for r in chunked:
                if ci < len(r.chunks):
                    chunk = r.chunks[ci]
                    lines.append(f"**{r.run_id}** ({chunk.elapsed_seconds}s):")
                    lines.append("```")
                    lines.append(_truncate(chunk.text, 300))
                    lines.append("```\n")

    lines.append("## Full Text Comparison\n")
    lines.append(
        "See each `<run_id>/transcript.txt` for complete transcriptions."
    )

    path = os.path.join(output_dir, "comparison.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."
