import asyncio
import os
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import httpx

from app.models.assistant import assistant_service
from app.models.database import (
    CommunicationLog,
    CreditAccount,
    FinancialProduct,
    RagKnowledgeChunk,
    SessionLocal,
    User,
    find_user_by_identifier,
    normalize_phone_digits,
)

MAX_PROCESSED_MESSAGE_IDS = 500
_processed_message_ids: "OrderedDict[str, float]" = OrderedDict()
_phone_locks: Dict[str, asyncio.Lock] = {}

_metrics_state: Dict[str, Any] = {
    "total_requests": 0,
    "whatsapp_messages_processed": 0,
    "safety_blocks": 0,
    "tool_calls_executed": 0,
    "latencies_ms": [],
}


def record_metric(
    latency_ms: float,
    is_whatsapp: bool = False,
    safety_blocked: bool = False,
    tool_executed: bool = False,
) -> None:
    _metrics_state["total_requests"] += 1
    if is_whatsapp:
        _metrics_state["whatsapp_messages_processed"] += 1
    if safety_blocked:
        _metrics_state["safety_blocks"] += 1
    if tool_executed:
        _metrics_state["tool_calls_executed"] += 1
    latencies: List[float] = _metrics_state["latencies_ms"]
    latencies.append(round(latency_ms, 2))
    if len(latencies) > 500:
        del latencies[: len(latencies) - 500]


def summarize_metrics() -> Dict[str, Any]:
    latencies: List[float] = list(_metrics_state["latencies_ms"])
    if not latencies:
        return {
            "total_requests": _metrics_state["total_requests"],
            "whatsapp_messages_processed": _metrics_state["whatsapp_messages_processed"],
            "safety_blocks": _metrics_state["safety_blocks"],
            "tool_calls_executed": _metrics_state["tool_calls_executed"],
            "latency_ms": {"avg": 0.0, "p95": 0.0, "max": 0.0},
        }
    sorted_lat = sorted(latencies)
    p95_idx = min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))
    return {
        "total_requests": _metrics_state["total_requests"],
        "whatsapp_messages_processed": _metrics_state["whatsapp_messages_processed"],
        "safety_blocks": _metrics_state["safety_blocks"],
        "tool_calls_executed": _metrics_state["tool_calls_executed"],
        "latency_ms": {
            "avg": round(sum(sorted_lat) / len(sorted_lat), 2),
            "p95": round(sorted_lat[p95_idx], 2),
            "max": round(sorted_lat[-1], 2),
        },
    }


def normalize_mexican_phone(phone: str) -> str:
    return normalize_phone_digits(phone)


def is_duplicate_message(message_id: str) -> bool:
    if not message_id:
        return False
    if message_id in _processed_message_ids:
        return True
    _processed_message_ids[message_id] = time.time()
    while len(_processed_message_ids) > MAX_PROCESSED_MESSAGE_IDS:
        _processed_message_ids.popitem(last=False)
    return False


def get_phone_lock(phone: str) -> asyncio.Lock:
    if phone not in _phone_locks:
        _phone_locks[phone] = asyncio.Lock()
    return _phone_locks[phone]


def extract_incoming_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    extracted: List[Dict[str, str]] = []
    if payload.get("object") and payload.get("entry"):
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    msg_type = msg.get("type", "text")
                    text_body = ""
                    if msg_type == "text":
                        text_body = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        text_body = (
                            interactive.get("list_reply", {}).get("id")
                            or interactive.get("list_reply", {}).get("title")
                            or interactive.get("button_reply", {}).get("id")
                            or interactive.get("button_reply", {}).get("title")
                            or ""
                        )
                    if text_body:
                        extracted.append(
                            {
                                "id": msg.get("id", ""),
                                "from": msg.get("from", ""),
                                "text": text_body.strip(),
                            }
                        )
    elif "from_phone" in payload and "message_body" in payload:
        extracted.append(
            {
                "id": payload.get("wamid", f"wamid.direct.{int(time.time() * 1000)}"),
                "from": str(payload["from_phone"]),
                "text": str(payload["message_body"]).strip(),
            }
        )
    return extracted


def _get_whatsapp_credentials() -> tuple[str, str, str]:
    token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or ""
    ).strip()
    phone_number_id = (
        os.getenv("PHONE_NUMBER_ID")
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        or ""
    ).strip()
    api_version = os.getenv("WHATSAPP_API_VERSION", "v25.0").strip()
    return token, phone_number_id, api_version


async def send_whatsapp_text_message(recipient_phone: str, text: str) -> Dict[str, Any]:
    token, phone_number_id, api_version = _get_whatsapp_credentials()
    normalized_to = normalize_mexican_phone(recipient_phone)

    if not token or not phone_number_id:
        return {
            "sent": False,
            "simulated": True,
            "to": normalized_to,
            "reason": "WHATSAPP_ACCESS_TOKEN or PHONE_NUMBER_ID not set",
        }

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4000]},
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=body)
            res_data = response.json() if response.content else {}
            print(f"[WhatsApp Text Send] to={normalized_to} status={response.status_code} resp={res_data}", flush=True)
            return {
                "sent": response.status_code in (200, 201),
                "status_code": response.status_code,
                "to": normalized_to,
                "response": res_data,
            }
    except Exception as exc:
        print(f"[WhatsApp Text Error] to={normalized_to} err={exc}", flush=True)
        return {
            "sent": False,
            "to": normalized_to,
            "error": str(exc),
        }


async def send_whatsapp_interactive_list(
    recipient_phone: str,
    interactive_payload: Dict[str, Any],
) -> Dict[str, Any]:
    token, phone_number_id, api_version = _get_whatsapp_credentials()
    normalized_to = normalize_mexican_phone(recipient_phone)

    if not token or not phone_number_id:
        return {
            "sent": False,
            "simulated": True,
            "type": "interactive_list",
            "to": normalized_to,
            "reason": "WHATSAPP_ACCESS_TOKEN or PHONE_NUMBER_ID not set",
        }

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalized_to,
        "type": "interactive",
        "interactive": interactive_payload,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=body)
            res_data = response.json() if response.content else {}
            print(f"[WhatsApp Interactive List Send] to={normalized_to} status={response.status_code} resp={res_data}", flush=True)
            return {
                "sent": response.status_code in (200, 201),
                "type": "interactive_list",
                "status_code": response.status_code,
                "to": normalized_to,
                "response": res_data,
            }
    except Exception as exc:
        print(f"[WhatsApp Interactive List Error] to={normalized_to} err={exc}", flush=True)
        return {
            "sent": False,
            "type": "interactive_list",
            "to": normalized_to,
            "error": str(exc),
        }


async def process_whatsapp_webhook_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages = extract_incoming_messages(payload)
    results: List[Dict[str, Any]] = []

    for msg in messages:
        msg_id = msg["id"]
        sender_raw = msg["from"]
        text = msg["text"]
        print(f"[WhatsApp Incoming] id={msg_id} from={sender_raw} text={text!r}", flush=True)

        if is_duplicate_message(msg_id):
            results.append({"id": msg_id, "status": "duplicate_ignored"})
            continue

        normalized_sender = normalize_mexican_phone(sender_raw)
        lock = get_phone_lock(normalized_sender)

        async with lock:
            start_ts = time.perf_counter()
            with SessionLocal() as db:
                user = find_user_by_identifier(db, normalized_sender)
                user_id = user.user_id if user else f"anon-{normalized_sender}"
                session_id = f"wa-{normalized_sender}"

                chat_res = assistant_service.answer(
                    db=db,
                    message=text,
                    session_id=session_id,
                    user_id=user_id,
                )

            interactive_delivery = None
            if chat_res.interactive_menu:
                menu_payload = dict(chat_res.interactive_menu)
                menu_payload["body"] = {"text": chat_res.reply[:1020]}
                interactive_delivery = await send_whatsapp_interactive_list(
                    normalized_sender,
                    menu_payload,
                )
                if interactive_delivery.get("sent") or interactive_delivery.get("simulated"):
                    delivery = interactive_delivery
                else:
                    delivery = await send_whatsapp_text_message(normalized_sender, chat_res.reply)
            else:
                delivery = await send_whatsapp_text_message(normalized_sender, chat_res.reply)

            elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
            record_metric(
                latency_ms=elapsed_ms,
                is_whatsapp=True,
                safety_blocked=chat_res.safety_blocked,
                tool_executed=bool(chat_res.tool_executed),
            )
            results.append(
                {
                    "id": msg_id,
                    "from": normalized_sender,
                    "user_id": user_id,
                    "reply": chat_res.reply,
                    "active_use_case": chat_res.active_use_case,
                    "tool_executed": chat_res.tool_executed,
                    "safety_blocked": chat_res.safety_blocked,
                    "interactive_menu_sent": bool(chat_res.interactive_menu),
                    "delivery": delivery,
                    "interactive_delivery": interactive_delivery,
                }
            )

    return results


def get_system_diagnostics() -> Dict[str, Any]:
    with SessionLocal() as db:
        users_count = db.query(User).count()
        products_count = db.query(FinancialProduct).count()
        contracts_count = db.query(CreditAccount).count()
        comm_logs_count = db.query(CommunicationLog).count()
        rag_db_chunks = db.query(RagKnowledgeChunk).count()

    token, phone_number_id, _ = _get_whatsapp_credentials()
    verify_token = (os.getenv("VERIFY_TOKEN") or os.getenv("WHATSAPP_VERIFY_TOKEN") or "").strip()

    return {
        "status": "ok",
        "service": "fintech-omnichannel-assistant",
        "database": {
            "connected": True,
            "users_count": users_count,
            "financial_products_count": products_count,
            "credit_accounts_count": contracts_count,
            "communication_logs_count": comm_logs_count,
            "rag_knowledge_chunks_count": rag_db_chunks,
        },
        "rag": {
            "total_indexed_items": len(assistant_service.items),
            "embedding_model": os.getenv(
                "EMBEDDING_MODEL",
                os.getenv(
                    "EMBEDDING_MODEL_NAME",
                    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                ),
            ),
        },
        "llm": {
            "provider": "ollama"
            if "localhost:11434" in os.getenv("LLM_BASE_URL", "")
            else ("groq" if os.getenv("GROQ_API_KEY", "").strip() else "ollama"),
            "model": os.getenv("GROQ_MODEL", os.getenv("LLM_MODEL", "llama3.1:8b")),
        },
        "safety": {
            "layer_1": "Prompt Guard (Active)",
            "layer_2": "Llama Guard Input/Output (Active)",
        },
        "whatsapp": {
            "configured": bool(token and phone_number_id),
            "phone_number_id": phone_number_id,
            "verify_token_configured": bool(verify_token),
        },
    }
