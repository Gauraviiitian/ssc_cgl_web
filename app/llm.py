from __future__ import annotations

import json
import os

from groq import Groq

MODEL = "llama-3.3-70b-versatile"

_client = Groq(api_key=os.environ["GROQ_API_KEY"])

EXPLAIN_SYSTEM_PROMPT = (
    "You are an SSC CGL exam tutor. Explain the correct answer to a practice "
    "question concisely, the way a topper explains a shortcut to a friend. "
    "Prioritize the fastest valid method (formula/shortcut) over a textbook derivation. "
    "Keep it under 120 words. Use plain text, no markdown headers."
)


def generate_explanation(question: dict) -> str:
    user_prompt = (
        f"Subject: {question['subject']} | Topic: {question['topic']}\n"
        f"Question: {question['text']}\n"
        f"A. {question['option_a']}\nB. {question['option_b']}\n"
        f"C. {question['option_c']}\nD. {question['option_d']}\n"
        f"Correct answer: {question['correct_option']}\n\n"
        "Explain why this is correct and the fastest way to solve it."
    )
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


GENERATE_SYSTEM_PROMPT = (
    "You generate SSC CGL Tier-1 style multiple-choice practice questions. "
    "Match the real exam's difficulty and phrasing conventions for the given subject/topic. "
    "Respond with ONLY a JSON array, no prose, no markdown fences. "
    "Each element: {\"text\": str, \"option_a\": str, \"option_b\": str, \"option_c\": str, "
    "\"option_d\": str, \"correct_option\": \"A\"|\"B\"|\"C\"|\"D\", \"difficulty\": \"easy\"|\"medium\"|\"hard\"}. "
    "Ensure exactly one option is correct and options are plausible distractors."
)


def generate_questions(subject: str, topic: str, count: int) -> list[dict]:
    user_prompt = (
        f"Generate {count} SSC CGL Tier-1 practice questions for subject '{subject}', topic '{topic}'. "
        "Vary difficulty across easy/medium/hard."
    )
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=4000,
    )
    content = resp.choices[0].message.content.strip()
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    questions = json.loads(content)

    valid = []
    for q in questions:
        opt = str(q.get("correct_option", "")).strip().upper()[:1]
        if opt not in ("A", "B", "C", "D"):
            continue
        q["correct_option"] = opt
        valid.append(q)
    return valid


CA_GENERATE_SYSTEM_PROMPT = (
    "You write SSC CGL Tier-1 style current-affairs multiple-choice questions from a "
    "daily news digest. Use only facts present in the supplied source text — do not invent "
    "facts. Vary difficulty across easy/medium/hard, and vary the category across the "
    "questions (pick each from: Polity, Economy, Sports, Awards, Science & Tech, National, "
    "International, Defence, Schemes, Appointments, Banking, Environment). "
    "Respond with ONLY a JSON array, no prose, no markdown fences. "
    "Each element: {\"category\": str, \"text\": str, \"option_a\": str, \"option_b\": str, "
    "\"option_c\": str, \"option_d\": str, \"correct_option\": \"A\"|\"B\"|\"C\"|\"D\", "
    "\"difficulty\": \"easy\"|\"medium\"|\"hard\", \"explanation\": str}. "
    "Ensure exactly one option is correct and options are plausible distractors. "
    "Keep \"explanation\" under 300 characters, plain text, no markdown."
)


def generate_ca_questions(source_text: str, count: int = 20) -> list[dict]:
    user_prompt = (
        f"Generate {count} SSC CGL Tier-1 current-affairs MCQs from the news digest below. "
        "Vary difficulty and category across the set.\n\n"
        f"SOURCE:\n{source_text}"
    )
    resp = _client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": CA_GENERATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=6000,
    )
    content = resp.choices[0].message.content.strip()
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    questions = json.loads(content)

    valid = []
    for q in questions:
        opt = str(q.get("correct_option", "")).strip().upper()[:1]
        if opt not in ("A", "B", "C", "D"):
            continue
        if not q.get("explanation"):
            continue
        q["correct_option"] = opt
        valid.append(q)
    return valid
