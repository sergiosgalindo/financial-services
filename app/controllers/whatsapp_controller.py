import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.models.whatsapp import process_whatsapp_webhook_payload

router = APIRouter(tags=["WhatsApp Cloud API"])


@router.get("/webhook")
def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    expected_token = (
        os.getenv("WHATSAPP_VERIFY_TOKEN")
        or os.getenv("VERIFY_TOKEN")
        or "verify-token-123"
    ).strip()
    if hub_mode == "subscribe" and hub_verify_token == expected_token and hub_challenge is not None:
        return PlainTextResponse(content=str(hub_challenge), status_code=200)
    raise HTTPException(status_code=403, detail="Invalid WhatsApp webhook verification token.")


@router.post("/webhook")
async def receive_whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    payload = await request.json()
    sync_mode = request.query_params.get("sync", "false").lower() == "true"
    if sync_mode:
        processed = await process_whatsapp_webhook_payload(payload)
        return {"status": "EVENT_RECEIVED", "processed": processed}

    background_tasks.add_task(process_whatsapp_webhook_payload, payload)
    return {"status": "EVENT_RECEIVED"}


@router.post("/v1/webhooks/whatsapp")
async def receive_v1_whatsapp_webhook(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    processed = await process_whatsapp_webhook_payload(payload)
    return {"status": "PROCESSED", "results": processed}
