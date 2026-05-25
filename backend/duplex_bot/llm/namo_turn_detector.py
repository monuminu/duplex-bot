from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
_ONNX_FILENAME = "model_quant.onnx"

_LANGUAGE_MAP = {
    "ar": "Arabic", "bn": "Bengali", "zh": "Chinese", "da": "Danish",
    "nl": "Dutch", "de": "German", "en": "English", "fi": "Finnish",
    "fr": "French", "hi": "Hindi", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "mr": "Marathi", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ru": "Russian", "es": "Spanish",
    "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
}


def _get_model_name(language: str | None) -> str:
    if language is None:
        return "Namo-Turn-Detector-v1-Multilingual"
    lang_name = _LANGUAGE_MAP.get(language.lower(), language.capitalize())
    return f"Namo-Turn-Detector-v1-{lang_name}"


class NamoSemanticClassifier:
    """ONNX-based end-of-turn classifier using NAMO Turn Detector v1."""

    def __init__(self, language: str | None = "en"):
        self._language = language
        self._model_name = _get_model_name(language)
        self._max_length = 8192 if language is None else 512
        self._session: ort.InferenceSession | None = None
        self._tokenizer = None

    async def load(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_sync)

    def _load_sync(self) -> None:
        from transformers import AutoTokenizer

        local_dir = _MODEL_DIR / self._model_name
        model_path = local_dir / _ONNX_FILENAME

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

        # Load tokenizer from local directory (pre-downloaded alongside ONNX model)
        tokenizer_path = local_dir if (local_dir / "tokenizer.json").exists() else None
        if tokenizer_path:
            self._tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_path))
        else:
            hf_repo = f"videosdk-live/{self._model_name}"
            logger.warning("Local tokenizer not found at %s, downloading from %s", local_dir, hf_repo)
            self._tokenizer = AutoTokenizer.from_pretrained(hf_repo)
            self._tokenizer.save_pretrained(str(local_dir))

        logger.info(
            "NAMO turn detector loaded (model=%s, local=%s)",
            self._model_name, local_dir,
        )

    async def classify(self, transcript: str, _context: list[dict]) -> float:
        if self._session is None or self._tokenizer is None:
            raise RuntimeError("NAMO model not loaded. Call load() first.")

        encoded = self._tokenizer(
            transcript,
            return_tensors="np",
            truncation=True,
            max_length=self._max_length,
        )

        outputs = self._session.run(
            None,
            {
                "input_ids": encoded["input_ids"].astype(np.int64),
                "attention_mask": encoded["attention_mask"].astype(np.int64),
            },
        )

        logits = outputs[0][0]
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        return float(probs[1])  # label 1 = end of turn
