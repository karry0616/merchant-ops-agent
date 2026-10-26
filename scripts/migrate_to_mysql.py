"""Migrate conversation records from JSON to MySQL and rebuild Milvus index

Usage:
    python scripts/migrate_to_mysql.py          # migrate data + reindex
    python scripts/migrate_to_mysql.py --reindex  # only rebuild Milvus from existing MySQL data
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.db import _probe_mysql as probe_mysql
from knowledge.conversation_rag import _build_search_text


def migrate_json_to_mysql() -> int:
    """Migrate all records from JSON to MySQL. Returns count migrated."""
    from knowledge.conversation_records import _json_load, _mysql_add, STAGES

    records = _json_load()
    if not records:
        print("No JSON records found to migrate.")
        return 0

    migrated = 0
    skipped = 0
    for r in records:
        stage = r.get("stage", "")
        if stage not in STAGES:
            skipped += 1
            continue
        result = _mysql_add(
            stage=stage,
            question=r.get("customer_question", "").strip(),
            response=r.get("merchant_response", "").strip(),
            product=r.get("product", "").strip(),
            category=r.get("category", "").strip(),
            tags=",".join(r.get("tags", [])) if isinstance(r.get("tags"), list) else r.get("tags", ""),
            outcome=r.get("outcome", "").strip(),
        )
        if result:
            migrated += 1
        else:
            skipped += 1

    print(f"Migration complete: {migrated} migrated, {skipped} skipped")
    return migrated


def reindex_milvus() -> tuple[int, int]:
    """Rebuild Milvus index from all records in MySQL/JSON"""
    from knowledge.conversation_records import get_records, get_all_record_ids
    from knowledge.vector_store import rebuild_index, clear_fallback_cache

    records = get_records(limit=10000)
    if not records:
        print("No records found to index.")
        return 0, 0

    record_data = []
    for r in records:
        text = _build_search_text(r)
        if text:
            record_data.append((
                r["id"],
                r.get("stage", ""),
                r.get("category", ""),
                text,
            ))

    clear_fallback_cache()
    success, fail = rebuild_index(record_data)
    print(f"Milvus indexing: {success} success, {fail} failed (total {len(record_data)} records)")
    return success, fail


def main():
    parser = argparse.ArgumentParser(description="Migrate data to MySQL + Milvus")
    parser.add_argument("--reindex", action="store_true", help="Only rebuild Milvus index")
    args = parser.parse_args()

    if not probe_mysql():
        print("MySQL is not available. Running in JSON-only mode.")
        print("Start the docker stack first: docker compose up -d")

    if not args.reindex:
        migrated = migrate_json_to_mysql()
        if migrated > 0:
            print("Migration done. Now rebuilding Milvus index...")
        else:
            print("Skipping Milvus reindex (no new data).")

    reindex_milvus()
    print("Done.")


if __name__ == "__main__":
    main()
