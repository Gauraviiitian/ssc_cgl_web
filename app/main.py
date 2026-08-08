from __future__ import annotations

import os
from datetime import datetime, timezone

from dotenv import load_dotenv

# .env lives at the ProjectX root, two levels above this file (app/main.py).
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import adaptive, db, llm

app = FastAPI(title="SSC CGL Prep")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

MOCK_SIZE = 20


@app.on_event("startup")
def startup():
    db.init_schema()


def current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get_user(user_id)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = current_user(request)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, name: str = Form(...)):
    name = name.strip()
    if not name:
        return RedirectResponse("/", status_code=302)
    user = db.get_or_create_user(name)
    request.session["user_id"] = user["id"]
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    weak = adaptive.weak_topics_by_subject(user["id"])
    weak_flat = [(subject, topic) for subject, topics in weak.items() for topic in topics]
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "weak_topics": weak_flat, "ca_date": db.latest_ca_date()},
    )


@app.post("/mock/start")
def start_mock(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    question_ids = adaptive.build_mock(user["id"], total_questions=MOCK_SIZE)
    session_id = db.create_session(user["id"])
    db.add_session_questions(session_id, question_ids)
    return RedirectResponse(f"/mock/{session_id}", status_code=302)


@app.post("/ca/start")
def start_ca_quiz(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    ca_date = db.latest_ca_date()
    if not ca_date:
        return RedirectResponse("/dashboard", status_code=302)

    questions = db.ca_questions_for_date(ca_date)
    session_id = db.create_session(user["id"])
    db.add_session_questions(session_id, [q["id"] for q in questions])
    return RedirectResponse(f"/mock/{session_id}", status_code=302)


@app.get("/mock/{session_id}", response_class=HTMLResponse)
def mock_question(request: Request, session_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    session = db.get_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    questions = db.session_questions_ordered(session_id)
    answered_ids = db.answered_question_ids(session_id)
    remaining = [q for q in questions if q["id"] not in answered_ids]

    if not remaining:
        return RedirectResponse(f"/mock/{session_id}/summary", status_code=302)

    question = remaining[0]
    db.mark_question_sent(session_id, question["id"])

    return templates.TemplateResponse(
        "mock.html",
        {
            "request": request,
            "session_id": session_id,
            "question": question,
            "progress": len(answered_ids) + 1,
            "total": len(questions),
        },
    )


@app.post("/mock/{session_id}/answer", response_class=HTMLResponse)
def answer_question(
    request: Request,
    session_id: int,
    question_id: int = Form(...),
    selected_option: str = Form(...),
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    session = db.get_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    question = db.get_question(question_id)
    sent_at = db.get_session_question_sent_at(session_id, question_id)
    time_taken = (datetime.now(timezone.utc) - sent_at).total_seconds() if sent_at else 0

    is_correct = selected_option.upper() == question["correct_option"]
    db.record_response(session_id, question_id, selected_option.upper(), is_correct, time_taken)

    questions = db.session_questions_ordered(session_id)
    answered_ids = db.answered_question_ids(session_id)
    is_last = len(answered_ids) >= len(questions)

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "session_id": session_id,
            "question": question,
            "selected_option": selected_option.upper(),
            "is_correct": is_correct,
            "is_last": is_last,
        },
    )


@app.get("/mock/{session_id}/explain/{question_id}", response_class=HTMLResponse)
def explain(request: Request, session_id: int, question_id: int):
    user = current_user(request)
    if not user:
        return HTMLResponse("Not logged in", status_code=401)

    cached = db.get_cached_explanation(question_id)
    if cached:
        text = cached["explanation_text"]
    else:
        question = db.get_question(question_id)
        text = llm.generate_explanation(question)
        db.store_explanation(question_id, text, llm.MODEL)

    return templates.TemplateResponse(
        "_explanation.html", {"request": request, "explanation": text}
    )


@app.get("/mock/{session_id}/summary", response_class=HTMLResponse)
def summary(request: Request, session_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    session = db.get_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    if session["status"] != "completed":
        db.complete_session(session_id)

    data = db.session_summary(session_id)
    return templates.TemplateResponse(
        "summary.html", {"request": request, "session_id": session_id, **data}
    )
