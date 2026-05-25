from __future__ import annotations

import audioop
import io
import struct
import wave


def pcm_to_wav(pcm_data: bytes, sample_rate: int, sample_width: int = 2, channels: int = 1) -> bytes:
    """Wrap raw PCM data in a WAV header.

    Args:
        pcm_data: Raw PCM audio bytes.
        sample_rate: Sample rate in Hz.
        sample_width: Bytes per sample (2 for 16-bit).
        channels: Number of audio channels (1 for mono).

    Returns:
        Complete WAV file as bytes.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def resample_pcm(
    pcm_data: bytes,
    from_rate: int,
    to_rate: int,
    sample_width: int = 2,
    channels: int = 1,
) -> bytes:
    """Resample raw PCM audio from one sample rate to another.

    Uses audioop.ratecv for resampling.

    Args:
        pcm_data: Raw PCM audio bytes.
        from_rate: Source sample rate.
        to_rate: Target sample rate.
        sample_width: Bytes per sample.
        channels: Number of channels.

    Returns:
        Resampled PCM data.
    """
    if from_rate == to_rate:
        return pcm_data
    resampled, _ = audioop.ratecv(pcm_data, sample_width, channels, from_rate, to_rate, None)
    return resampled


def mulaw_to_pcm(mulaw_data: bytes) -> bytes:
    """Convert mu-law encoded audio to 16-bit linear PCM."""
    return audioop.ulaw2lin(mulaw_data, 2)


def pcm_to_mulaw(pcm_data: bytes) -> bytes:
    """Convert 16-bit linear PCM to mu-law encoding."""
    return audioop.lin2ulaw(pcm_data, 2)


def pcm_duration_ms(pcm_data: bytes, sample_rate: int, sample_width: int = 2) -> float:
    """Calculate the duration of PCM audio in milliseconds."""
    num_samples = len(pcm_data) / sample_width
    return (num_samples / sample_rate) * 1000


def split_pcm_chunks(pcm_data: bytes, chunk_duration_ms: int, sample_rate: int, sample_width: int = 2) -> list[bytes]:
    """Split PCM data into fixed-duration chunks.

    Args:
        pcm_data: Raw PCM audio bytes.
        chunk_duration_ms: Duration of each chunk in ms.
        sample_rate: Sample rate in Hz.
        sample_width: Bytes per sample.

    Returns:
        List of PCM byte chunks.
    """
    bytes_per_chunk = int(sample_rate * sample_width * chunk_duration_ms / 1000)
    chunks = []
    for i in range(0, len(pcm_data), bytes_per_chunk):
        chunk = pcm_data[i : i + bytes_per_chunk]
        if len(chunk) == bytes_per_chunk:
            chunks.append(chunk)
    return chunks


def keep_trailing_pcm(
    pcm_data: bytes,
    keep_duration_ms: int,
    sample_rate: int,
    sample_width: int = 2,
) -> bytes:
    """Keep at most the requested amount of trailing PCM audio."""
    if keep_duration_ms <= 0:
        return b""
    bytes_to_keep = int(sample_rate * sample_width * keep_duration_ms / 1000)
    if len(pcm_data) <= bytes_to_keep:
        return pcm_data
    return pcm_data[-bytes_to_keep:]


def pcm_to_float32(pcm_data: bytes, sample_width: int = 2) -> list[float]:
    """Convert 16-bit PCM bytes to float32 samples in [-1.0, 1.0] range.

    Used for feeding audio to VAD models that expect float input.
    """
    num_samples = len(pcm_data) // sample_width
    samples = struct.unpack(f"<{num_samples}h", pcm_data[:num_samples * sample_width])
    return [s / 32768.0 for s in samples]
