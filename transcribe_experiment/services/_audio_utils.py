import subprocess


def convert_to_mp3_bytes(audio_path: str, bitrate: str = "128k") -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            audio_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            "-y",
            "-loglevel",
            "error",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout
