"""Vector Store — Milvus ANN search for conversation embeddings with linear-scan fallback

Architecture:
  Primary: Milvus (Docker) for fast ANN search with metadata filtering
  Fallback: in-memory embedding cache + linear cosine similarity scan
"""

import os
import time
import logging
import threading
from typing import Optional

import numpy as np

from knowledge.embedding import get_embedding, get_embeddings_batch, cosine_similarity

logger = logging.getLogger(__name__)

# ── Milvus config from environment ──
MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))
COLLECTION_NAME = "conversation_embeddings"
EMBED_DIM = 1024  # bge-m3 output dimension

# Global state
_milvus_available = None  # None = unchecked, True/False after probe
_collection = None
_lock = threading.Lock()

# ── Fallback in-memory cache ──
_fallback_cache: dict[int, list[float]] = {}  # record_id -> embedding
_fallback_lock = threading.Lock()


# ═════════════════════════════════════════════════
#  Milvus connection & collection management
# ═════════════════════════════════════════════════

def _probe_milvus() -> bool:
    """Check if Milvus is reachable"""
    global _milvus_available
    if _milvus_available is not None:
        return _milvus_available

    if not MILVUS_HOST:
        logger.info("MILVUS_HOST not configured, using fallback vector search")
        _milvus_available = False
        return False

    try:
        from pymilvus import connections
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        connections.disconnect(alias="default")
        _milvus_available = True
        logger.info(f"Milvus connected at {MILVUS_HOST}:{MILVUS_PORT}")
        return True
    except Exception as e:
        logger.warning(f"Milvus unavailable ({e}), using fallback vector search")
        _milvus_available = False
        return False


def _get_connection():
    """Get or create Milvus connection"""
    from pymilvus import connections
    try:
        connections.connect(alias="default", host=MILVUS_HOST, port=MILVUS_PORT)
        return True
    except Exception:
        return False


def _ensure_collection():
    """Create collection + index if not exists"""
    global _collection
    if _collection is not None:
        return True

    from pymilvus import Collection, CollectionSchema, FieldSchema, DataType, utility

    if not _get_connection():
        return False

    with _lock:
        # Double-check after acquiring lock
        if _collection is not None:
            return True

        try:
            if utility.has_collection(COLLECTION_NAME):
                _collection = Collection(COLLECTION_NAME)
                logger.info(f"Milvus collection '{COLLECTION_NAME}' loaded")
                return True
        except Exception as e:
            logger.warning(f"Milvus collection check failed: {e}")
            return False

        # Create collection
        try:
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="record_id", dtype=DataType.INT64),
                FieldSchema(name="stage", dtype=DataType.VARCHAR, max_length=50),
                FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBED_DIM),
            ]
            schema = CollectionSchema(fields, description="Conversation record embeddings")
            _collection = Collection(COLLECTION_NAME, schema)

            # Create IVF_FLAT index for ANN search
            index_params = {
                "metric_type": "IP",  # inner product ≈ cosine for normalized vectors
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            }
            _collection.create_index("embedding", index_params)
            _collection.load()

            logger.info(f"Milvus collection '{COLLECTION_NAME}' created with IVF_FLAT index")
            return True

        except Exception as e:
            logger.error(f"Milvus collection creation failed: {e}")
            return False


# ═════════════════════════════════════════════════
#  Public API
# ═════════════════════════════════════════════════

def _needs_probe():
    """Check if probe is needed and run it"""
    if _milvus_available is None:
        _probe_milvus()
    return _milvus_available


def store_embedding(record_id: int, stage: str, category: str, text: str) -> bool:
    """Compute and store embedding for a conversation record

    Falls back to in-memory cache if Milvus is unavailable.
    """
    emb = get_embedding(text)
    if not emb:
        return False

    # Try Milvus first
    if _needs_probe() and _ensure_collection():
        try:
            from pymilvus import Collection
            col = Collection(COLLECTION_NAME)
            col.insert([
                [record_id],
                [stage],
                [category],
                [emb],
            ])
            col.flush()
            return True
        except Exception as e:
            logger.warning(f"Milvus insert failed, using fallback: {e}")

    # Fallback: in-memory cache
    with _fallback_lock:
        _fallback_cache[record_id] = emb
    return True


def search_similar(
    query: str,
    stage: str = "",
    category: str = "",
    k: int = 5,
) -> list[tuple[int, float]]:
    """Search for similar conversation records by semantic similarity

    Args:
        query: Search text
        stage: Filter by stage (optional)
        category: Filter by category (optional)
        k: Number of results

    Returns:
        List of (record_id, similarity_score) tuples
    """
    query_emb = get_embedding(query)
    if not query_emb:
        return []

    query_norm = np.array(query_emb, dtype=np.float64)
    query_norm = query_norm / (np.linalg.norm(query_norm) + 1e-12)

    # Milvus search
    if _needs_probe() and _ensure_collection():
        try:
            from pymilvus import Collection, AnnSearchRequest, RRFRanker
            from pymilvus import WeightedRanker

            col = Collection(COLLECTION_NAME)
            col.load()

            # Build filter expression
            expr_parts = []
            if stage:
                expr_parts.append(f'stage == "{stage}"')
            if category:
                expr_parts.append(f'category == "{category}"')
            expr = " and ".join(expr_parts) if expr_parts else None

            search_params = {
                "metric_type": "IP",
                "params": {"nprobe": 16},
            }

            results = col.search(
                data=[query_emb],
                anns_field="embedding",
                param=search_params,
                limit=k,
                expr=expr,
                output_fields=["record_id"],
            )

            hits = results[0]
            return [(int(hit.entity.get("record_id")), hit.score) for hit in hits]

        except Exception as e:
            logger.warning(f"Milvus search failed, using fallback: {e}")

    # Fallback: linear scan over in-memory cache
    return _fallback_search(query_norm, stage, category, k)


def _fallback_search(
    query_norm: np.ndarray,
    stage: str = "",
    category: str = "",
    k: int = 5,
) -> list[tuple[int, float]]:
    """Linear scan over in-memory embedding cache"""
    from knowledge.conversation_records import get_records

    with _fallback_lock:
        if not _fallback_cache:
            return []

        # Filter by stage/category if needed
        if stage or category:
            records = get_records(stage=stage, category=category, limit=5000)
            candidate_ids = {r["id"] for r in records}
        else:
            candidate_ids = set(_fallback_cache.keys())

    scores = []
    with _fallback_lock:
        for rid, emb in _fallback_cache.items():
            if rid not in candidate_ids:
                continue
            vec = np.array(emb, dtype=np.float64)
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            vec = vec / norm
            score = float(np.dot(query_norm, vec))
            scores.append((score, rid))

    scores.sort(key=lambda x: x[0], reverse=True)
    return [(rid, score) for score, rid in scores[:k]]


def delete_embedding(record_id: int) -> bool:
    """Delete embedding for a record"""
    if _needs_probe() and _ensure_collection():
        try:
            from pymilvus import Collection
            col = Collection(COLLECTION_NAME)
            col.delete(f"record_id in [{record_id}]")
            return True
        except Exception as e:
            logger.warning(f"Milvus delete failed: {e}")

    with _fallback_lock:
        _fallback_cache.pop(record_id, None)
    return True


def rebuild_index(record_data: list[tuple[int, str, str, str]]) -> tuple[int, int]:
    """Batch index conversation records into vector store

    Args:
        record_data: list of (record_id, stage, category, search_text)

    Returns:
        (success_count, fail_count)
    """
    success = 0
    fail = 0

    # Try Milvus batch insert
    if _needs_probe() and _ensure_collection():  # fmt: skip
        try:
            embeddings = get_embeddings_batch([d[3] for d in record_data])
            ids, stages, cats, valid_embs = [], [], [], []
            for (rid, stage, cat, _), emb in zip(record_data, embeddings):
                if emb:
                    ids.append(rid)
                    stages.append(stage)
                    cats.append(cat)
                    valid_embs.append(emb)
                    success += 1
                else:
                    fail += 1

            if ids:
                from pymilvus import Collection
                col = Collection(COLLECTION_NAME)
                col.insert([ids, stages, cats, valid_embs])
                col.flush()
            return success, fail
        except Exception as e:
            logger.warning(f"Milvus batch insert failed, using fallback: {e}")

    # Fallback: cache embeddings in memory
    texts = [d[3] for d in record_data]
    embeddings = get_embeddings_batch(texts)
    with _fallback_lock:
        for (rid, _, _, _), emb in zip(record_data, embeddings):
            if emb:
                _fallback_cache[rid] = emb
                success += 1
            else:
                fail += 1
    return success, fail


def clear_fallback_cache():
    """Clear the in-memory fallback cache"""
    with _fallback_lock:
        _fallback_cache.clear()


def is_milvus_available() -> bool:
    if _milvus_available is None:
        _probe_milvus()
    return _milvus_available is True
