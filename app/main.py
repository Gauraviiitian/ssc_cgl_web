from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone

from dotenv import load_dotenv

# .env lives at the ProjectX root, two levels above this file (app/main.py).
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import adaptive, db, llm, mock_upload

app = FastAPI(title="SSC CGL Prep")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

MOCK_SIZE = 20
NO_EXPLANATION_TEXT = "No explanation provided for this question."


@app.on_event("startup")
def startup():
    db.init_schema()


def current_user(request: Request) -> dict | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get_user(user_id)


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


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
def dashboard(request: Request, paid_error: bool = False):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    weak = adaptive.weak_topics_by_subject(user["id"])
    weak_flat = [(subject, topic) for subject, topics in weak.items() for topic in topics]

    overall_perf = db.overall_performance(user["id"])
    overall_accuracy = (
        round(100 * overall_perf["total_correct"] / overall_perf["total_attempts"], 1)
        if overall_perf["total_attempts"]
        else None
    )
    subject_perf = [
        {
            **row,
            "accuracy": round(100 * (row["correct"] or 0) / row["attempts"], 1) if row["attempts"] else 0,
        }
        for row in db.subject_performance(user["id"])
    ]

    paid_unlocked = bool(request.session.get("paid_unlocked"))
    live_mocks = db.list_paid_mock_tests(live_only=True)
    attempts_by_mock = db.paid_attempts_for_user(user["id"])

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "weak_topics": weak_flat,
            "ca_date": db.latest_ca_date(),
            "overall_perf": overall_perf,
            "overall_accuracy": overall_accuracy,
            "subject_perf": subject_perf,
            "paid_unlocked": paid_unlocked,
            "paid_error": paid_error,
            "live_mocks": live_mocks,
            "attempts_by_mock": attempts_by_mock,
        },
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


@app.post("/paid/unlock")
def unlock_paid_mocks(request: Request, key: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    current_key = db.current_access_key()
    now = datetime.now(timezone.utc)
    entered = key.strip().upper()
    valid = (
        current_key is not None
        and current_key["expires_at"] > now
        and secrets.compare_digest(entered, current_key["key_value"])
    )
    if not valid:
        return RedirectResponse("/dashboard?paid_error=1#paid", status_code=302)

    request.session["paid_unlocked"] = True
    return RedirectResponse("/dashboard#paid", status_code=302)


@app.post("/paid/start/{paid_mock_test_id}")
def start_paid_mock(request: Request, paid_mock_test_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)
    if not request.session.get("paid_unlocked"):
        return RedirectResponse("/dashboard#paid", status_code=302)

    mock = db.get_paid_mock_test(paid_mock_test_id)
    if not mock or not mock["is_live"]:
        return RedirectResponse("/dashboard#paid", status_code=302)

    existing = db.get_paid_attempt(user["id"], paid_mock_test_id)
    if existing:
        return RedirectResponse(f"/mock/{existing['session_id']}/review", status_code=302)

    questions = db.paid_mock_questions(paid_mock_test_id)
    if not questions:
        return RedirectResponse("/dashboard#paid", status_code=302)

    session_id = db.create_session(user["id"])
    db.add_session_questions(session_id, [q["id"] for q in questions])
    db.record_paid_attempt(user["id"], paid_mock_test_id, session_id)
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


@app.get("/mock/{session_id}/review", response_class=HTMLResponse)
def review(request: Request, session_id: int):
    user = current_user(request)
    if not user:
        return RedirectResponse("/", status_code=302)

    session = db.get_session(session_id)
    if not session or session["user_id"] != user["id"]:
        return RedirectResponse("/dashboard", status_code=302)

    questions = db.session_review(session_id)
    return templates.TemplateResponse(
        "review.html", {"request": request, "session_id": session_id, "questions": questions}
    )


# --- admin ---

@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": None})


@app.post("/admin/login")
def admin_login(request: Request, name: str = Form(...), password: str = Form(...)):
    if not secrets.compare_digest(password, ADMIN_PASSWORD):
        return templates.TemplateResponse(
            "admin_login.html", {"request": request, "error": "Wrong password."}, status_code=401
        )
    request.session["is_admin"] = True
    request.session["admin_name"] = name.strip() or "Admin"
    return RedirectResponse("/admin", status_code=302)


@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.pop("is_admin", None)
    request.session.pop("admin_name", None)
    return RedirectResponse("/admin/login", status_code=302)


def _admin_context(request: Request, upload_result: dict | None = None) -> dict:
    return {
        "request": request,
        "admin_name": request.session.get("admin_name"),
        "current_key": db.current_access_key(),
        "mocks": db.list_paid_mock_tests(),
        "upload_result": upload_result,
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse("admin.html", _admin_context(request))


@app.post("/admin/mocks/upload", response_class=HTMLResponse)
async def admin_upload_mock(request: Request, title: str = Form(...), file: UploadFile = File(...)):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)

    title = title.strip()
    file_bytes = await file.read()

    try:
        rows, errors = mock_upload.parse_upload(file_bytes, file.filename or "")
    except (ValueError, mock_upload.UploadTooLargeError) as e:
        return templates.TemplateResponse(
            "admin.html", _admin_context(request, upload_result={"failed": str(e)})
        )

    if not title or not rows:
        failed = "Title is required." if not title else "No valid rows found in the file."
        return templates.TemplateResponse(
            "admin.html", _admin_context(request, upload_result={"failed": failed, "errors": errors})
        )

    mock_id = db.create_paid_mock_test(title, request.session.get("admin_name") or "Admin")
    for row in rows:
        qid = db.insert_question(
            subject="Paid Mock",
            topic=title,
            text=row["text"],
            option_a=row["option_a"],
            option_b=row["option_b"],
            option_c=row["option_c"],
            option_d=row["option_d"],
            correct_option=row["correct_option"],
            difficulty="medium",
            source="paid_upload",
            paid_mock_test_id=mock_id,
        )
        db.store_explanation(qid, row["explanation"] or NO_EXPLANATION_TEXT, "manual")

    return templates.TemplateResponse(
        "admin.html",
        _admin_context(
            request,
            upload_result={"imported": len(rows), "errors": errors, "title": title},
        ),
    )


@app.post("/admin/mocks/{paid_mock_test_id}/toggle_live")
def admin_toggle_live(request: Request, paid_mock_test_id: int):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    mock = db.get_paid_mock_test(paid_mock_test_id)
    if mock:
        db.set_paid_mock_live(paid_mock_test_id, not mock["is_live"])
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/keys/generate")
def admin_generate_key(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    key_value = secrets.token_hex(4).upper()
    db.generate_access_key(key_value)
    return RedirectResponse("/admin", status_code=302)
