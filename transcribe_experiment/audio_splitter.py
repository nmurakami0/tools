import glob
import json
import math
import os
import subprocess
import tempfile


def get_audio_duration(file_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def split_audio_ffmpeg(
    file_path: str,
    chunk_size_mb: int = 20,
    output_dir: str | None = None,
) -> list[str]:
    chunk_size_bytes = chunk_size_mb * 1024 * 1024
    file_size = os.path.getsize(file_path)

    if file_size <= chunk_size_bytes:
        return [file_path]

    duration = get_audio_duration(file_path)
    num_chunks = math.ceil(file_size / chunk_size_bytes)
    chunk_duration = duration / num_chunks

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(file_path), "audio_chunks")
    os.makedirs(output_dir, exist_ok=True)

    ext = os.path.splitext(file_path)[1]
    chunk_paths = []

    for i in range(num_chunks):
        start = i * chunk_duration
        chunk_path = os.path.join(output_dir, f"chunk_{i:03d}{ext}")
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(chunk_duration),
            "-i",
            file_path,
            "-c",
            "copy",
            chunk_path,
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        chunk_paths.append(chunk_path)
        print(f"  Split chunk {i + 1}/{num_chunks}: {chunk_path}")

    return chunk_paths


def split_audio_by_duration(
    file_path: str,
    segment_seconds: int = 30,
    output_dir: str | None = None,
) -> list[str]:
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(file_path), "segments")
    os.makedirs(output_dir, exist_ok=True)

    ext = os.path.splitext(file_path)[1]
    pattern = os.path.join(output_dir, f"segment_%03d{ext}")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", file_path,
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-c", "copy",
            "-reset_timestamps", "1",
            pattern,
        ],
        capture_output=True,
        check=True,
    )

    paths = sorted(glob.glob(os.path.join(output_dir, f"segment_*{ext}")))
    return paths


def concat_audio_files(file_paths: list[str], output_path: str) -> str:
    if len(file_paths) == 1:
        return file_paths[0]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in file_paths:
            f.write(f"file '{p}'\n")
        list_path = f.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                output_path,
            ],
            capture_output=True,
            check=True,
        )
    finally:
        os.unlink(list_path)

    return output_path
