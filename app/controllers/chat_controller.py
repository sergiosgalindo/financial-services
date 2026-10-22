import time
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.assistant import assistant_service
from app.models.database import get_db
from app.models.llama_stack_store import llama_stack_store
from app.models.schemas import ChatRequest, ChatResponse, ConversationResetRequest
from app.models.whatsapp import get_system_diagnostics, record_metric, summarize_metrics

router = APIRouter(prefix="/api", tags=["Chat & Observability"])


@router.get("/health")
def health_check() -> Dict[str, Any]:
    diag = get_system_diagnostics()
    return {
        "status": "ok",
        "service": diag["service"],
        "database_connected": diag["database"]["connected"],
        "knowledge_base_items": diag["rag"]["total_indexed_items"],
        "llm_model": diag["llm"]["model"],
    }


@router.get("/diagnostics")
def diagnostics_endpoint() -> Dict[str, Any]:
    return get_system_diagnostics()


@router.get("/metrics")
def metrics_endpoint() -> Dict[str, Any]:
    return summarize_metrics()


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    start_ts = time.perf_counter()
    response = assistant_service.answer(
        db=db,
        message=payload.message,
        session_id=payload.session_id or "web-default-session",
        user_id=payload.user_id or "usr-carlos-001",
        history=payload.history,
        top_k=payload.top_k,
    )
    elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
    record_metric(
        latency_ms=elapsed_ms,
        is_whatsapp=False,
        safety_blocked=response.safety_blocked,
        tool_executed=bool(response.tool_executed),
    )
    return response


@router.post("/conversation/reset")
def reset_conversation_endpoint(payload: ConversationResetRequest) -> Dict[str, Any]:
    cleared = llama_stack_store.clear_session(payload.session_id)
    return {"status": "ok", "session_id": payload.session_id, "cleared": cleared}
