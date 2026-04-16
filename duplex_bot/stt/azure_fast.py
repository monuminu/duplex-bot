from __future__ import annotations

import json
import logging

import aiohttp

from duplex_bot.config import AzureSpeechConfig, AzureSTTConfig
from duplex_bot.core.audio import pcm_to_wav
from duplex_bot.core.events import Transcript
from duplex_bot.stt.base import STTBase

logger = logging.getLogger(__name__)


class AzureFastTranscription(STTBase):
    """Azure Fast Transcription API — batch transcription of speech segments.

    Uses the REST-based Fast Transcription endpoint which is optimized for
    short audio segments. Ideal for VAD-segmented speech.
    """

    def __init__(self, speech_config: AzureSpeechConfig, stt_config: AzureSTTConfig):
        self._speech_config = speech_config
        self._stt_config = stt_config
        self._session: aiohttp.ClientSession | None = None

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
        """Transcribe audio using Azure Fast Transcription API.

        Encodes raw PCM as WAV, sends multipart POST to the API.
        """
        session = await self._ensure_session()
        wav_data = pcm_to_wav(audio, sample_rate)

        url = (
            f"https://{self._speech_config.region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe"
            f"?api-version={self._stt_config.api_version}"
        )

        definition = {
            "locales": [language or self._stt_config.language],
            "profanityFilterMode": "None",
        }

        form = aiohttp.FormData()
        form.add_field(
            "audio",
            wav_data,
            filename="audio.wav",
            content_type="audio/wav",
        )
        form.add_field(
            "definition",
            json.dumps(definition),
            content_type="application/json",
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self._speech_config.subscription_key,
            "Accept": "application/json",
        }

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
        combined_phrases = result.get("combinedPhrases", [])
        if not combined_phrases:
            return Transcript(text="", confidence=0.0)

        text = combined_phrases[0].get("text", "")

        # Extract confidence from individual phrases
        phrases = result.get("phrases", [])
        confidence = 1.0
        if phrases:
            confidences = [p.get("confidence", 1.0) for p in phrases]
            confidence = sum(confidences) / len(confidences)

        logger.debug("Azure STT: '%s' (confidence=%.3f)", text, confidence)
        return Transcript(text=text, confidence=confidence)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
