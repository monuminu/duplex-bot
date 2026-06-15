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

    def __init__(
        self,
        use_managed_identity: bool = False,
        managed_identity_client_id: str = "",
    ) -> None:
        self._token: str = ""
        self._initialized = False
        self._use_managed_identity = use_managed_identity
        self._managed_identity_client_id = managed_identity_client_id

    async def initialize(self) -> None:
        from azure.identity.aio import DefaultAzureCredential

        # Local dev authenticates via `az login`; managed identity is excluded
        # by default so a half-configured IMDS endpoint can't shadow it. In
        # Azure (Container Apps / App Service / AKS / VM) set
        # AZURE_SPEECH__USE_MANAGED_IDENTITY=true so the workload identity is
        # used instead. Optionally pin a user-assigned identity by client id.
        cred_kwargs: dict[str, object] = {
            "exclude_managed_identity_credential": not self._use_managed_identity,
        }
        if self._use_managed_identity and self._managed_identity_client_id:
            cred_kwargs["managed_identity_client_id"] = self._managed_identity_client_id

        credential = DefaultAzureCredential(**cred_kwargs)
        try:
            token = await credential.get_token(AZURE_COGNITIVE_SCOPE)
            self._token = token.token
            self._initialized = True
            logger.info(
                "Azure token acquired (shared for session, managed_identity=%s)",
                self._use_managed_identity,
            )
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
