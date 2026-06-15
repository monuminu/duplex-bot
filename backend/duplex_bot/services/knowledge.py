from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from duplex_bot.config import AppConfig
from duplex_bot.db.models import VoiceAgentKnowledgeChunk, VoiceAgentKnowledgeFile

logger = logging.getLogger(__name__)


# ─── Text extraction ────────────────────────────────────────────────


def _extract_text(path: Path, content_type: str, file_name: str) -> str:
    """Extract plain text from a stored knowledge file.

    Supports txt/markdown/csv/json natively, PDF via pypdf, and docx via
    python-docx. Unknown types are best-effort decoded as UTF-8 text.
    """
    suffix = Path(file_name).suffix.lower()

    if suffix in {".pdf"} or "pdf" in content_type:
        return _extract_pdf(path)
    if suffix in {".docx"} or "wordprocessingml" in content_type:
        return _extract_docx(path)

    # Plain-text family (txt, md, csv, json, html, etc.)
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise RuntimeError(f"Could not read file: {exc}") from exc


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - skip unreadable pages
            continue
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


# ─── Chunking ───────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks on heading/paragraph/word boundaries.

    Markdown headings (``#``..``######``) start a new chunk so that distinct
    sections (e.g. "Shipping", "Returns") stay separately retrievable instead of
    being merged into one oversized block.
    """
    text = _normalize(text)
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        starts_section = bool(re.match(r"#{1,6}\s", paragraph))
        # A heading flushes the current buffer so each section is its own chunk.
        if starts_section and buffer:
            chunks.append(buffer)
            buffer = ""

        if len(buffer) + len(paragraph) + 2 <= chunk_size:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
            continue
        if buffer:
            chunks.append(buffer)
        if len(paragraph) <= chunk_size:
            buffer = paragraph
        else:
            # Paragraph longer than a chunk: hard-split with overlap.
            chunks.extend(_split_long(paragraph, chunk_size, overlap))
            buffer = ""

    if buffer:
        chunks.append(buffer)
    return chunks


def _split_long(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if length + len(word) + 1 > chunk_size and current:
            chunks.append(" ".join(current))
            # Keep an overlapping tail for context continuity.
            tail: list[str] = []
            tail_len = 0
            for prev in reversed(current):
                if tail_len + len(prev) + 1 > overlap:
                    break
                tail.insert(0, prev)
                tail_len += len(prev) + 1
            current = tail
            length = tail_len
        current.append(word)
        length += len(word) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


# ─── Ingestion ──────────────────────────────────────────────────────


def ingest_file(
    db: Session,
    record: VoiceAgentKnowledgeFile,
    config: AppConfig,
) -> int:
    """Extract, chunk, and store retrievable chunks for a knowledge file.

    Returns the number of chunks created. Replaces any existing chunks for the
    file (idempotent re-ingest).
    """
    path = Path(record.storage_path)
    if not path.exists():
        raise RuntimeError("Stored file is missing")

    text = _extract_text(path, record.content_type, record.file_name)
    chunks = chunk_text(
        text,
        config.knowledge.chunk_size_chars,
        config.knowledge.chunk_overlap_chars,
    )

    db.execute(
        delete(VoiceAgentKnowledgeChunk).where(
            VoiceAgentKnowledgeChunk.file_id == record.id
        )
    )
    for index, content in enumerate(chunks):
        db.add(
            VoiceAgentKnowledgeChunk(
                file_id=record.id,
                agent_id=record.agent_id,
                chunk_index=index,
                content=content,
            )
        )
    logger.info(
        "Ingested knowledge file %s: %d chunks", record.file_name, len(chunks)
    )
    return len(chunks)


# ─── Retrieval ──────────────────────────────────────────────────────

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "what", "how", "do", "does", "i",
    "you", "it", "this", "that", "can", "my", "me", "we", "our", "your",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


def search_chunks(
    db: Session,
    agent_id: str,
    query: str,
    max_results: int,
) -> list[VoiceAgentKnowledgeChunk]:
    """Lexical retrieval over an agent's knowledge chunks.

    Scores candidate chunks by overlapping query-term frequency. Pulls a bounded
    candidate set via SQL LIKE filters (works on both SQLite and Postgres) and
    ranks in Python — fast and dependency-free for the corpus sizes a single
    small-business agent uploads. Swappable for pgvector later without touching
    the voice core.
    """
    terms = _tokenize(query)
    if not terms:
        return []

    candidates = _fetch_candidates(db, agent_id, terms)
    scored: list[tuple[int, VoiceAgentKnowledgeChunk]] = []
    for chunk in candidates:
        content_lower = chunk.content.lower()
        score = sum(content_lower.count(term) for term in terms)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored[:max_results]]


def _fetch_candidates(
    db: Session, agent_id: str, terms: list[str], limit: int = 200
) -> list[VoiceAgentKnowledgeChunk]:
    from sqlalchemy import or_

    conditions = [
        func.lower(VoiceAgentKnowledgeChunk.content).like(f"%{term}%")
        for term in terms[:8]
    ]
    query = (
        select(VoiceAgentKnowledgeChunk)
        .where(VoiceAgentKnowledgeChunk.agent_id == agent_id)
        .where(or_(*conditions))
        .limit(limit)
    )
    return list(db.scalars(query).all())


def has_knowledge(db: Session, agent_id: str) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(VoiceAgentKnowledgeChunk)
        .where(VoiceAgentKnowledgeChunk.agent_id == agent_id)
    )
    return bool(count)
