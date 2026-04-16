from __future__ import annotations

import json
import logging
import time

import aiohttp

from duplex_bot.config import AzureSpeechConfig, AzureSTTConfig
from duplex_bot.core.audio import pcm_to_wav
from duplex_bot.core.events import Transcript
from duplex_bot.stt.base import STTBase

logger = logging.getLogger(__name__)


class AzureFastTranscription(STTBase):
    """Azure Fast Transcription API — batch transcription of speech segments.

    Supports both key-based and Entra ID (DefaultAzureCredential) authentication.
    """

    def __init__(self, speech_config: AzureSpeechConfig, stt_config: AzureSTTConfig):
        self._speech_config = speech_config
        self._stt_config = stt_config
        self._session: aiohttp.ClientSession | None = None

        # Entra ID token caching
        self._credential = None
        self._cached_token: str = ""
        self._token_expires_at: float = 0

    def _get_endpoint(self) -> str:
        resource = self._speech_config.resource_name
        region = self._speech_config.region
        if resource:
            return f"https://{resource}.cognitiveservices.azure.com"
        return f"https://{region}.api.cognitive.microsoft.com"

    async def _get_token(self) -> str:
        """Get a cached Entra ID token, refreshing if needed."""
        now = time.time()
        if self._cached_token and now < self._token_expires_at - 60:
            return self._cached_token

        if self._credential is None:
            from azure.identity import DefaultAzureCredential
            self._credential = DefaultAzureCredential()

        token = self._credential.get_token("https://cognitiveservices.azure.com/.default")
        self._cached_token = token.token
        self._token_expires_at = token.expires_on
        logger.debug("Azure Entra token refreshed (expires in %ds)", int(token.expires_on - now))
        return self._cached_token

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def transcribe(
        self,
        audio: bytes,
        sample_rate: int,
        language: str = "en-US",
    ) -> Transcript:
        """Transcribe audio using Azure Fast Transcription API."""
        session = await self._ensure_session()
        wav_data = pcm_to_wav(audio, sample_rate)

        url = (
            f"{self._get_endpoint()}"
            f"/speechtotext/transcriptions:transcribe"
            f"?api-version={self._stt_config.api_version}"
        )

        definition = json.dumps({
            "locales": [language or self._stt_config.language],
            "profanityFilterMode": "None",
            "channels": [0],
        })

        # Build auth headers
        if self._speech_config.auth_mode == "key":
            headers = {
                "Ocp-Apim-Subscription-Key": self._speech_config.subscription_key,
            }
        else:
            token = await self._get_token()
            headers = {
                "Authorization": f"Bearer {token}",
            }
        headers["Accept"] = "application/json"

        form = aiohttp.FormData()
        form.add_field(
            "audio",
            wav_data,
            filename="audio.wav",
            content_type="audio/wav",
        )
        form.add_field("definition", definition)

        try:
            async with session.post(url, data=form, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error("Azure STT error %d: %s", resp.status, error_text)
                    return Transcript(text="", confidence=0.0)

                result = await resp.json()
                return self._parse_response(result)

        except Exception:
            logger.exception("Azure Fast Transcription request failed")
            return Transcript(text="", confidence=0.0)

    def _parse_response(self, result: dict) -> Transcript:
        """Parse the Azure Fast Transcription API response."""
        phrases = result.get("phrases", [])
        if not phrases:
            combined = result.get("combinedPhrases", [])
            if combined:
                text = combined[0].get("text", "")
                return Transcript(text=text, confidence=1.0)
            return Transcript(text="", confidence=0.0)

        texts = [p.get("text", "") for p in phrases]
        text = " ".join(texts).strip()

        confidence = 1.0
        confidences = [p.get("confidence", 1.0) for p in phrases]
        if confidences:
            confidence = sum(confidences) / len(confidences)

        logger.debug("Azure STT: '%s' (confidence=%.3f)", text, confidence)
        return Transcript(text=text, confidence=confidence)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
