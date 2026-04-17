from __future__ import annotations

import json
import logging
import time

import aiohttp
from azure.identity.aio import DefaultAzureCredential

from duplex_bot.config import AzureSpeechConfig, AzureSTTConfig
from duplex_bot.core.audio import pcm_to_wav
from duplex_bot.core.events import Transcript
from duplex_bot.stt.base import STTBase

logger = logging.getLogger(__name__)


class AzureFastTranscription(STTBase):
    """Azure Fast Transcription via REST — fully async with connection reuse."""

    def __init__(self, speech_config: AzureSpeechConfig, stt_config: AzureSTTConfig):
        self._speech_config = speech_config
        self._stt_config = stt_config
        self._session: aiohttp.ClientSession | None = None

        self._use_key = speech_config.auth_mode == "key"
        if not self._use_key:
            self._credential = DefaultAzureCredential(
                exclude_managed_identity_credential=True,
            )
            self._cached_token: str = ""
            self._token_expires_at: float = 0

        self._base_url = self._build_base_url()

    def _build_base_url(self) -> str:
        resource = self._speech_config.resource_name
        region = self._speech_config.region
        return f"https://{resource}.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15"

    async def _get_bearer_token(self) -> str:
        now = time.time()
        if self._cached_token and now < self._token_expires_at - 60:
            return self._cached_token
        token = await self._credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        )
        self._cached_token = token.token
        self._token_expires_at = token.expires_on
        return self._cached_token

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(keepalive_timeout=300)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def transcribe(
        self,
        audio: bytes,
        sample_rate: int,
        language: str = "en-US",
    ) -> Transcript:
        t0 = time.monotonic()
        session = await self._ensure_session()
        wav_data = pcm_to_wav(audio, sample_rate)
        t_wav = time.monotonic()

        headers: dict[str, str] = {}
        if self._use_key:
            headers["Ocp-Apim-Subscription-Key"] = self._speech_config.subscription_key
        else:
            headers["Authorization"] = f"Bearer {await self._get_bearer_token()}"
        t_auth = time.monotonic()

        definition = json.dumps({"locales": [language]})
        form = aiohttp.FormData()
        form.add_field(
            "definition", definition, content_type="application/json",
        )
        form.add_field(
            "audio", wav_data, filename="audio.wav", content_type="audio/wav",
        )

        async with session.post(
            self._base_url, data=form, headers=headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("STT request failed (%d): %s", resp.status, body[:200])
                return Transcript(text="", confidence=0.0)

            result = await resp.json()
        t_api = time.monotonic()

        combined = result.get("combinedPhrases", [])
        text = combined[0].get("text", "") if combined else ""
        logger.info(
            "STT breakdown: wav=%.0fms auth=%.0fms api=%.0fms total=%.0fms audio=%dB",
            (t_wav - t0) * 1000,
            (t_auth - t_wav) * 1000,
            (t_api - t_auth) * 1000,
            (t_api - t0) * 1000,
            len(wav_data),
        )
        return Transcript(text=text, confidence=0.0)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if not self._use_key:
            await self._credential.close()
