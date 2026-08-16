from __future__ import annotations

import json
import os

from groq import Groq

MODEL = "openai/gpt-oss-120b"

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
        temperature=0.5,
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


GENERATE_SYSTEM_PROMPT = (
    """You generate SSC CGL Tier-1 style multiple-choice practice questions. Match the real exam's difficulty and phrasing conventions for the given subject/topic.
    Respond with ONLY a JSON array, no prose, no markdown fences with each element as : 
    {
        "text": str, 
        "option_a": str, 
        "option_b": str, 
        "option_c": str, 
        "option_d": str, 
        "correct_option": "A"|"B"|"C"|"D", 
        "difficulty": "easy"|"medium"|"hard"
    }
    Ensure exactly one option is correct and options are not easy to eliminate or guess."""
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
    """You write SSC CGL Tier-1 style current-affairs multiple-choice questions from a daily news digest. 
    Use only facts present in the supplied source text — do not invent facts. Vary difficulty across easy/medium/hard, and vary the category across the 
    questions (pick each from: Polity, Economy, Sports, Awards, Science & Tech, National, International, Defence, Schemes, Appointments, Banking, Environment). 
    Respond with ONLY a JSON array, no prose, no markdown fences with each element as: 
    {
        "category": str, 
        "text": str, 
        "option_a": str, 
        "option_b": str, 
        "option_c": str, 
        "option_d": str, 
        "correct_option": "A"|"B"|"C"|"D", 
        "difficulty": "easy"|"medium"|"hard", 
        "explanation": str
    } 
    Ensure exactly one option is correct and options are not directly doable using guess work or elimination. 
    Keep "explanation" under 300 characters, plain text, no markdown. """

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
