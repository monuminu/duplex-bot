from __future__ import annotations

import asyncio
import logging

import aiohttp
from duplex_bot.config import AzureSpeechConfig, AzureSTTConfig
from duplex_bot.core.audio import pcm_to_wav
from duplex_bot.core.events import Transcript
from duplex_bot.stt.base import STTBase
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionContent, TranscriptionOptions

logger = logging.getLogger(__name__)



class AzureFastTranscription(STTBase):
    """Azure Fast Transcription API — batch transcription of speech segments.

    Supports both key-based and Entra ID (DefaultAzureCredential) authentication.
    """

    def __init__(self, speech_config: AzureSpeechConfig, stt_config: AzureSTTConfig):
        self._speech_config = speech_config
        self._stt_config = stt_config
        self._session: aiohttp.ClientSession | None = None
        if self._speech_config.auth_mode == "key":
            self._credential = AzureKeyCredential(self._speech_config.api_key)
        else:
            self._credential = DefaultAzureCredential(exclude_managed_identity_credential=True)
        self.client = TranscriptionClient(endpoint=self._get_endpoint(), credential=self._credential)
        self._cached_token: str = ""
        self._token_expires_at: float = 0
        
    def _get_endpoint(self) -> str:
        resource = self._speech_config.resource_name
        region = self._speech_config.region
        if resource:
            return f"https://{resource}.cognitiveservices.azure.com"
        return f"https://{region}.api.cognitive.microsoft.com"
    
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
        wav_data = pcm_to_wav(audio, sample_rate)
        options = TranscriptionOptions(locales=[language])
        request_content = TranscriptionContent(
            definition=options,
            audio=("audio.wav", wav_data, "audio/wav"),
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.client.transcribe, request_content)
        text = result.combined_phrases[0].text if result.combined_phrases else ""
        duration_milliseconds = result.duration_milliseconds
        logger.debug(f"Transcription result: '{text}' (duration: {duration_milliseconds} ms)")
        return Transcript(text=text, confidence=0)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
