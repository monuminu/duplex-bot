from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from duplex_bot.vad.base import VADBase

logger = logging.getLogger(__name__)

SILERO_SAMPLE_RATE = 16000

# V5 model constants
_WINDOW_SIZES = {16000: 512, 8000: 256}
_CONTEXT_SIZES = {16000: 64, 8000: 32}

# Default model path (relative to this package)
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx"
_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


def _download_model(dest: Path) -> None:
    """Download the Silero VAD ONNX model if not present."""
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading Silero VAD ONNX model to %s ...", dest)
    urllib.request.urlretrieve(_MODEL_URL, str(dest))
    logger.info("Download complete (%.1f MB)", dest.stat().st_size / 1e6)


class SileroVAD(VADBase):
    """Silero VAD v5 using ONNX Runtime — no PyTorch dependency."""

    def __init__(self, model_path: str | Path | None = None):
        self._model_path = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self._session: ort.InferenceSession | None = None
        self._state: np.ndarray | None = None
        self._context: np.ndarray | None = None
        self._last_sr: int = 0

    async def load(self) -> None:
        """Load the Silero VAD ONNX model."""
        loop = asyncio.get_event_loop()

        def _load():
            if not self._model_path.exists():
                _download_model(self._model_path)
            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            return ort.InferenceSession(
                str(self._model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )

        self._session = await loop.run_in_executor(None, _load)
        self._reset_internal()
        logger.info("Silero VAD ONNX model loaded from %s", self._model_path)

    def _reset_internal(self) -> None:
        """Reset state and context tensors."""
        # state shape: (2, batch=1, 128) — V5 uses a single fused state
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(0, dtype=np.float32)
        self._last_sr = 0

    async def process_chunk(self, chunk: bytes, sample_rate: int) -> float:
        """Run VAD inference on a single audio chunk.

        Args:
            chunk: Raw 16-bit PCM mono audio. Must be exactly window_size samples
                   (512 for 16kHz, 256 for 8kHz).
            sample_rate: Must be 8000 or 16000.

        Returns:
            Speech probability [0.0, 1.0].
        """
        if self._session is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if sample_rate not in _WINDOW_SIZES:
            raise ValueError(
                f"Silero VAD supports 8000/16000 Hz, got {sample_rate} Hz"
            )

        # Convert PCM int16 bytes -> float32
        audio_int16 = np.frombuffer(chunk, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Handle sample-rate change: reset context
        if sample_rate != self._last_sr:
            self._context = np.zeros(0, dtype=np.float32)
            self._last_sr = sample_rate

        context_size = _CONTEXT_SIZES[sample_rate]

        # Build context-prepended input (V5 requirement)
        if self._context.shape[0] == 0:
            self._context = np.zeros(context_size, dtype=np.float32)

        # Prepend context to audio: input shape = (1, context_size + window_size)
        input_audio = np.concatenate([self._context, audio_float])
        input_tensor = input_audio[np.newaxis, :]  # (1, context_size + window_size)

        # Save tail of current chunk as context for next call
        self._context = audio_float[-context_size:]

        # Run inference
        sr_tensor = np.array(sample_rate, dtype=np.int64)
        outputs = self._session.run(
            ["output", "stateN"],
            {"input": input_tensor, "state": self._state, "sr": sr_tensor},
        )
        prob = outputs[0][0, 0]  # output shape: (1, 1)
        self._state = outputs[1]  # updated state

        return float(prob)

    def reset(self) -> None:
        """Reset the model's internal hidden state between utterances."""
        self._reset_internal()
