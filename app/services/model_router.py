from app.core.config import Settings, get_settings
from app.providers import DeepgramProvider
from app.schemas import ProviderName


class ModelServicesRouter:
    """Routes transcription work to the configured provider.

    Currently only supports Deepgram, but can be extended to support multiple providers in the future.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def transcription_provider(
        self, provider: ProviderName = ProviderName.deepgram
    ) -> DeepgramProvider:
        if provider != ProviderName.deepgram:
            raise ValueError(f"Unsupported transcription provider: {provider}")
        return DeepgramProvider(self.settings)
