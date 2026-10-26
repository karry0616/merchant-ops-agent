"""Conversation RAG — Milvus ANN retrieval of merchant's past customer conversations

Architecture:
  Primary: Milvus ANN search with metadata filters (stage, category)
  Fallback: keyword search over MySQL/JSON records

Covers four stages:
  - pre_sale:         pre-purchase (selling points, performance, value)
  - post_sale_address: post-purchase address changes/inquiries
  - post_sale_usage:   post-purchase usage instructions
  - after_sales:       after-sales service
"""

import re
import logging
from typing import Optional

from knowledge.conversation_records import get_records, STAGES
from knowledge.vector_store import search_similar
from config import RAG_TOP_K

logger = logging.getLogger(__name__)


def _build_search_text(record: dict) -> str:
    """Build searchable text from a conversation record"""
    parts = [
        record.get("customer_question", ""),
        record.get("merchant_response", ""),
        record.get("product", ""),
        record.get("category", ""),
        " ".join(record.get("tags", [])),
    ]
    return " ".join(p for p in parts if p)


def _vector_search(query: str, stage: str, category: str, k: int) -> list[dict]:
    """Milvus ANN search → fetch full records"""
    results = search_similar(query, stage=stage, category=category, k=k)
    if not results:
        return []

    record_ids = [rid for rid, _ in results]
    records = []
    for rid in record_ids:
        from knowledge.conversation_records import get_record
        r = get_record(rid)
        if r:
            records.append(r)
    return records


class ConversationRAG:
    """Semantic retriever for merchant's past conversation records

    Uses Milvus for fast ANN search with metadata filtering.
    Falls back to keyword search when vector store is unavailable.
    """

    def search_similar(
        self,
        query: str,
        stage: str = "",
        category: str = "",
        k: int = None,
    ) -> list[dict]:
        """Search past conversations semantically, optionally filtered by stage/category

        Args:
            query: The customer's question
            stage: Filter by stage (pre_sale/post_sale_address/post_sale_usage/after_sales)
            category: Filter by product category
            k: Number of results to return

        Returns:
            List of matching conversation records, scored by relevance
        """
        if k is None:
            k = RAG_TOP_K

        # Try vector search first
        vector_results = _vector_search(query, stage, category, k)
        if vector_results:
            return vector_results

        # Fallback: keyword search
        return self._keyword_search(query, stage, k)

    def _keyword_search(self, query: str, stage: str = "", k: int = 3) -> list[dict]:
        """Keyword search fallback"""
        query_lower = query.lower()
        records = get_records(stage=stage, limit=500)
        if not records:
            return []

        scored = []
        for r in records:
            score = 0.0
            text = _build_search_text(r).lower()

            keywords = set(query_lower.split())
            for kw in keywords:
                if kw in text:
                    score += 1.0
                for ch in kw:
                    if '\u4e00' <= ch <= '\u9fff' and ch in text:
                        score += 0.3
                # English word match
                for word in re.findall(r'[a-z0-9]+', kw):
                    if word in text:
                        score += 0.5

            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:k]]

    def format_context(self, query: str, stage: str = "", category: str = "") -> str:
        """Format similar past conversations as context for LLM prompt"""
        results = self.search_similar(query, stage=stage, category=category)
        if not results:
            return ""

        stage_label = STAGES.get(stage, "全部")
        ctx = f"【相似历史对话参考 - {stage_label}】\n"
        ctx += "以下是与当前问题相似的历史对话记录，供参考：\n\n"

        for i, r in enumerate(results, 1):
            tags = ", ".join(r.get("tags", [])) if r.get("tags") else ""
            product_info = f" [{r.get('product', '')}]" if r.get("product") else ""
            outcome = f" → {r['outcome']}" if r.get("outcome") else ""

            ctx += f"--- 案例{i}{product_info}{outcome} ---\n"
            ctx += f"顾客：{r['customer_question']}\n"
            ctx += f"商家：{r['merchant_response']}\n"
            if tags:
                ctx += f"标签：{tags}\n"
            ctx += "\n"

        ctx += "注意：以上是历史对话记录，请参考其中的回答方式和有效信息，结合当前问题给出合适的回复。"
        return ctx


# Global singleton
_rag = None


def get_conversation_rag() -> ConversationRAG:
    global _rag
    if _rag is None:
        _rag = ConversationRAG()
    return _rag
