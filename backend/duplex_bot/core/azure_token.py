from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

AZURE_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureTokenProvider:
    """Shared Azure Entra ID token for a single voice session.

    Fetches one token at session start and reuses it for STT, TTS, and LLM.
    Azure AD tokens are valid for 60-75 minutes, which exceeds the
    configurable max call duration (default 30 min).
    """

    def __init__(self) -> None:
        self._token: str = ""
        self._initialized = False

    async def initialize(self) -> None:
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential(
            exclude_managed_identity_credential=True,
        )
        try:
            token = await credential.get_token(AZURE_COGNITIVE_SCOPE)
            self._token = token.token
            self._initialized = True
            logger.info("Azure token acquired (shared for session)")
        finally:
            await credential.close()

    @property
    def token(self) -> str:
        if not self._initialized:
            raise RuntimeError("AzureTokenProvider not initialized — call initialize() first")
        return self._token

    async def __call__(self) -> str:
        """Async callable — required by AsyncOpenAI's api_key provider interface."""
        return self.token
