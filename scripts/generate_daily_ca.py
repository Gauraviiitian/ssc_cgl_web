"""Daily current-affairs pipeline: scrape today's CA article, ask Groq for 20
SSC CGL style MCQs with explanations, and save them to Postgres. Meant to be
run once a day (e.g. by a GitHub Actions cron) before post_telegram_quiz.py.

Idempotent: if today's date already has a row in daily_ca_runs, it exits
without calling Groq again.

Usage: python scripts/generate_daily_ca.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app import ca_scraper, db, llm  # noqa: E402

QUESTION_COUNT = 20
IST = ZoneInfo("Asia/Kolkata")


def main():
    db.init_schema()
    today = datetime.now(IST).date()

    existing = db.get_daily_ca_run(today)
    if existing:
        print(f"Already generated for {today} ({existing['question_count']} questions, source {existing['source_date']}). Skipping.")
        return

    print(f"Fetching current affairs source for {today}...")
    source_text, source_url, source_date = ca_scraper.fetch_source_for_date(today)
    if source_date != today:
        print(f"  Note: {today}'s article wasn't up yet, using {source_date}'s instead.")
    print(f"  Source: {source_url} ({len(source_text)} chars)")

    print(f"Asking Groq for {QUESTION_COUNT} questions...")
    questions = llm.generate_ca_questions(source_text, count=QUESTION_COUNT)
    if not questions:
        raise RuntimeError("Groq returned no valid questions")
    print(f"  Got {len(questions)} valid questions")

    for q in questions:
        qid = db.insert_question(
            subject="Current Affairs",
            topic=q.get("category", "General"),
            text=q["text"],
            option_a=q["option_a"],
            option_b=q["option_b"],
            option_c=q["option_c"],
            option_d=q["option_d"],
            correct_option=q["correct_option"],
            difficulty=q.get("difficulty", "medium"),
            source=f"ca:{source_url}",
            question_date=today,
            source_url=source_url,
        )
        db.store_explanation(qid, q["explanation"], llm.MODEL)

    db.record_ca_run(today, source_date, source_url, len(questions))
    print(f"Done. Inserted {len(questions)} current affairs questions for {today}.")


if __name__ == "__main__":
    main()
