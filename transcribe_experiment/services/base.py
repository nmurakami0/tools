from dataclasses import dataclass, field


@dataclass
class ChunkResult:
    chunk_index: int
    chunk_path: str
    text: str
    elapsed_seconds: float
    error: str | None = None
    detected_language: str | None = None
    language_probability: float | None = None


@dataclass
class RunResult:
    run_id: str
    service: str
    settings: dict
    chunks: list[ChunkResult]
    total_elapsed_seconds: float
    full_text: str = ""
    verbose_chunks: list[dict] | None = None

    def __post_init__(self):
        if not self.full_text:
            self.full_text = "\n".join(c.text for c in self.chunks if c.text)

    @property
    def char_count(self) -> int:
        return len(self.full_text)


class BaseSTTService:
    needs_splitting: bool = True

    def __init__(self, config: dict, api_key: str):
        self.config = config
        self.api_key = api_key

    def transcribe_chunk(self, chunk_path: str, settings: dict) -> str:
        raise NotImplementedError

    def transcribe_chunk_detailed(self, chunk_path: str, settings: dict) -> dict:
        text = self.transcribe_chunk(chunk_path, settings)
        return {"text": text, "language": None, "language_probability": None}
