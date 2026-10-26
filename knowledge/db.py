"""Database connection manager — MySQL primary, JSON fallback"""

import os
import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── MySQL config from environment ──
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3307"))
MYSQL_USER = os.environ.get("MYSQL_USER", "merchant")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "merchant_pass_2024")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "merchant_agent")

# Connection pool (lazy init)
_conn = None
_use_mysql = None  # None = not checked yet, True/False after probe


def _probe_mysql() -> bool:
    """Probe MySQL availability, cache result"""
    global _use_mysql
    if _use_mysql is not None:
        return _use_mysql

    if not MYSQL_HOST:
        logger.info("MYSQL_HOST not configured, using JSON fallback")
        _use_mysql = False
        return False

    try:
        import pymysql
        conn = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            connect_timeout=3,
            charset="utf8mb4",
        )
        conn.close()
        _use_mysql = True
        logger.info(f"MySQL connected at {MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}")
        return True
    except Exception as e:
        logger.warning(f"MySQL unavailable ({e}), using JSON fallback")
        _use_mysql = False
        return False


def get_connection():
    """Get MySQL connection (lazy init with retry)"""
    global _conn
    if not _probe_mysql():
        return None
    if _conn is None or not _is_connected():
        try:
            import pymysql
            _conn = pymysql.connect(
                host=MYSQL_HOST, port=MYSQL_PORT,
                user=MYSQL_USER, password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
                connect_timeout=5,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
            _conn.autocommit(True)
        except Exception as e:
            logger.error(f"MySQL connection failed: {e}")
            return None
    return _conn


def _is_connected() -> bool:
    if _conn is None:
        return False
    try:
        _conn.ping(reconnect=False)
        return True
    except Exception:
        return False


def close():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


def reset_probe():
    """Force re-probe on next access (e.g. after MySQL becomes available)"""
    global _use_mysql
    _use_mysql = None
    close()
