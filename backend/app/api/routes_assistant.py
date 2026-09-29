"""Помощник по документации (бета): вопрос → поток ответа, база знаний."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response, StreamingResponse

from app import schemas
from app.api.deps import current_user, get_ctx
from app.services import assistant
from app.services.common import AppContext

router = APIRouter(prefix="/api/assistant")


@router.post("/chat", tags=["assistant"])
def chat(body: schemas.AssistantIn, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """Ответ потоком NDJSON: ``meta`` (источники) → ``delta`` (фрагменты текста) → ``done``."""
    stream = assistant.stream_answer(ctx, user, body.question, body.project_id, ctx.settings.assistant_stream_delay)
    # X-Accel-Buffering: nginx не копит ответ целиком — текст появляется по мере генерации
    return StreamingResponse(stream, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/documents", tags=["assistant"])
def documents(user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return assistant.list_documents(ctx, user)


@router.post("/documents", tags=["assistant"], status_code=201)
def add_document(file: UploadFile = File(...), user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    return assistant.add_document(ctx, user, file.filename or "документ", file.file.read(assistant.MAX_DOC_BYTES + 1))


@router.delete("/documents/{doc_id}", tags=["assistant"], status_code=204)
def delete_document(doc_id: int, user: int = Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    assistant.delete_document(ctx, user, doc_id)
    return Response(status_code=204)
