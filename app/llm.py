from __future__ import annotations

import os
from time import time
from typing import Literal

from groq import APIStatusError
from langchain_groq import ChatGroq
from pydantic import BaseModel

MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

EXPLAIN_SYSTEM_PROMPT = (
    "You are an SSC CGL exam tutor. Explain the correct answer to a practice "
    "question concisely, the way a topper explains a shortcut to a friend. "
    "Prioritize the fastest valid method (formula/shortcut) over a textbook derivation. "
    "Keep it under 120 words. Use plain text, no markdown headers."
)

_explain_llm = ChatGroq(model=MODEL, api_key=GROQ_API_KEY, temperature=0.5, max_tokens=300)


def generate_explanation(question: dict) -> str:
    user_prompt = (
        f"Subject: {question['subject']} | Topic: {question['topic']}\n"
        f"Question: {question['text']}\n"
        f"A. {question['option_a']}\nB. {question['option_b']}\n"
        f"C. {question['option_c']}\nD. {question['option_d']}\n"
        f"Correct answer: {question['correct_option']}\n\n"
        "Explain why this is correct and the fastest way to solve it."
    )
    resp = _explain_llm.invoke([
        ("system", EXPLAIN_SYSTEM_PROMPT),
        ("user", user_prompt),
    ])
    return resp.content.strip()


# --- structured output schemas ---
# correct_option as a Literal means Groq's structured-output (tool-calling)
# is constrained to only ever emit A/B/C/D — the old post-hoc "is this one
# of A/B/C/D" validation loop is no longer needed, the model can't produce
# anything else.

class Question(BaseModel):
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: Literal["A", "B", "C", "D"]
    difficulty: Literal["easy", "medium", "hard"]


class QuestionBatch(BaseModel):
    questions: list[Question]


CACategory = Literal[
    "Polity", "Economy", "Sports", "Awards", "Science & Tech", "National",
    "International", "Defence", "Schemes", "Appointments", "Banking", "Environment",
]


class CAQuestion(BaseModel):
    category: CACategory
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: Literal["A", "B", "C", "D"]
    difficulty: Literal["easy", "medium", "hard"]
    explanation: str


class CAQuestionBatch(BaseModel):
    questions: list[CAQuestion]


GENERATE_SYSTEM_PROMPT = (
    """You generate SSC CGL Tier-1 style multiple-choice practice questions. Match the real exam's difficulty and phrasing conventions for the given subject/topic.
    Ensure exactly one option is correct and options are not easy to eliminate or guess."""
)

_generate_llm = ChatGroq(
    model=MODEL, api_key=GROQ_API_KEY, temperature=0.7, max_tokens=4000
).with_structured_output(QuestionBatch)


def generate_questions(subject: str, topic: str, count: int) -> list[dict]:
    user_prompt = (
        f"Generate {count} SSC CGL Tier-1 practice questions for subject '{subject}', topic '{topic}'. "
        "Vary difficulty across easy/medium/hard."
    )
    result = _generate_llm.invoke([
        ("system", GENERATE_SYSTEM_PROMPT),
        ("user", user_prompt),
    ])
    return [q.model_dump() for q in result.questions]


CA_GENERATE_SYSTEM_PROMPT = (
    """You write SSC CGL Tier-1 style current-affairs multiple-choice questions from a daily news digest.
    Use only facts present in the supplied source text — do not invent facts. Vary difficulty across easy/medium/hard, and vary the category across the
    questions (Categories: Polity, Economy, Sports, Awards, Science & Tech, National, International, Defence, Schemes, Appointments, Banking, Environment).
    Ensure exactly one option is correct and options are not directly doable using guess work or elimination.
    Keep "explanation" under 200 characters, plain text, no markdown. """

    """Some examples of valid questions:
    Q1. Mary Kom won her last international gold medal at which boxing competition?
    1. Asian Games, Hangzhou 2. President's Cup, Indonesia 3. World Boxing Championships, New Delhi 4. Commonwealth Games, Birmingham
    Q2. Under the SLKIC component of Khelo India, how many Kendriya Vidyalayas were adopted with KVS partnership?
    1. 30 2. 40 3. 50 4. 60\n
    Q3. Consider the following statements about The Adventures of Kakababu, Volume 1 by Sunil Gangopadhyay:
        1) It features detective Kakababu in an adventure-filled story.
        2) It is based on cultural and mystery themes.
    Which of the statements given above are correct?
        1. Only 1 is correct
        2. Only 2 is correct
        3. Both 1 and 2 are correct
        4. Neither 1 nor 2 is correct\n"
    Q4. Which Indian leader spoke at a special session in 2025 on “Environment, COP-30 and Global Health”?
        1. Piyush Goyal
        2. Hardeep Singh Puri
        3. Narendra Modi
        4. S. Jaishankar
    Q5. According to the Global Cities Index 2025 by Oxford Economics, which two cities topped the list?
        1. Tokyo and Beijing
        2. London and New York
        3. Paris and Rome
        4. Berlin and Moscow
    """
)

# Kept modest — this org's TPM limit for this model counts the source text +
# system prompt + this reservation all together (see ca_scraper.py's
# MAX_COMBINED_SOURCE_CHARS comment).
_ca_generate_llm = ChatGroq(
    model=MODEL, api_key=GROQ_API_KEY, temperature=0.5, max_tokens=5000
).with_structured_output(CAQuestionBatch)


def generate_ca_questions(source_text: str, count: int = 10) -> list[dict]:
    # The char caps in ca_scraper.py keep this well under the org's TPM
    # limit in the normal case, but if a request still comes back 413
    # (request too large), halve the source text and retry once rather
    # than fail the whole day's pipeline over it.
    for attempt in range(2):
        user_prompt = (
            f"""Generate SSC CGL Tier-1 current-affairs MCQs from the news digest below. "
            Vary difficulty and category across the set. 
            DO NOT Generate duplicate questions.
            DO NOT Generate more than one questions per topic or category.\n\n
            SOURCE:\n{source_text}"""
        )
        try:
            result = _ca_generate_llm.invoke([
                ("system", CA_GENERATE_SYSTEM_PROMPT),
                ("user", user_prompt),
            ])
            break
        except APIStatusError as e:
            if e.status_code == 413 and attempt == 0:
                time.sleep(60)  # wait a minute before retrying, in case the org's TPM limit is being hit
                source_text = source_text[:len(source_text) // 2]
                print(f"  Groq 413 (request too large) — retrying with source halved to {len(source_text)} chars")
                continue
            raise

    # correct_option is schema-guaranteed now; explanation is free text, so
    # still guard against the model leaving it blank.
    return [q.model_dump() for q in result.questions if q.explanation.strip()]
