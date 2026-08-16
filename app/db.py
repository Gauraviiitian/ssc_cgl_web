from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

DATABASE_URL = os.environ["DATABASE_URL"]

_pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)


def _checked_out_conn():
    """Neon (serverless Postgres) can silently close a pooled connection
    while it sits idle; psycopg2's pool doesn't validate before handing one
    out. Probe with a trivial query and discard+retry once rather than let
    every caller's first real query hit "SSL connection has been closed
    unexpectedly"."""
    for attempt in range(2):
        conn = _pool.getconn()
        try:
            with conn.cursor() as probe:
                probe.execute("SELECT 1")
            return conn
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            _pool.putconn(conn, close=True)
            if attempt == 1:
                raise


@contextmanager
def get_cursor(commit: bool = False):
    conn = _checked_out_conn()
    cur = None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    except Exception:
        # Neon can close idle pooled connections server-side; rollback() on an
        # already-dead connection would itself raise and mask the real error.
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        # Don't recycle a connection Postgres/Neon already dropped — hand the
        # pool a fresh one next time instead of repeating this failure.
        _pool.putconn(conn, close=conn.closed)


def init_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        ddl = f.read()
    with get_cursor(commit=True) as cur:
        cur.execute(ddl)


# --- users ---

def get_or_create_user(name: str) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM users WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            return dict(row)
        cur.execute(
            "INSERT INTO users (name) VALUES (%s) RETURNING *", (name,)
        )
        return dict(cur.fetchone())


def get_user(user_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


# --- topic accuracy (drives adaptive selection) ---

def topic_accuracy(user_id: int) -> list[dict]:
    """Per-topic accuracy across the user's full history."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT q.subject, q.topic,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) AS correct
            FROM responses r
            JOIN questions q ON q.id = r.question_id
            JOIN sessions s ON s.id = r.session_id
            WHERE s.user_id = %s
            GROUP BY q.subject, q.topic
            """,
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# --- questions ---

def all_subjects() -> list[str]:
    with get_cursor() as cur:
        cur.execute("SELECT DISTINCT subject FROM questions ORDER BY subject")
        return [r["subject"] for r in cur.fetchall()]


def pick_questions_for_subject(subject: str, topics_weighted: list[str], count: int, exclude_ids: list[int]) -> list[dict]:
    """Pick `count` questions for a subject, preferring weak topics, avoiding recent repeats."""
    with get_cursor() as cur:
        exclude_ids = exclude_ids or [-1]
        if topics_weighted:
            cur.execute(
                """
                SELECT * FROM questions
                WHERE subject = %s AND topic = ANY(%s) AND id != ALL(%s)
                ORDER BY random() LIMIT %s
                """,
                (subject, topics_weighted, exclude_ids, count),
            )
            rows = [dict(r) for r in cur.fetchall()]
        else:
            rows = []

        if len(rows) < count:
            remaining = count - len(rows)
            got_ids = [r["id"] for r in rows] or [-1]
            cur.execute(
                """
                SELECT * FROM questions
                WHERE subject = %s AND id != ALL(%s) AND id != ALL(%s)
                ORDER BY random() LIMIT %s
                """,
                (subject, exclude_ids, got_ids, remaining),
            )
            rows += [dict(r) for r in cur.fetchall()]
        return rows


def get_question(question_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM questions WHERE id = %s", (question_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def insert_question(subject, topic, text, option_a, option_b, option_c, option_d, correct_option, difficulty, source="generated", question_date=None, source_url=None, paid_mock_test_id=None) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO questions (subject, topic, text, option_a, option_b, option_c, option_d, correct_option, difficulty, source, question_date, source_url, paid_mock_test_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            (subject, topic, text, option_a, option_b, option_c, option_d, correct_option, difficulty, source, question_date, source_url, paid_mock_test_id),
        )
        return cur.fetchone()["id"]


# --- daily current affairs ---

def ca_questions_for_date(question_date) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM questions WHERE subject = 'Current Affairs' AND question_date = %s ORDER BY id",
            (question_date,),
        )
        return [dict(r) for r in cur.fetchall()]


def latest_ca_date():
    with get_cursor() as cur:
        cur.execute(
            "SELECT question_date FROM questions WHERE subject = 'Current Affairs' AND question_date IS NOT NULL ORDER BY question_date DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row["question_date"] if row else None


def get_daily_ca_run(question_date) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM daily_ca_runs WHERE question_date = %s", (question_date,))
        row = cur.fetchone()
        return dict(row) if row else None


def record_ca_run(question_date, source_date, source_url, question_count: int):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO daily_ca_runs (question_date, source_date, source_url, question_count)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (question_date) DO UPDATE SET
                source_date = EXCLUDED.source_date, source_url = EXCLUDED.source_url,
                question_count = EXCLUDED.question_count, generated_at = now()
            """,
            (question_date, source_date, source_url, question_count),
        )


def mark_ca_telegram_posted(question_date):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE daily_ca_runs SET telegram_posted_at = now() WHERE question_date = %s",
            (question_date,),
        )


def mark_ca_pdf_posted(question_date):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE daily_ca_runs SET pdf_posted_at = now() WHERE question_date = %s",
            (question_date,),
        )


# --- paid mock tests ---

def create_paid_mock_test(title: str, uploaded_by: str) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO paid_mock_tests (title, uploaded_by) VALUES (%s, %s) RETURNING id",
            (title, uploaded_by),
        )
        return cur.fetchone()["id"]


def set_paid_mock_live(paid_mock_test_id: int, is_live: bool):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE paid_mock_tests SET is_live = %s WHERE id = %s",
            (is_live, paid_mock_test_id),
        )


def list_paid_mock_tests(live_only: bool = False) -> list[dict]:
    with get_cursor() as cur:
        query = """
            SELECT pmt.*, COUNT(q.id) AS question_count
            FROM paid_mock_tests pmt
            LEFT JOIN questions q ON q.paid_mock_test_id = pmt.id
        """
        if live_only:
            query += " WHERE pmt.is_live = TRUE"
        query += " GROUP BY pmt.id ORDER BY pmt.created_at DESC"
        cur.execute(query)
        return [dict(r) for r in cur.fetchall()]


def get_paid_mock_test(paid_mock_test_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM paid_mock_tests WHERE id = %s", (paid_mock_test_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def paid_mock_questions(paid_mock_test_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM questions WHERE paid_mock_test_id = %s ORDER BY id",
            (paid_mock_test_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# --- access keys ---

def current_access_key() -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM access_keys ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def generate_access_key(key_value: str) -> dict:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO access_keys (key_value, expires_at) VALUES (%s, now() + interval '1 day') RETURNING *",
            (key_value,),
        )
        return dict(cur.fetchone())


# --- paid mock attempts ---

def get_paid_attempt(user_id: int, paid_mock_test_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM paid_mock_attempts WHERE user_id = %s AND paid_mock_test_id = %s",
            (user_id, paid_mock_test_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def paid_attempts_for_user(user_id: int) -> dict:
    """Maps paid_mock_test_id -> attempt row, for the dashboard's paid mocks list."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM paid_mock_attempts WHERE user_id = %s", (user_id,))
        return {r["paid_mock_test_id"]: dict(r) for r in cur.fetchall()}


def record_paid_attempt(user_id: int, paid_mock_test_id: int, session_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO paid_mock_attempts (user_id, paid_mock_test_id, session_id) VALUES (%s, %s, %s)",
            (user_id, paid_mock_test_id, session_id),
        )


# --- sessions ---

def create_session(user_id: int) -> int:
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO sessions (user_id) VALUES (%s) RETURNING id", (user_id,)
        )
        return cur.fetchone()["id"]


def add_session_questions(session_id: int, question_ids: list[int]):
    with get_cursor(commit=True) as cur:
        for seq, qid in enumerate(question_ids):
            cur.execute(
                "INSERT INTO session_questions (session_id, question_id, seq, sent_at) VALUES (%s,%s,%s, NULL)",
                (session_id, qid, seq),
            )


def mark_question_sent(session_id: int, question_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE session_questions SET sent_at = now() WHERE session_id = %s AND question_id = %s AND sent_at IS NULL",
            (session_id, question_id),
        )


def get_session_question_sent_at(session_id: int, question_id: int):
    with get_cursor() as cur:
        cur.execute(
            "SELECT sent_at FROM session_questions WHERE session_id = %s AND question_id = %s",
            (session_id, question_id),
        )
        row = cur.fetchone()
        return row["sent_at"] if row else None


def get_session(session_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def session_questions_ordered(session_id: int) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT sq.seq, sq.sent_at, q.*
            FROM session_questions sq
            JOIN questions q ON q.id = sq.question_id
            WHERE sq.session_id = %s
            ORDER BY sq.seq
            """,
            (session_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def answered_question_ids(session_id: int) -> set:
    with get_cursor() as cur:
        cur.execute("SELECT question_id FROM responses WHERE session_id = %s", (session_id,))
        return {r["question_id"] for r in cur.fetchall()}


def record_response(session_id: int, question_id: int, selected_option: str, is_correct: bool, time_taken_sec: float):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO responses (session_id, question_id, selected_option, is_correct, time_taken_sec)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (session_id, question_id) DO NOTHING
            """,
            (session_id, question_id, selected_option, is_correct, time_taken_sec),
        )


def complete_session(session_id: int):
    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE sessions SET status = 'completed', completed_at = now() WHERE id = %s",
            (session_id,),
        )


def session_summary(session_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT q.subject,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) AS correct,
                   AVG(r.time_taken_sec) AS avg_time_sec
            FROM responses r
            JOIN questions q ON q.id = r.question_id
            WHERE r.session_id = %s
            GROUP BY q.subject
            """,
            (session_id,),
        )
        by_subject = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct FROM responses WHERE session_id = %s",
            (session_id,),
        )
        overall = dict(cur.fetchone())

        return {"overall": overall, "by_subject": by_subject}


def session_review(session_id: int) -> list[dict]:
    """Every question in a session with the user's selected option and
    correctness, for a full after-the-fact answer review."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT sq.seq, q.*, r.selected_option, r.is_correct
            FROM session_questions sq
            JOIN questions q ON q.id = sq.question_id
            LEFT JOIN responses r ON r.session_id = sq.session_id AND r.question_id = sq.question_id
            WHERE sq.session_id = %s
            ORDER BY sq.seq
            """,
            (session_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def recent_answered_question_ids(user_id: int, session_limit: int = 1) -> list[int]:
    """Question ids answered in the user's most recent session(s), to avoid immediate repeats."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.question_id
            FROM responses r
            JOIN sessions s ON s.id = r.session_id
            WHERE s.user_id = %s
            ORDER BY r.answered_at DESC
            LIMIT 200
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        # naive recency cap; session_limit reserved for future use if needed
        return [r["question_id"] for r in rows][: session_limit * 50]


# --- performance (dashboard "My Performance" tab) ---

def subject_performance(user_id: int) -> list[dict]:
    """Accuracy per subject across the user's full history (Current Affairs
    included automatically, since it's just another subject value)."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT q.subject,
                   COUNT(*) AS attempts,
                   SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) AS correct
            FROM responses r
            JOIN questions q ON q.id = r.question_id
            JOIN sessions s ON s.id = r.session_id
            WHERE s.user_id = %s
            GROUP BY q.subject
            ORDER BY q.subject
            """,
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def overall_performance(user_id: int) -> dict:
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS total_sessions FROM sessions WHERE user_id = %s AND status = 'completed'",
            (user_id,),
        )
        total_sessions = cur.fetchone()["total_sessions"]

        cur.execute(
            """
            SELECT COUNT(*) AS total_attempts,
                   SUM(CASE WHEN r.is_correct THEN 1 ELSE 0 END) AS total_correct
            FROM responses r
            JOIN sessions s ON s.id = r.session_id
            WHERE s.user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return {
            "total_sessions": total_sessions,
            "total_attempts": row["total_attempts"] or 0,
            "total_correct": row["total_correct"] or 0,
        }


# --- explanation cache ---

def get_cached_explanation(question_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM explanation_cache WHERE question_id = %s", (question_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def store_explanation(question_id: int, explanation_text: str, model_used: str):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO explanation_cache (question_id, explanation_text, model_used)
            VALUES (%s,%s,%s)
            ON CONFLICT (question_id) DO UPDATE SET explanation_text = EXCLUDED.explanation_text,
                model_used = EXCLUDED.model_used, generated_at = now()
            """,
            (question_id, explanation_text, model_used),
        )
