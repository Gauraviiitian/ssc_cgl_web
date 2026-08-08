from __future__ import annotations

from app import db

SUBJECTS = ["Quant", "Reasoning", "English", "GA"]
WEAK_ACCURACY_THRESHOLD = 0.6
MIN_ATTEMPTS_TO_TRUST = 3


def weak_topics_by_subject(user_id: int) -> dict[str, list[str]]:
    """Topics where the user's historical accuracy is below threshold, per subject."""
    rows = db.topic_accuracy(user_id)
    weak: dict[str, list[str]] = {s: [] for s in SUBJECTS}
    for row in rows:
        attempts = row["attempts"]
        correct = row["correct"] or 0
        if attempts >= MIN_ATTEMPTS_TO_TRUST and (correct / attempts) < WEAK_ACCURACY_THRESHOLD:
            weak.setdefault(row["subject"], []).append(row["topic"])
    return weak


def build_mock(user_id: int, total_questions: int = 20) -> list[int]:
    """Pick a question set: balanced across subjects, weighted toward weak topics, avoiding recent repeats."""
    weak = weak_topics_by_subject(user_id)
    exclude_ids = db.recent_answered_question_ids(user_id)

    per_subject = total_questions // len(SUBJECTS)
    remainder = total_questions % len(SUBJECTS)

    selected: list[int] = []
    for i, subject in enumerate(SUBJECTS):
        count = per_subject + (1 if i < remainder else 0)
        topics = weak.get(subject, [])
        questions = db.pick_questions_for_subject(
            subject=subject,
            topics_weighted=topics,
            count=count,
            exclude_ids=exclude_ids + selected,
        )
        selected.extend(q["id"] for q in questions)

    return selected
