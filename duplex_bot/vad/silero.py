from __future__ import annotations

import asyncio
import logging

import numpy as np
import torch

from duplex_bot.vad.base import VADBase

logger = logging.getLogger(__name__)

SILERO_SAMPLE_RATE = 16000


class SileroVAD(VADBase):
    """Silero VAD using PyTorch for speech probability inference."""

    def __init__(self):
        self._model = None

    async def load(self) -> None:
        """Load the Silero VAD model via torch.hub."""
        loop = asyncio.get_event_loop()
        model, _ = await loop.run_in_executor(
            None,
            lambda: torch.hub.load(
                "snakers4/silero-vad", "silero_vad", trust_repo=True
            ),
        )
        self._model = model
        logger.info("Silero VAD model loaded via torch.hub")

    async def process_chunk(self, chunk: bytes, sample_rate: int) -> float:
        """Run VAD inference on a single audio chunk.

        Args:
            chunk: Raw 16-bit PCM mono audio.
            sample_rate: Must be 16000 for Silero.

        Returns:
            Speech probability [0.0, 1.0].
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if sample_rate != SILERO_SAMPLE_RATE:
            raise ValueError(
                f"Silero VAD requires {SILERO_SAMPLE_RATE}Hz audio, got {sample_rate}Hz"
            )

        # Convert PCM int16 bytes → float32 tensor (matching working code's int2float)
        audio_int16 = np.frombuffer(chunk, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio_float)

        # Inference (fast, <1ms)
        with torch.no_grad():
            prob = self._model(tensor, sample_rate).item()

        return float(prob)

    def reset(self) -> None:
        """Reset the model's internal hidden state."""
        if self._model is not None:
            self._model.reset_states()
