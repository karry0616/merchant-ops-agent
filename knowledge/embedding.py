"""Embedding service — Ollama bge-m3 for semantic vectors"""

import logging
import time
import numpy as np
import httpx
from typing import Optional
from config import OLLAMA_BASE

logger = logging.getLogger(__name__)

EMBED_MODEL = "bge-m3"

_http_client = httpx.Client(timeout=60)

# 熔断：Ollama 不可用时短时间内直接跳过，避免每次请求重试 3 次白白等待
_DOWN_COOLDOWN = 60.0
_down_until = 0.0


def _is_down() -> bool:
    return time.time() < _down_until


def _mark_down() -> None:
    global _down_until
    _down_until = time.time() + _DOWN_COOLDOWN


def get_embedding(text: str, model: str = EMBED_MODEL) -> Optional[list[float]]:
    """Get embedding vector for a single text (with retry)"""
    if _is_down():
        return None
    for attempt in range(3):
        try:
            resp = _http_client.post(
                f"{OLLAMA_BASE}/api/embed",
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
            return embeddings[0] if embeddings else None
        except Exception as e:
            logger.warning(f"Embedding failed attempt={attempt+1}/3: {e}")
            _mark_down()
            if attempt < 2:
                time.sleep(0.3)
    return None

def get_embeddings_batch(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Get embedding vectors for a batch of texts"""
    if not texts:
        return []
    if _is_down():
        return []
    try:
        resp = _http_client.post(
            f"{OLLAMA_BASE}/api/embed",
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embeddings", [])
    except Exception as e:
        logger.warning(f"Batch embedding failed: {e}")
        _mark_down()
        return []

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity"""
    a = np.array(a, dtype=np.float64)
    b = np.array(b, dtype=np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))

def rank_by_similarity(query_emb: list[float], candidates: list[tuple[str, list[float]]]) -> list[tuple[int, float]]:
    """Rank candidates by cosine similarity, returns [(index, score), ...]"""
    scores = []
    for idx, (_, cand_emb) in enumerate(candidates):
        score = cosine_similarity(query_emb, cand_emb)
        scores.append((idx, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores
