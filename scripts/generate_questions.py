"""One-off seeder: generates SSC CGL practice questions via Groq and loads them
into the questions table. Run this manually when the bank needs topping up —
it is NOT called from the live web app, so it never adds to per-request cost.

Usage: python scripts/generate_questions.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app import db, llm  # noqa: E402

TOPIC_PLAN = {
    "Quant": ["Simple & Compound Interest", "Percentage", "Profit & Loss", "Time & Work", "Averages"],
    "Reasoning": ["Blood Relations", "Coding-Decoding", "Series Completion", "Direction Sense", "Syllogism"],
    "English": ["Spot the Error", "Fill in the Blanks", "Synonyms & Antonyms", "One Word Substitution", "Sentence Improvement"],
    "GA": ["Indian Polity", "Static GK", "Science & Tech", "Geography", "Current Affairs Basics"],
}
QUESTIONS_PER_TOPIC = 3


def main():
    db.init_schema()
    total = 0
    for subject, topics in TOPIC_PLAN.items():
        for topic in topics:
            print(f"Generating {QUESTIONS_PER_TOPIC} questions: {subject} / {topic} ...")
            try:
                questions = llm.generate_questions(subject, topic, QUESTIONS_PER_TOPIC)
            except Exception as e:
                print(f"  FAILED: {e}")
                continue
            for q in questions:
                db.insert_question(
                    subject=subject,
                    topic=topic,
                    text=q["text"],
                    option_a=q["option_a"],
                    option_b=q["option_b"],
                    option_c=q["option_c"],
                    option_d=q["option_d"],
                    correct_option=q["correct_option"],
                    difficulty=q.get("difficulty", "medium"),
                )
                total += 1
            time.sleep(1)  # stay well under Groq rate limits
    print(f"Done. Inserted {total} questions.")


if __name__ == "__main__":
    main()
