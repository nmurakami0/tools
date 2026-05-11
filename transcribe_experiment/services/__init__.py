from .base import BaseSTTService, ChunkResult, RunResult
from .elevenlabs import ElevenLabsService
from .faster_whisper import FasterWhisperService
from .openai_transcribe import OpenAITranscribeService
from .two_pass import TwoPassService

SERVICE_REGISTRY: dict[str, type[BaseSTTService]] = {
    "faster_whisper": FasterWhisperService,
    "openai_transcribe": OpenAITranscribeService,
    "elevenlabs": ElevenLabsService,
    "two_pass": TwoPassService,
}


def create_service(
    name: str,
    services_config: dict,
    api_key: str,
    *,
    auth: dict | None = None,
) -> BaseSTTService:
    cls = SERVICE_REGISTRY[name]
    if name == "two_pass":
        return cls(
            config=services_config.get(name, {}),
            api_key="",
            services_config=services_config,
            auth=auth or {},
        )
    return cls(config=services_config.get(name, {}), api_key=api_key)
