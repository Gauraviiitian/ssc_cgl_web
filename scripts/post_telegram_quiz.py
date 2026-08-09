"""Posts today's current-affairs questions to Telegram:
  1. Native quiz polls (question + options + correct answer + explanation
     revealed on answer) to the discussion group (TELEGRAM_CHAT_ID).
  2. A recap PDF (all questions + answers + explanations) to the channel
     (TELEGRAM_PREPZONE_CHANNEL_ID), with a caption meant to drive downloads.

This is a script, not a persistent bot: it reads today's questions from
Postgres and calls the Telegram Bot API directly. Meant to run once a day
(e.g. by a GitHub Actions cron) right after generate_daily_ca.py.

Both steps are independently idempotent (tracked via daily_ca_runs'
telegram_posted_at / pdf_posted_at), so re-running only retries whichever
step hasn't succeeded yet.

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

from app import ca_pdf, db  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PREPZONE_CHANNEL_ID = os.environ["TELEGRAM_PREPZONE_CHANNEL_ID"]
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Telegram Bot API limits for sendPoll.
QUESTION_MAX = 300
OPTION_MAX = 100
EXPLANATION_MAX = 200
DELAY_BETWEEN_POLLS_SEC = 30

# Telegram Bot API limit for sendDocument's caption.
CAPTION_MAX = 1024


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


def _post_file(method: str, data: dict, files: dict):
    resp = httpx.post(f"{API_BASE}/{method}", data=data, files=files, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {payload}")
    return payload["result"]


def send_intro(question_date, run: dict):
    text = f"📅 PrepZone Daily Current Affairs Quiz — {question_date.strftime('%d %b %Y')}\n\n Starting in 30 seconds...\n"
    # if run["source_date"] != question_date:
    #     text += f"\n(Today's article wasn't published yet — questions are based on current affairs from the past 7 days, through {run['source_date'].strftime('%d %b %Y')}.)"
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


def post_polls(question_date, run: dict, questions: list[dict]):
    print(f"Posting {len(questions)} questions for {question_date} to chat {CHAT_ID}...")
    send_intro(question_date, run)
    time.sleep(DELAY_BETWEEN_POLLS_SEC)
    for q in questions:
        cached = db.get_cached_explanation(q["id"])
        explanation = cached["explanation_text"] if cached else "See the practice app for the explanation."
        send_question(q, explanation)
        time.sleep(DELAY_BETWEEN_POLLS_SEC)
    db.mark_ca_telegram_posted(question_date)
    print("Polls posted.")


def _build_caption(question_date, count: int) -> str:
    caption = (
        f"🎯 Today's Current Affairs, Exam-Ready! 🎯\n"
        f"📅 {question_date.strftime('%d %b %Y')} · {count} MCQs with full explanations\n\n"
        f"⬇️ Download now, revise on the go, and turn today's headlines into "
        f"tomorrow's marks in the GA section!\n\n"
        f"💬 Discuss & compete: t.me/prepzoneofficial\n"
        f"📢 Never miss a day: t.me/PrepZone_Official"
    )
    return _clip(caption, CAPTION_MAX)


def post_pdf(question_date, questions: list[dict]):
    print(f"Building PDF for {question_date}...")
    explanations = {}
    for q in questions:
        cached = db.get_cached_explanation(q["id"])
        explanations[q["id"]] = cached["explanation_text"] if cached else ""

    pdf_bytes = ca_pdf.build_pdf(questions, explanations, question_date)
    filename = f"PrepZone_CurrentAffairs_{question_date.isoformat()}.pdf"
    caption = _build_caption(question_date, len(questions))

    print(f"Posting PDF to channel {PREPZONE_CHANNEL_ID}...")
    _post_file(
        "sendDocument",
        data={"chat_id": PREPZONE_CHANNEL_ID, "caption": caption},
        files={"document": (filename, pdf_bytes, "application/pdf")},
    )
    db.mark_ca_pdf_posted(question_date)
    print("PDF posted.")


def main():
    db.init_schema()
    today = datetime.now(IST).date()

    run = db.get_daily_ca_run(today)
    if not run:
        print(f"No current affairs generated for {today} yet. Run generate_daily_ca.py first. Skipping.")
        return

    questions = db.ca_questions_for_date(today)
    if not questions:
        print(f"daily_ca_runs has a row for {today} but no questions found. Skipping.")
        return

    if run["telegram_posted_at"]:
        print(f"Polls already posted for {today} at {run['telegram_posted_at']}. Skipping.")
    else:
        post_polls(today, run, questions)

    if run["pdf_posted_at"]:
        print(f"PDF already posted for {today} at {run['pdf_posted_at']}. Skipping.")
    else:
        post_pdf(today, questions)

    print("Done.")


if __name__ == "__main__":
    main()
