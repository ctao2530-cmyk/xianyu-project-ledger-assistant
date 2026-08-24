from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from ...config import Settings
from ...database import Database
from ...global_agent_schemas import (
    AgentKnowledgeCitation,
    AgentKnowledgeReindexResult,
    AgentKnowledgeStatus,
)
from ...models import GlobalAgentKnowledgeChunk, GlobalAgentKnowledgeDocument


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"(?im)^\s*(?:api[_-]?key|authorization|cookie|password|secret|token)"
        r"\s*[:=]\s*['\"]?[^\s'\"]{12,}"
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class _SourceDocument:
    path: Path
    relative_path: str
    title: str
    maturity: str
    content: str
    content_hash: str
    exclusion_reason: str


class GlobalAgentRAG:
    """Manual, local-only Markdown retrieval over explicitly approved folders."""

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.root = Path(settings.global_agent_vault_root).expanduser().resolve()
        self.approved_directories = tuple(
            settings.global_agent_knowledge_directory_list
        )

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return f"{prefix}-{digest[:32]}"

    @staticmethod
    def _frontmatter(content: str) -> tuple[dict[str, str], str]:
        match = FRONTMATTER_RE.match(content)
        if not match:
            return {}, content
        metadata: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip("'\"")
        return metadata, content[match.end():]

    @staticmethod
    def _contains_secret(content: str) -> bool:
        return any(pattern.search(content) for pattern in SECRET_PATTERNS)

    def _scan(self) -> list[_SourceDocument]:
        documents: list[_SourceDocument] = []
        if not self.root.is_dir():
            return documents
        for directory_name in self.approved_directories:
            directory = (self.root / directory_name).resolve()
            try:
                directory.relative_to(self.root)
            except ValueError:
                continue
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.md")):
                resolved = path.resolve()
                try:
                    relative = resolved.relative_to(self.root).as_posix()
                    resolved.relative_to(directory)
                except ValueError:
                    continue
                try:
                    raw = resolved.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                metadata, body = self._frontmatter(raw)
                title = metadata.get("title", "").strip() or resolved.stem
                maturity = metadata.get("maturity", "candidate").strip() or "candidate"
                reason = "contains_secret_material" if self._contains_secret(raw) else ""
                documents.append(
                    _SourceDocument(
                        path=resolved,
                        relative_path=relative,
                        title=title[:500],
                        maturity=maturity[:32],
                        content=body,
                        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                        exclusion_reason=reason,
                    )
                )
        return documents

    def _chunks(self, document: _SourceDocument) -> list[tuple[str, str]]:
        body = document.content.strip()
        if not body:
            return []
        matches = list(HEADING_RE.finditer(body))
        sections: list[tuple[str, str]] = []
        if not matches:
            sections.append((document.title, body))
        else:
            intro = body[: matches[0].start()].strip()
            if intro:
                sections.append((document.title, intro))
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
                section = body[match.end():end].strip()
                if section:
                    sections.append((match.group(2).strip()[:500], section))
        result: list[tuple[str, str]] = []
        maximum = self.settings.global_agent_chunk_chars
        for heading, section in sections:
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section) if part.strip()]
            current = ""
            for paragraph in paragraphs or [section]:
                while len(paragraph) > maximum:
                    if current:
                        result.append((heading, current))
                        current = ""
                    result.append((heading, paragraph[:maximum]))
                    paragraph = paragraph[maximum:]
                candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
                if len(candidate) > maximum and current:
                    result.append((heading, current))
                    current = paragraph
                else:
                    current = candidate
            if current:
                result.append((heading, current))
        return result

    def status(self) -> AgentKnowledgeStatus:
        with self.database.session() as session:
            active = session.scalar(
                select(func.count()).select_from(GlobalAgentKnowledgeDocument).where(
                    GlobalAgentKnowledgeDocument.active.is_(True)
                )
            ) or 0
            inactive = session.scalar(
                select(func.count()).select_from(GlobalAgentKnowledgeDocument).where(
                    GlobalAgentKnowledgeDocument.active.is_(False)
                )
            ) or 0
            chunks = session.scalar(
                select(func.count()).select_from(GlobalAgentKnowledgeChunk)
            ) or 0
            last = session.scalar(select(func.max(GlobalAgentKnowledgeDocument.indexed_at)))
        return AgentKnowledgeStatus(
            root=str(self.root),
            approved_directories=list(self.approved_directories),
            active_documents=int(active),
            inactive_documents=int(inactive),
            chunks=int(chunks),
            last_indexed_at=last,
        )

    def reindex(self) -> AgentKnowledgeReindexResult:
        scanned = self._scan()
        now = datetime.now(timezone.utc)
        seen = {document.relative_path for document in scanned}
        indexed = 0
        excluded = 0
        deactivated = 0
        with self.database.session() as session:
            existing = {
                row.relative_path: row
                for row in session.scalars(select(GlobalAgentKnowledgeDocument))
            }
            session.execute(text("DELETE FROM global_agent_knowledge_fts"))
            for relative_path, row in existing.items():
                if relative_path not in seen:
                    if row.active:
                        deactivated += 1
                    row.active = False
                    row.exclusion_reason = "source_missing"
                    row.indexed_at = now
                    session.execute(
                        delete(GlobalAgentKnowledgeChunk).where(
                            GlobalAgentKnowledgeChunk.document_id == row.id
                        )
                    )
            session.flush()
            for document in scanned:
                document_id = self._stable_id("knowledge", document.relative_path)
                row = existing.get(document.relative_path)
                if row is None:
                    row = GlobalAgentKnowledgeDocument(
                        id=document_id,
                        relative_path=document.relative_path,
                        absolute_path=str(document.path),
                        title=document.title,
                        maturity=document.maturity,
                        content_hash=document.content_hash,
                        active=False,
                        exclusion_reason="",
                        indexed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                row.absolute_path = str(document.path)
                row.title = document.title
                row.maturity = document.maturity
                row.content_hash = document.content_hash
                row.indexed_at = now
                row.updated_at = now
                row.exclusion_reason = document.exclusion_reason
                row.active = not bool(document.exclusion_reason)
                session.execute(
                    delete(GlobalAgentKnowledgeChunk).where(
                        GlobalAgentKnowledgeChunk.document_id == row.id
                    )
                )
                session.flush()
                if document.exclusion_reason:
                    excluded += 1
                    continue
                indexed += 1
                for ordinal, (heading, content) in enumerate(self._chunks(document)):
                    chunk_id = self._stable_id(
                        "chunk", f"{document.relative_path}#{ordinal}"
                    )
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    session.add(
                        GlobalAgentKnowledgeChunk(
                            id=chunk_id,
                            document_id=row.id,
                            ordinal=ordinal,
                            heading=heading,
                            content=content,
                            content_hash=content_hash,
                            created_at=now,
                        )
                    )
                    session.execute(
                        text(
                            "INSERT INTO global_agent_knowledge_fts "
                            "(chunk_id, heading, content) VALUES (:id, :heading, :content)"
                        ),
                        {"id": chunk_id, "heading": heading, "content": content},
                    )
            session.commit()
        status = self.status()
        return AgentKnowledgeReindexResult(
            **status.model_dump(),
            indexed_documents=indexed,
            excluded_documents=excluded,
            deactivated_documents=deactivated,
        )

    def search(self, query: str, *, limit: int | None = None) -> list[AgentKnowledgeCitation]:
        normalized = " ".join(query.strip().split())[:240]
        if not normalized:
            return []
        bounded = min(limit or self.settings.global_agent_rag_top_k, 12)
        phrase = '"' + normalized.replace('"', '""') + '"'
        sql = text(
            "SELECT c.id, c.heading, c.content, c.content_hash, "
            "d.relative_path, d.absolute_path, d.title, d.maturity "
            "FROM global_agent_knowledge_fts "
            "JOIN global_agent_knowledge_chunks c "
            "ON c.id = global_agent_knowledge_fts.chunk_id "
            "JOIN global_agent_knowledge_documents d ON d.id = c.document_id "
            "WHERE global_agent_knowledge_fts MATCH :query AND d.active = 1 "
            "ORDER BY bm25(global_agent_knowledge_fts) LIMIT :limit"
        )
        fallback = text(
            "SELECT c.id, c.heading, c.content, c.content_hash, "
            "d.relative_path, d.absolute_path, d.title, d.maturity "
            "FROM global_agent_knowledge_chunks c "
            "JOIN global_agent_knowledge_documents d ON d.id = c.document_id "
            "WHERE d.active = 1 AND (c.heading LIKE :like OR c.content LIKE :like) "
            "ORDER BY d.indexed_at DESC, c.ordinal ASC LIMIT :limit"
        )
        with self.database.session() as session:
            try:
                rows = list(
                    session.execute(sql, {"query": phrase, "limit": bounded}).mappings()
                )
            except OperationalError:
                rows = []
            if not rows:
                rows = list(
                    session.execute(
                        fallback,
                        {"like": f"%{normalized}%", "limit": bounded},
                    ).mappings()
                )
            if not rows:
                # Chinese questions often contain a relevant two-character
                # concept inside a longer sentence (for example “证据”). FTS5
                # trigram intentionally requires three characters, so use a
                # bounded local overlap pass instead of silently reporting no
                # match. This remains read-only and never leaves SQLite.
                candidates = list(
                    session.execute(
                        text(
                            "SELECT c.id, c.heading, c.content, c.content_hash, "
                            "d.relative_path, d.absolute_path, d.title, d.maturity "
                            "FROM global_agent_knowledge_chunks c "
                            "JOIN global_agent_knowledge_documents d ON d.id = c.document_id "
                            "WHERE d.active = 1 ORDER BY d.indexed_at DESC, c.ordinal ASC "
                            "LIMIT 2000"
                        )
                    ).mappings()
                )
                compact_query = re.sub(r"[^\w\u4e00-\u9fff]", "", normalized)
                query_grams = {
                    compact_query[index:index + size]
                    for size in (2, 3)
                    for index in range(max(0, len(compact_query) - size + 1))
                }
                scored: list[tuple[int, Any]] = []
                for candidate in candidates:
                    compact_value = re.sub(
                        r"[^\w\u4e00-\u9fff]",
                        "",
                        f"{candidate['heading']}{candidate['content']}",
                    )
                    value_grams = {
                        compact_value[index:index + size]
                        for size in (2, 3)
                        for index in range(max(0, len(compact_value) - size + 1))
                    }
                    score = sum(len(value) for value in query_grams.intersection(value_grams))
                    if score:
                        scored.append((score, candidate))
                scored.sort(
                    key=lambda item: (item[0], str(item[1]["relative_path"])),
                    reverse=True,
                )
                rows = [candidate for _score, candidate in scored[:bounded]]
        return [
            AgentKnowledgeCitation(
                id=f"knowledge:{row['id']}",
                relative_path=str(row["relative_path"]),
                absolute_path=str(row["absolute_path"]),
                title=str(row["title"]),
                heading=str(row["heading"]),
                snippet=" ".join(str(row["content"]).split())[:420],
                maturity=str(row["maturity"]),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]
