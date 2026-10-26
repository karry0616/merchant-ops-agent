"""Conversation Records Manager — MySQL primary, JSON file fallback

Stages:
  - pre_sale:         售前咨询（卖点/性能/性价比）
  - post_sale_address: 买后地址修改/查询
  - post_sale_usage:   买后使用说明
  - after_sales:       商品售后
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional

from knowledge.db import get_connection, _probe_mysql as probe_mysql

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
JSON_FILE = os.path.join(DATA_DIR, "conversation_records.json")

STAGES = {
    "pre_sale": "售前咨询（卖点/性能/性价比）",
    "post_sale_address": "买后地址修改/查询",
    "post_sale_usage": "买后使用说明",
    "after_sales": "商品售后",
}


def _mysql_available() -> bool:
    """Check if MySQL backend is available"""
    return probe_mysql()


# ═════════════════════════════════════════════════
#  JSON fallback helpers
# ═════════════════════════════════════════════════

def _json_load() -> list[dict]:
    if os.path.exists(JSON_FILE):
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"JSON load failed: {e}")
            return []
    return []


def _json_save(records: list[dict]) -> bool:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"JSON save failed: {e}")
        return False


# ═════════════════════════════════════════════════
#  MySQL CRUD
# ═════════════════════════════════════════════════

def _mysql_add(stage: str, question: str, response: str,
               product: str, category: str, tags: str,
               outcome: str) -> Optional[dict]:
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO conversation_records
                   (stage, customer_question, merchant_response, product, category, tags, outcome)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (stage, question, response, product, category, tags, outcome),
            )
            record_id = cur.lastrowid
        return {
            "id": record_id,
            "stage": stage,
            "customer_question": question,
            "merchant_response": response,
            "product": product,
            "category": category,
            "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
            "outcome": outcome,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        logger.error(f"MySQL add failed: {e}")
        return None


def _mysql_get(record_id: int) -> Optional[dict]:
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM conversation_records WHERE id = %s", (record_id,))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_dict(row)
    except Exception as e:
        logger.error(f"MySQL get failed: {e}")
        return None


def _mysql_search(stage: str = "", keyword: str = "",
                  product: str = "", category: str = "",
                  limit: int = 50) -> list[dict]:
    conn = get_connection()
    if not conn:
        return []
    try:
        where = []
        params = []

        if stage:
            where.append("stage = %s")
            params.append(stage)
        if keyword:
            where.append("(customer_question LIKE %s OR merchant_response LIKE %s OR tags LIKE %s)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])
        if product:
            where.append("product LIKE %s")
            params.append(f"%{product}%")
        if category:
            where.append("category LIKE %s")
            params.append(f"%{category}%")

        sql = "SELECT * FROM conversation_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"MySQL search failed: {e}")
        return []


def _mysql_update(record_id: int, **kwargs) -> bool:
    conn = get_connection()
    if not conn:
        return False
    allowed = {"stage", "customer_question", "merchant_response",
               "product", "category", "tags", "outcome"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return False
    try:
        with conn.cursor() as cur:
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            values = list(updates.values()) + [record_id]
            cur.execute(f"UPDATE conversation_records SET {set_clause} WHERE id = %s", values)
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"MySQL update failed: {e}")
        return False


def _mysql_delete(record_id: int) -> bool:
    conn = get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversation_records WHERE id = %s", (record_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"MySQL delete failed: {e}")
        return False


def _mysql_count() -> dict:
    conn = get_connection()
    if not conn:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT stage, COUNT(*) as cnt FROM conversation_records
                GROUP BY stage WITH ROLLUP
            """)
            rows = cur.fetchall()
            counts = {s: 0 for s in STAGES}
            counts["total"] = 0
            for r in rows:
                if r["stage"] is None:
                    counts["total"] = r["cnt"]
                elif r["stage"] in counts:
                    counts[r["stage"]] = r["cnt"]
            return counts
    except Exception as e:
        logger.error(f"MySQL count failed: {e}")
        return {}


def _mysql_get_all_ids() -> list[int]:
    """Get all record IDs (for Milvus indexing)"""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM conversation_records ORDER BY id")
            return [r["id"] for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"MySQL get_all_ids failed: {e}")
        return []


def _row_to_dict(row: dict) -> dict:
    """Convert MySQL row to standard dict format"""
    tags_str = row.get("tags", "") or ""
    return {
        "id": row["id"],
        "stage": row["stage"],
        "customer_question": row["customer_question"],
        "merchant_response": row["merchant_response"],
        "product": row.get("product", "") or "",
        "category": row.get("category", "") or "",
        "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
        "outcome": row.get("outcome", "") or "",
        "created_at": row.get("created_at", "").strftime("%Y-%m-%d %H:%M") if row.get("created_at") else "",
    }


# ═════════════════════════════════════════════════
#  JSON CRUD (fallback)
# ═════════════════════════════════════════════════

def _json_add(stage: str, question: str, response: str,
              product: str, category: str, tags: str,
              outcome: str) -> Optional[dict]:
    records = _json_load()
    next_id = max((r.get("id", 0) for r in records), default=0) + 1
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    record = {
        "id": next_id,
        "stage": stage,
        "customer_question": question,
        "merchant_response": response,
        "product": product,
        "category": category,
        "tags": tag_list,
        "outcome": outcome,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    records.append(record)
    _json_save(records)
    return record


def _json_get(record_id: int) -> Optional[dict]:
    records = _json_load()
    for r in records:
        if r.get("id") == record_id:
            return r
    return None


def _json_search(stage: str = "", keyword: str = "",
                 product: str = "", category: str = "",
                 limit: int = 50) -> list[dict]:
    records = _json_load()
    results = []
    for r in records:
        if stage and r.get("stage") != stage:
            continue
        if keyword:
            kw = keyword.lower()
            if (kw not in r.get("customer_question", "").lower()
                    and kw not in r.get("merchant_response", "").lower()
                    and not any(kw in t.lower() for t in r.get("tags", []))):
                continue
        if product and product.lower() not in r.get("product", "").lower():
            continue
        if category and category.lower() not in r.get("category", "").lower():
            continue
        results.append(r)
    results.sort(key=lambda x: x.get("id", 0), reverse=True)
    return results[:limit]


def _json_update(record_id: int, **kwargs) -> bool:
    records = _json_load()
    for r in records:
        if r.get("id") == record_id:
            for k, v in kwargs.items():
                if k == "tags" and isinstance(v, str):
                    v = [t.strip() for t in v.split(",") if t.strip()]
                if v is not None and k in ("stage", "customer_question", "merchant_response",
                                           "product", "category", "tags", "outcome"):
                    r[k] = v
            return _json_save(records)
    return False


def _json_delete(record_id: int) -> bool:
    records = _json_load()
    before = len(records)
    records = [r for r in records if r.get("id") != record_id]
    if len(records) < before:
        return _json_save(records)
    return False


def _json_count() -> dict:
    records = _json_load()
    counts = {s: 0 for s in STAGES}
    counts["total"] = len(records)
    for r in records:
        s = r.get("stage", "")
        if s in counts:
            counts[s] += 1
    return counts


def _json_get_all_ids() -> list[int]:
    records = _json_load()
    return sorted(r["id"] for r in records)


# ═════════════════════════════════════════════════
#  Public API (auto-selects MySQL or JSON)
# ═════════════════════════════════════════════════

def add_record(
    stage: str,
    customer_question: str,
    merchant_response: str,
    product: str = "",
    category: str = "",
    tags: str = "",
    outcome: str = "",
) -> Optional[dict]:
    """Add a conversation record"""
    if stage not in STAGES:
        logger.warning(f"Unknown stage: {stage}, defaulting to pre_sale")
        stage = "pre_sale"

    question = customer_question.strip()
    response = merchant_response.strip()
    if not question or not response:
        logger.error("customer_question and merchant_response cannot be empty")
        return None

    if _mysql_available():
        result = _mysql_add(stage, question, response,
                            product.strip(), category.strip(),
                            tags, outcome.strip())
        if result:
            return result
        # MySQL failed, fall through to JSON

    return _json_add(stage, question, response,
                     product.strip(), category.strip(),
                     tags, outcome.strip())


def get_record(record_id: int) -> Optional[dict]:
    """Get a single record by ID"""
    if _mysql_available():
        r = _mysql_get(record_id)
        if r:
            return r
    return _json_get(record_id)


def get_records(
    stage: str = "",
    keyword: str = "",
    product: str = "",
    category: str = "",
    limit: int = 50,
) -> list[dict]:
    """Search conversation records by various filters"""
    if _mysql_available():
        return _mysql_search(stage, keyword, product, category, limit)
    return _json_search(stage, keyword, product, category, limit)


def update_record(record_id: int, **kwargs) -> bool:
    """Update a conversation record"""
    if _mysql_available():
        if _mysql_update(record_id, **kwargs):
            return True
    return _json_update(record_id, **kwargs)


def delete_record(record_id: int) -> bool:
    """Delete a conversation record"""
    if _mysql_available():
        if _mysql_delete(record_id):
            return True
    return _json_delete(record_id)


def get_record_count() -> dict:
    """Get count statistics by stage"""
    if _mysql_available():
        return _mysql_count() or _json_count()
    return _json_count()


def get_all_record_ids() -> list[int]:
    """Get all record IDs (for building or rebuilding Milvus index)"""
    if _mysql_available():
        return _mysql_get_all_ids()
    return _json_get_all_ids()


def import_records(records: list[dict]) -> tuple[int, int]:
    """Import multiple records. Returns (success, fail) counts"""
    success = 0
    fail = 0
    for r in records:
        stage = r.get("stage", "")
        question = r.get("customer_question", "").strip()
        response = r.get("merchant_response", "").strip()
        if not question or not response or stage not in STAGES:
            fail += 1
            continue

        tags = r.get("tags", [])
        if isinstance(tags, list):
            tags = ",".join(tags)

        result = add_record(
            stage=stage,
            customer_question=question,
            merchant_response=response,
            product=r.get("product", ""),
            category=r.get("category", ""),
            tags=tags,
            outcome=r.get("outcome", ""),
        )
        if result:
            success += 1
        else:
            fail += 1

    return success, fail
