"""Posts today's current-affairs questions to a Telegram group as native quiz
polls (question + options + correct answer + explanation revealed on answer).

This is a script, not a persistent bot: it reads today's questions from
Postgres and calls the Telegram Bot API directly. Meant to run once a day
(e.g. by a GitHub Actions cron) right after generate_daily_ca.py.

Idempotent: no-ops if today has no generated questions yet, or if they were
already posted.

Usage: python scripts/post_telegram_quiz.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

import httpx  # noqa: E402

from app import db  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Telegram Bot API limits for sendPoll.
QUESTION_MAX = 300
OPTION_MAX = 100
EXPLANATION_MAX = 200
DELAY_BETWEEN_POLLS_SEC = 10


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _post(method: str, payload: dict):
    resp = httpx.post(f"{API_BASE}/{method}", json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {data}")
    return data["result"]


def send_intro(question_date, run: dict):
    text = f"📅 Daily Current Affairs Quiz — {question_date.strftime('%d %b %Y')}"
    if run["source_date"] != question_date:
        text += f"\n(Today's article wasn't published yet — questions are based on current affairs from the past 7 days, through {run['source_date'].strftime('%d %b %Y')}.)"
    _post("sendMessage", {"chat_id": CHAT_ID, "text": text})


def send_question(q: dict, explanation: str):
    options = [q["option_a"], q["option_b"], q["option_c"], q["option_d"]]
    correct_index = "ABCD".index(q["correct_option"])
    _post(
        "sendPoll",
        {
            "chat_id": CHAT_ID,
            "question": _clip(q["text"], QUESTION_MAX),
            "options": [_clip(o, OPTION_MAX) for o in options],
            "type": "quiz",
            "correct_option_id": correct_index,
            "explanation": _clip(explanation, EXPLANATION_MAX),
            "is_anonymous": True,
        },
    )


def main():
    today = datetime.now(IST).date()

    run = db.get_daily_ca_run(today)
    if not run:
        print(f"No current affairs generated for {today} yet. Run generate_daily_ca.py first. Skipping.")
        return
    if run["telegram_posted_at"]:
        print(f"Already posted for {today} at {run['telegram_posted_at']}. Skipping.")
        return

    questions = db.ca_questions_for_date(today)
    if not questions:
        print(f"daily_ca_runs has a row for {today} but no questions found. Skipping.")
        return

    print(f"Posting {len(questions)} questions for {today} to chat {CHAT_ID}...")
    send_intro(today, run)
    for q in questions:
        cached = db.get_cached_explanation(q["id"])
        explanation = cached["explanation_text"] if cached else "See the practice app for the explanation."
        send_question(q, explanation)
        time.sleep(DELAY_BETWEEN_POLLS_SEC)

    db.mark_ca_telegram_posted(today)
    print("Done.")


if __name__ == "__main__":
    main()
