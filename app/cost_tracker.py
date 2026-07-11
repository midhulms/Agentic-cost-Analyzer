# All request/cost persistence (SQLite). Author: Midhul MS (Cryzal)
import os
import sqlite3
import time
from contextlib import contextmanager

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    route TEXT NOT NULL,
    model_used TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'sparrow',
    agent_name TEXT NOT NULL DEFAULT 'Sparrow',
    complexity_score REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    token_count_method TEXT NOT NULL DEFAULT 'whitespace-approx',
    estimated_cost_usd REAL NOT NULL,
    baseline_cost_usd REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    prompt_preview TEXT NOT NULL
);
"""

# Columns added after the initial release. Kept as a list of
# (column, ddl) so upgrading an existing cost_router.db in place
# doesn't lose historical rows.
_MIGRATIONS = [
    ("agent_id", "ALTER TABLE requests ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'sparrow'"),
    ("agent_name", "ALTER TABLE requests ADD COLUMN agent_name TEXT NOT NULL DEFAULT 'Sparrow'"),
    ("token_count_method", "ALTER TABLE requests ADD COLUMN token_count_method TEXT NOT NULL DEFAULT 'whitespace-approx'"),
    # Nullable: old rows logged before accounts existed have no owner, and
    # stay visible in the GLOBAL stats endpoints (/v1/stats etc.). They
    # just never show up in a specific user's /v1/stats/me.
    ("user_id", "ALTER TABLE requests ADD COLUMN user_id INTEGER"),
]


@contextmanager
def get_conn():
    # Make sure the parent directory exists before opening the DB.
    db_dir = os.path.dirname(settings.db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(SCHEMA)
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
        for col, ddl in _MIGRATIONS:
            if col not in existing_cols:
                conn.execute(ddl)
        conn.commit()


def log_request(
    route: str,
    model_used: str,
    agent_id: str,
    agent_name: str,
    complexity_score: float,
    input_tokens: int,
    output_tokens: int,
    token_count_method: str,
    estimated_cost_usd: float,
    baseline_cost_usd: float,
    latency_ms: int,
    prompt: str,
    user_id: int | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO requests
               (ts, route, model_used, agent_id, agent_name, complexity_score,
                input_tokens, output_tokens, token_count_method,
                estimated_cost_usd, baseline_cost_usd, latency_ms, prompt_preview, user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                route,
                model_used,
                agent_id,
                agent_name,
                complexity_score,
                input_tokens,
                output_tokens,
                token_count_method,
                estimated_cost_usd,
                baseline_cost_usd,
                latency_ms,
                prompt[:120],
                user_id,
            ),
        )
        conn.commit()


def get_stats(user_id: int | None = None) -> dict:
    query = """SELECT
                 COUNT(*),
                 SUM(CASE WHEN route='cheap' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN route='frontier' THEN 1 ELSE 0 END),
                 COALESCE(SUM(estimated_cost_usd),0),
                 COALESCE(SUM(baseline_cost_usd),0),
                 COALESCE(AVG(latency_ms),0),
                 COALESCE(SUM(input_tokens),0),
                 COALESCE(SUM(output_tokens),0)
               FROM requests"""
    params: list = []
    if user_id is not None:
        query += " WHERE user_id = ?"
        params.append(user_id)

    with get_conn() as conn:
        row = conn.execute(query, params).fetchone()

    (total, cheap_n, frontier_n, total_cost, baseline_cost, avg_latency,
     total_in_tok, total_out_tok) = row
    total = total or 0
    cheap_n = cheap_n or 0
    frontier_n = frontier_n or 0
    total_in_tok = total_in_tok or 0
    total_out_tok = total_out_tok or 0
    savings = baseline_cost - total_cost
    savings_pct = (savings / baseline_cost * 100) if baseline_cost > 0 else 0.0

    return {
        "total_requests": total,
        "cheap_requests": cheap_n,
        "frontier_requests": frontier_n,
        "total_cost_usd": round(total_cost, 6),
        "baseline_cost_usd": round(baseline_cost, 6),
        "estimated_savings_usd": round(savings, 6),
        "estimated_savings_pct": round(savings_pct, 2),
        "avg_latency_ms": round(avg_latency, 1),
        "total_input_tokens": total_in_tok,
        "total_output_tokens": total_out_tok,
        "total_tokens": total_in_tok + total_out_tok,
    }


def get_recent(limit: int = 25, user_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM requests"
    params: list = []
    if user_id is not None:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_stats_by_agent(user_id: int | None = None) -> list[dict]:
    query = """SELECT
                 agent_id,
                 agent_name,
                 COUNT(*) AS requests,
                 COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                 COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                 COALESCE(AVG(estimated_cost_usd), 0) AS avg_cost_usd
               FROM requests"""
    params: list = []
    if user_id is not None:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " GROUP BY agent_id, agent_name ORDER BY total_cost_usd DESC"

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_stats_by_model(user_id: int | None = None) -> list[dict]:
    query = """SELECT
                 model_used,
                 COUNT(*) AS requests,
                 COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                 COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd,
                 COALESCE(AVG(estimated_cost_usd), 0) AS avg_cost_usd
               FROM requests"""
    params: list = []
    if user_id is not None:
        query += " WHERE user_id = ?"
        params.append(user_id)
    query += " GROUP BY model_used ORDER BY total_cost_usd DESC"

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_daily_consumption(days: int = 30, model: str | None = None, user_id: int | None = None) -> list[dict]:
    """One row per (day, model) over the last `days` days. This is what
    feeds the daily line graph. `ts` is stored as a unix timestamp, so we
    bucket it with SQLite's date()/unixepoch modifier rather than a second
    table."""
    cutoff = time.time() - days * 86400
    query = """
        SELECT
            date(ts, 'unixepoch') AS period,
            model_used,
            COUNT(*) AS requests,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd
        FROM requests
        WHERE ts >= ?
    """
    params: list = [cutoff]
    if model:
        query += " AND model_used = ?"
        params.append(model)
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    query += " GROUP BY period, model_used ORDER BY period ASC"

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_monthly_consumption(months: int = 12, model: str | None = None, user_id: int | None = None) -> list[dict]:
    """Same idea as get_daily_consumption, bucketed by calendar month
    (YYYY-MM) instead of day, for the monthly line graph."""
    cutoff = time.time() - months * 31 * 86400  # generous, over-inclusive window
    query = """
        SELECT
            strftime('%Y-%m', ts, 'unixepoch') AS period,
            model_used,
            COUNT(*) AS requests,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
            COALESCE(SUM(estimated_cost_usd), 0) AS total_cost_usd
        FROM requests
        WHERE ts >= ?
    """
    params: list = [cutoff]
    if model:
        query += " AND model_used = ?"
        params.append(model)
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    query += " GROUP BY period, model_used ORDER BY period ASC"

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
