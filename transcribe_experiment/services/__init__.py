from .base import BaseSTTService, ChunkResult, RunResult
from .elevenlabs import ElevenLabsService
from .faster_whisper import FasterWhisperService
from .gemini import GeminiService
from .openai_chat import OpenAIChatService
from .openai_transcribe import OpenAITranscribeService

SERVICE_REGISTRY: dict[str, type[BaseSTTService]] = {
    "faster_whisper": FasterWhisperService,
    "openai_transcribe": OpenAITranscribeService,
    "openai_chat": OpenAIChatService,
    "elevenlabs": ElevenLabsService,
    "gemini": GeminiService,
}


def create_service(
    name: str,
    services_config: dict,
    api_key: str,
) -> BaseSTTService:
    cls = SERVICE_REGISTRY[name]
    return cls(config=services_config.get(name, {}), api_key=api_key)
