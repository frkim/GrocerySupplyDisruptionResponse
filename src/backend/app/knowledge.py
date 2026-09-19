"""Retrieval over the disruption knowledge corpus.

Uses Azure AI Search vector + semantic retrieval when available; otherwise falls back
to keyword scoring over the bundled Markdown so the agent still produces grounded output.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from azure.identity.aio import DefaultAzureCredential

from .config import get_settings
from .paths import knowledge_dir

logger = logging.getLogger(__name__)


class KnowledgeService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = None
        self._credential: DefaultAzureCredential | None = None
        self._local_docs: list[dict[str, str]] = []
        self.source = "unknown"

    async def initialize(self) -> None:
        self._load_local_docs()
        if not self._settings.has_search:
            self.source = "local-corpus"
            return
        try:
            from azure.search.documents.aio import SearchClient

            self._credential = DefaultAzureCredential()
            self._client = SearchClient(
                endpoint=self._settings.search_endpoint,
                index_name=self._settings.search_index,
                credential=self._credential,
            )
            count = await self._client.get_document_count()
            if count == 0:
                raise RuntimeError("search index is empty")
            self.source = "azure-ai-search"
            logger.info("Azure AI Search ready with %d documents.", count)
        except Exception as exc:
            logger.warning("Search unavailable (%s); using local corpus.", exc)
            self.source = "local-corpus"
            await self._close_client()

    def _load_local_docs(self) -> None:
        directory = knowledge_dir()
        if self._local_docs or not directory.exists():
            return
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for index, chunk in enumerate(self._chunk(text)):
                self._local_docs.append(
                    {"id": f"{path.stem}-{index}", "title": path.stem, "content": chunk}
                )

    @staticmethod
    def _chunk(text: str, size: int = 1400) -> list[str]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 2 > size and current:
                chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}" if current else paragraph
        if current:
            chunks.append(current)
        return chunks

    async def _close_client(self) -> None:
        try:
            if self._client is not None:
                await self._client.close()
        except Exception:
            pass
        self._client = None
        try:
            if self._credential is not None:
                await self._credential.close()
        except Exception:
            pass
        self._credential = None

    async def close(self) -> None:
        await self._close_client()

    async def search(self, query: str, top: int = 4) -> list[dict[str, Any]]:
        if self._client is not None:
            try:
                results = await self._client.search(search_text=query, top=top)
                hits = []
                async for item in results:
                    hits.append(
                        {
                            "title": item.get("title", ""),
                            "content": (item.get("content") or "")[:1800],
                            "score": item.get("@search.score", 0.0),
                        }
                    )
                if hits:
                    return hits
            except Exception as exc:
                logger.warning("Search query failed (%s); using local corpus.", exc)

        return self._local_search(query, top)

    def _local_search(self, query: str, top: int) -> list[dict[str, Any]]:
        self._load_local_docs()
        terms = [t for t in re.findall(r"[a-z0-9\-]{3,}", query.lower())]
        scored: list[tuple[float, dict[str, str]]] = []
        for doc in self._local_docs:
            haystack = f"{doc['title']} {doc['content']}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score:
                scored.append((float(score), doc))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"title": doc["title"], "content": doc["content"][:1800], "score": score}
            for score, doc in scored[:top]
        ]


_knowledge: KnowledgeService | None = None


async def get_knowledge() -> KnowledgeService:
    global _knowledge
    if _knowledge is None:
        _knowledge = KnowledgeService()
        await _knowledge.initialize()
    return _knowledge
