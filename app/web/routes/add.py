"""Add: GET /add, POST /entries, POST /uploads (owner and helper; TDD Part 2,
"HTTP routes"; batch 3 plan, CHG-006 S3). A helper sees only what they
submitted, with its status, and nothing else."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.datastructures import UploadFile

from app.ingest.store import DocumentStore, StoreKeyError
from app.web import actions, repo
from app.web.app import render
from app.web.auth import User, db, owner_or_helper
from app.web.routes._common import done, form_values

router = APIRouter()


def add_page(request: Request, conn: sqlite3.Connection, user: User, *, kind: str = "bill",
             values: dict | None = None, errors: dict | None = None, message: str | None = None,
             status: int = 200) -> Response:
    return render(request, "add.html", {
        "kind": kind, "v": values or {}, "e": errors or {}, "message": message,
        "submissions": repo.submissions(conn, user.business_id,
                                        user_id=None if user.role == "owner" else user.id),
    }, status=status)


@router.get("/add")
def add(request: Request, user: User = Depends(owner_or_helper), conn: sqlite3.Connection = Depends(db)):
    kind = request.query_params.get("kind", "bill")
    return add_page(request, conn, user, kind=kind if kind in ("bill", "invoice") else "bill")


@router.post("/entries")
async def entries(request: Request, user: User = Depends(owner_or_helper), conn: sqlite3.Connection = Depends(db)):
    values = await form_values(request)
    try:
        actions.add_entry(conn, user, values, clock=request.app.state.clock)
    except actions.FieldErrors as e:
        kind = values.get("kind") if values.get("kind") in ("bill", "invoice") else "bill"
        return add_page(request, conn, user, kind=kind, values=e.values, errors=e.errors, status=422)
    return done(request, "/add")


@router.post("/uploads")
async def uploads(request: Request, user: User = Depends(owner_or_helper), conn: sqlite3.Connection = Depends(db)):
    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile) or not file.filename:
        return add_page(request, conn, user, errors={"file": "Choose a file to upload."}, status=422)
    content = await file.read(actions.MAX_UPLOAD_BYTES + 1)
    if len(content) > actions.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is over 10 MB.")
    if not content:
        return add_page(request, conn, user, errors={"file": "That file is empty."}, status=422)
    kind = actions.upload_kind(file.content_type, file.filename)
    if kind is None:
        return add_page(request, conn, user, errors={"file": "Upload a photo, a PDF or a voice note."}, status=422)
    settings = request.app.state.settings
    try:
        store = DocumentStore(settings.data_dir, settings.fernet_key)
    except StoreKeyError:
        raise HTTPException(409, "Uploads are not set up yet: FERNET_KEY is missing. "
                                 "See .env.example for how to make one.") from None
    actions.upload(conn, user, content, kind, store, clock=request.app.state.clock)
    return done(request, "/add")
