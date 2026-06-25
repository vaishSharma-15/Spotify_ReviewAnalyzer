"""Phase 2 runner — structure raw_reviews into structured_reviews via Groq.

Design (per PhaseWiseArchitecture.md + EdgeCases.md):
  - Batch over raw_reviews not yet structured at the current MODEL_VERSION (idempotent).
  - One Groq chat-completion per review in JSON-object mode.
  - Validate + coerce against the controlled vocabularies (off-vocab theme -> 'other',
    bad segments dropped, severity clamped to 1-5); on hard failure retry then quarantine.
  - Store model_version + structured_at for auditability.

Usage:
  python -m structuring.structure --limit 50      # structure up to 50 new rows
  python -m structuring.structure --all           # structure everything pending
  python -m structuring.structure --status        # progress report
  python -m structuring.structure --redo-failed   # retry quarantined rows
  python -m structuring.structure --model llama-3.1-8b-instant
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path


class DailyLimitReached(Exception):
    """Groq per-day token cap (TPD) hit — stop the run; remaining rows stay pending."""


_RETRY_RE = re.compile(r"try again in ([\d.]+)s")

from ingestion.db import DEFAULT_DB_PATH
from . import schema as S

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

STRUCTURED_SCHEMA = """
CREATE TABLE IF NOT EXISTS structured_reviews (
    review_id        INTEGER PRIMARY KEY,
    theme            TEXT,
    sentiment        TEXT,
    job_to_be_done   TEXT,
    frustration      TEXT,
    user_segment     TEXT,    -- JSON array of segment ids
    feature_mentioned TEXT,
    severity_score   INTEGER,
    status           TEXT NOT NULL,   -- 'ok' | 'failed'
    error            TEXT,
    model_version    TEXT NOT NULL,
    structured_at    TEXT NOT NULL,
    FOREIGN KEY (review_id) REFERENCES raw_reviews(id)
);
CREATE INDEX IF NOT EXISTS idx_structured_theme   ON structured_reviews(theme);
CREATE INDEX IF NOT EXISTS idx_structured_status  ON structured_reviews(status);
"""

MAX_RETRIES = 2


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(STRUCTURED_SCHEMA)


def pending_rows(conn, model_version: str, limit: int | None, redo_failed: bool):
    q = """
        SELECT r.id, r.source, r.title, r.body
        FROM raw_reviews r
        LEFT JOIN structured_reviews s
          ON s.review_id = r.id AND s.model_version = ?
        WHERE s.review_id IS NULL
           OR (s.status = 'failed' AND ?)
        ORDER BY r.id
    """
    rows = conn.execute(q, (model_version, 1 if redo_failed else 0)).fetchall()
    return rows[:limit] if limit else rows


def validate(raw: dict) -> dict:
    """Coerce model output into the controlled vocabularies (edge cases S2/S3/S10)."""
    theme = raw.get("theme")
    if theme not in S.THEMES:
        theme = "other"

    sentiment = raw.get("sentiment")
    if sentiment not in S.SENTIMENTS:
        sentiment = "neutral"

    segs = raw.get("user_segment")
    if isinstance(segs, str):
        segs = [segs]
    if not isinstance(segs, list):
        segs = []
    segs = [s for s in segs if s in S.USER_SEGMENTS]
    if not segs:
        segs = ["unspecified"]

    sev = raw.get("severity_score", 1)
    try:
        sev = int(sev)
    except (TypeError, ValueError):
        sev = 1
    sev = max(1, min(5, sev))

    return {
        "theme": theme,
        "sentiment": sentiment,
        "job_to_be_done": str(raw.get("job_to_be_done") or "")[:500],
        "frustration": str(raw.get("frustration") or "")[:500],
        "user_segment": segs,
        "feature_mentioned": str(raw.get("feature_mentioned") or "")[:200],
        "severity_score": sev,
    }


def _repair_json(text: str) -> dict | None:
    """Best-effort recovery of nearly-valid JSON from the model.

    Handles the common failure where the model emits a controlled-vocab field
    fine but leaves unescaped double-quotes inside a free-text value (e.g.
    frustration: ""blessed by the algorithm""), which breaks json.loads.
    We pull each known field out by regex rather than trusting the braces.
    """
    out: dict = {}
    # Single-token / array fields are safe to grab with a tolerant regex.
    for key in ("theme", "sentiment", "feature_mentioned"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
        if m:
            out[key] = m.group(1)
    m = re.search(r'"user_segment"\s*:\s*\[([^\]]*)\]', text)
    if m:
        out["user_segment"] = re.findall(r'"([^"]+)"', m.group(1))
    m = re.search(r'"severity_score"\s*:\s*(\d+)', text)
    if m:
        out["severity_score"] = int(m.group(1))
    # Free-text fields: take everything up to the next `",\n  "key"` boundary,
    # collapsing any stray inner quotes.
    for key in ("job_to_be_done", "frustration"):
        m = re.search(rf'"{key}"\s*:\s*"(.*?)"\s*[,}}]\s*(?:"|$)', text, re.S)
        if m:
            out[key] = m.group(1).replace('"', "'").strip()
    return out if out.get("theme") else None


def structure_one(client, model: str, review: sqlite3.Row) -> dict:
    title = review["title"] or ""
    body = review["body"] or ""
    user_text = (f"Title: {title}\n" if title else "") + f"Review: {body}"

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": S.SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
            )
            text = resp.choices[0].message.content or ""
            try:
                return validate(json.loads(text))
            except json.JSONDecodeError:
                repaired = _repair_json(text)
                if repaired:
                    return validate(repaired)
                raise
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            # Daily token cap (TPD): can't recover today — abort the whole run.
            if "429" in msg and ("per day" in msg or "TPD" in msg):
                raise DailyLimitReached(msg) from exc
            # Model returned invalid JSON (400 json_validate_failed): try to
            # salvage the partial output from the error payload before retrying.
            if "json_validate_failed" in msg:
                m = re.search(r"'failed_generation':\s*'(.*)'\s*}", msg, re.S)
                if m:
                    salvaged = _repair_json(m.group(1).encode().decode("unicode_escape"))
                    if salvaged:
                        return validate(salvaged)
            # Per-minute rate limit (RPM/TPM): honor the suggested wait and retry,
            # without consuming a quarantine attempt.
            if "429" in msg:
                m = _RETRY_RE.search(msg)
                wait = min(float(m.group(1)) + 1, 65) if m else 20
                print(f"    rate-limited; waiting {wait:.0f}s…")
                time.sleep(wait)
                continue
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed after {MAX_RETRIES + 1} attempts: {last_err}")


def upsert_result(conn, review_id, data, error, model_version) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if data is not None:
        conn.execute(
            """INSERT OR REPLACE INTO structured_reviews
               (review_id, theme, sentiment, job_to_be_done, frustration,
                user_segment, feature_mentioned, severity_score, status, error,
                model_version, structured_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (review_id, data["theme"], data["sentiment"], data["job_to_be_done"],
             data["frustration"], json.dumps(data["user_segment"]),
             data["feature_mentioned"], data["severity_score"], "ok", None,
             model_version, now),
        )
    else:
        conn.execute(
            """INSERT OR REPLACE INTO structured_reviews
               (review_id, status, error, model_version, structured_at)
               VALUES (?, 'failed', ?, ?, ?)""",
            (review_id, (error or "")[:500], model_version, now),
        )
    conn.commit()


def print_status(conn, model_version: str) -> None:
    total = conn.execute("SELECT COUNT(*) FROM raw_reviews").fetchone()[0]
    ok = conn.execute("SELECT COUNT(*) FROM structured_reviews WHERE status='ok' AND model_version=?",
                      (model_version,)).fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM structured_reviews WHERE status='failed' AND model_version=?",
                          (model_version,)).fetchone()[0]
    print(f"model_version: {model_version}")
    print(f"  raw_reviews     : {total}")
    print(f"  structured (ok) : {ok}")
    print(f"  failed          : {failed}")
    print(f"  pending         : {total - ok - failed}")
    if ok:
        print("\n  theme distribution (structured):")
        for row in conn.execute("SELECT theme, COUNT(*) n FROM structured_reviews "
                                "WHERE status='ok' GROUP BY theme ORDER BY n DESC"):
            print(f"    {row[0]:30s} {row[1]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 — structure reviews via Groq")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--redo-failed", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--model", default=os.environ.get("GROQ_MODEL", S.MODEL))
    args = ap.parse_args(argv)

    model = args.model
    model_version = f"{model}/schema-{S.SCHEMA_VERSION}"

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    if args.status:
        print_status(conn, model_version)
        return 0

    try:
        import groq
    except ImportError:
        print("groq SDK not installed — run: pip install groq")
        return 1
    if not os.environ.get("GROQ_API_KEY"):
        print("No GROQ_API_KEY set. Add it to .env, then re-run.")
        return 1

    client = groq.Groq()
    limit = None if args.all else args.limit
    rows = pending_rows(conn, model_version, limit, args.redo_failed)
    if not rows:
        print("Nothing to structure — all rows are up to date.")
        return 0

    print(f"Structuring {len(rows)} reviews with {model_version}…")
    ok = failed = 0
    for i, review in enumerate(rows, 1):
        try:
            data = structure_one(client, model, review)
            upsert_result(conn, review["id"], data, None, model_version)
            ok += 1
        except DailyLimitReached:
            print(f"\nDaily token cap reached after {ok} new rows this run. "
                  f"Remaining rows stay pending — re-run tomorrow to resume.")
            break
        except Exception as exc:  # noqa: BLE001 - quarantine, keep going
            upsert_result(conn, review["id"], None, str(exc), model_version)
            failed += 1
            print(f"  [{review['id']}] quarantined: {exc}")
        if i % 25 == 0:
            print(f"  …{i}/{len(rows)} (ok={ok} failed={failed})")

    print(f"\nDone. ok={ok} failed={failed}.\n")
    print_status(conn, model_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
