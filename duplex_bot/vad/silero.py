from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from duplex_bot.core.audio import pcm_to_float32
from duplex_bot.vad.base import VADBase

logger = logging.getLogger(__name__)

# Silero VAD ONNX model expects 16kHz audio in 30ms chunks (480 samples)
SILERO_SAMPLE_RATE = 16000
SILERO_WINDOW_SIZE = 512  # ~32ms at 16kHz — Silero v5 uses 512


class SileroVAD(VADBase):
    """Silero VAD using ONNX Runtime for lightweight, fast inference."""

    def __init__(self, model_path: str | Path | None = None):
        self._model_path = model_path
        self._session: ort.InferenceSession | None = None
        # Silero internal state tensors
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array([SILERO_SAMPLE_RATE], dtype=np.int64)

    async def load(self) -> None:
        """Load the Silero VAD ONNX model."""
        model_path = self._resolve_model_path()
        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"Silero VAD model not found at {model_path}. "
                "Download from https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
            )
        loop = asyncio.get_event_loop()
        self._session = await loop.run_in_executor(
            None,
            lambda: ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            ),
        )
        logger.info("Silero VAD model loaded from %s", model_path)

    def _resolve_model_path(self) -> str:
        if self._model_path:
            return str(self._model_path)
        # Default: look in the package's models directory
        default = Path(__file__).parent.parent / "models" / "silero_vad.onnx"
        return str(default)

    async def process_chunk(self, chunk: bytes, sample_rate: int) -> float:
        """Run VAD inference on a single audio chunk.

        Args:
            chunk: Raw 16-bit PCM mono audio.
            sample_rate: Must be 16000 for Silero.

        Returns:
            Speech probability [0.0, 1.0].
        """
        if self._session is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if sample_rate != SILERO_SAMPLE_RATE:
            raise ValueError(f"Silero VAD requires {SILERO_SAMPLE_RATE}Hz audio, got {sample_rate}Hz")

        # Convert PCM to float32 numpy array
        float_samples = pcm_to_float32(chunk)
        audio_tensor = np.array(float_samples, dtype=np.float32).reshape(1, -1)

        # Run inference in thread executor (ONNX inference is synchronous, ~0.5ms)
        loop = asyncio.get_event_loop()
        prob = await loop.run_in_executor(None, self._infer, audio_tensor)
        return prob

    def _infer(self, audio_tensor: np.ndarray) -> float:
        """Synchronous ONNX inference."""
        ort_inputs = {
            "input": audio_tensor,
            "state": self._state,
            "sr": self._sr,
        }
        ort_outputs = self._session.run(None, ort_inputs)
        # outputs: [probability, updated_state]
        out_prob = ort_outputs[0].item()
        self._state = ort_outputs[1]
        return float(out_prob)

    def reset(self) -> None:
        """Reset the internal hidden state."""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
