import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.models.database import RagKnowledgeChunk
from app.models.llama_stack_store import (
    build_flow_return_interactive_menu,
    build_whatsapp_interactive_menu,
    detect_and_execute_fintech_tool,
    detect_conversational_intent,
    llama_stack_store,
)
from app.models.safety import evaluate_input_safety, evaluate_output_safety
from app.models.schemas import ChatMessage, ChatResponse, RetrievedSource

KNOWLEDGE_BASE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "knowledge_base.json",
)
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

ZERO_HALLUCINATION_CONTINGENCY_MSG = (
    "Para darte el dato exacto sobre ese punto, prefiero comunicarte con uno de nuestros asesores especializados. ¿Te gustaría?"
)

SYSTEM_PROMPT = """Eres un asesor financiero virtual experto especializado en productos de crédito (Personal, Express y Negocio). Tu objetivo es guiar al usuario y resolver dudas con absoluta precisión.

REGLAS DE ORO:
1. Responde con un tono profesional, empático y extremadamente conciso (máximo 2 o 3 líneas cortas, nunca superes 320 caracteres). NUNCA inicies con "Según el contexto".
2. Apóyate de forma estricta en el CONTEXTO RECUPERADO. Si la información no soluciona la duda del cliente, di textualmente: "Para darte el dato exacto sobre ese punto, prefiero comunicarte con uno de nuestros asesores especializados. ¿Te gustaría?".
3. Está terminantemente prohibido inventar porcentajes, penalizaciones, montos o plazos que no aparezcan de forma explícita en el contexto.
"""


def _normalize(text: str) -> str:
    lowered = (text or "").lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _is_unsupported_product_query(text: str) -> bool:
    norm = _normalize(text)
    unsupported = [
        "hipotecario",
        "hipoteca",
        "playa",
        "playas",
        "automotriz",
        "auto nuevo",
        "criptomoneda",
        "bitcoin",
        "seguro de vida",
        "fideicomiso",
    ]
    return any(term in norm for term in unsupported)


class FinancialRAGAssistant:
    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []
        self._embedder: Any = None
        self._embeddings: Any = None
        self._load_knowledge_base()

    def _load_knowledge_base(self) -> None:
        loaded: List[Dict[str, str]] = []
        if os.path.exists(KNOWLEDGE_BASE_PATH):
            with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
                loaded.extend(json.load(f))
        self.items = loaded

        if os.getenv("DISABLE_SENTENCE_TRANSFORMERS", "false").lower() == "true":
            return

        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
            corpus = [
                f"{item['category']} - {item['question']} - {item['answer']}"
                for item in self.items
            ]
            if corpus:
                self._embeddings = self._embedder.encode(corpus, normalize_embeddings=True)
        except Exception:
            self._embedder = None
            self._embeddings = None

    def sync_db_chunks(self, db: Session) -> int:
        existing_ids = {item["id"] for item in self.items}
        db_chunks = db.query(RagKnowledgeChunk).all()
        added = 0
        for ch in db_chunks:
            cid = f"DB-RAG-{ch.chunk_id}"
            if cid not in existing_ids:
                self.items.append(
                    {
                        "id": cid,
                        "category": ch.source_document,
                        "question": ch.section_title,
                        "answer": ch.content_text,
                    }
                )
                existing_ids.add(cid)
                added += 1
        if added > 0 and self._embedder is not None:
            try:
                corpus = [
                    f"{item['category']} - {item['question']} - {item['answer']}"
                    for item in self.items
                ]
                self._embeddings = self._embedder.encode(corpus, normalize_embeddings=True)
            except Exception:
                pass
        return len(self.items)

    def retrieve(self, query: str, top_k: int = 3) -> List[RetrievedSource]:
        if not self.items:
            return []

        norm_query = _normalize(query)
        query_tokens = [ tok for tok in re.findall(r"[a-z0-9]{3,}", norm_query) ]

        semantic_scores: List[float] = [0.0] * len(self.items)
        if self._embedder is not None and self._embeddings is not None:
            try:
                import numpy as np

                q_vec = self._embedder.encode([query], normalize_embeddings=True)[0]
                sims = np.dot(self._embeddings, q_vec)
                semantic_scores = [float(s) for s in sims]
            except Exception:
                pass

        scored: List[Tuple[float, Dict[str, str]]] = []
        for idx, item in enumerate(self.items):
            haystack = _normalize(f"{item['category']} {item['question']} {item['answer']}")
            lexical_hits = sum(1 for tok in query_tokens if tok in haystack)
            lexical_score = lexical_hits / max(1, len(query_tokens))
            combined = max(semantic_scores[idx], lexical_score * 0.85)
            if lexical_hits > 0:
                combined = min(0.99, combined + 0.12)
            scored.append((round(float(combined), 4), item))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[RetrievedSource] = []
        for score, item in scored[:top_k]:
            if score >= 0.18:
                results.append(
                    RetrievedSource(
                        id=item["id"],
                        category=item["category"],
                        question=item["question"],
                        answer=item["answer"],
                        score=score,
                    )
                )
        return results

    def _call_llm(
        self,
        user_message: str,
        sources: List[RetrievedSource],
        history: List[Dict[str, str]],
        tool_summary: Optional[str] = None,
    ) -> Tuple[str, str, bool]:
        configured_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1/chat/completions").strip()
        groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

        if "localhost:11434" in configured_url or "127.0.0.1:11434" in configured_url:
            endpoint_url = (
                configured_url
                if configured_url.endswith("/chat/completions")
                else f"{configured_url.rstrip('/')}/chat/completions"
            )
            model_name = os.getenv("LLM_MODEL") or os.getenv("GROQ_MODEL") or "llama3.1:8b"
            headers: Dict[str, str] = {}
        elif groq_api_key:
            base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
            endpoint_url = (
                base_url
                if base_url.endswith("/chat/completions")
                else f"{base_url.rstrip('/')}/chat/completions"
            )
            model_name = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
            headers = {"Authorization": f"Bearer {groq_api_key}"}
        else:
            endpoint_url = (
                configured_url
                if configured_url.endswith("/chat/completions")
                else f"{configured_url.rstrip('/')}/chat/completions"
            )
            model_name = os.getenv("LLM_MODEL", "llama3.1:8b")
            headers = {}

        context_blocks = "\n\n".join(
            f"[{s.id}] ({s.category}) {s.question}: {s.answer}" for s in sources
        )
        if tool_summary:
            context_blocks = f"RESULTADO TRANSACCIONAL EN BASE DE DATOS:\n{tool_summary}\n\n{context_blocks}"

        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context_blocks.strip():
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Información normativa y bancaria verificada para responder al cliente "
                        "(responde con naturalidad sin mencionar la palabra 'contexto'):\n"
                        f"{context_blocks}"
                    ),
                }
            )
        for msg in history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        if os.getenv("FORCE_FALLBACK_LLM", "false").lower() == "true":
            return self._build_fallback_reply(sources, tool_summary), f"{model_name} (fallback)", True

        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.post(
                    endpoint_url,
                    headers=headers,
                    json={
                        "model": model_name,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 160,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"].strip()
                    reply = re.sub(
                        r"^(segun\s+el\s+contexto(\s+proporcionado)?[:,]?\s*)",
                        "",
                        reply,
                        flags=re.IGNORECASE,
                    )
                    if reply:
                        return reply[0].upper() + reply[1:], model_name, False
        except Exception:
            pass

        return self._build_fallback_reply(sources, tool_summary), f"{model_name} (fallback)", True

    @staticmethod
    def _build_fallback_reply(
        sources: List[RetrievedSource],
        tool_summary: Optional[str] = None,
    ) -> str:
        if tool_summary:
            return tool_summary
        if not sources:
            return ZERO_HALLUCINATION_CONTINGENCY_MSG
        top = sources[0]
        return top.answer

    def answer(
        self,
        db: Session,
        message: str,
        session_id: str = "web-default-session",
        user_id: str = "usr-carlos-001",
        history: Optional[List[ChatMessage]] = None,
        top_k: int = 3,
    ) -> ChatResponse:
        self.sync_db_chunks(db)

        input_safety = evaluate_input_safety(message)
        if not input_safety["safe"]:
            safe_msg = input_safety["safe_reply"] or "Solicitud bloqueada por seguridad."
            llama_stack_store.append_message(session_id, "user", message)
            llama_stack_store.append_message(session_id, "assistant", safe_msg)
            return ChatResponse(
                reply=safe_msg,
                sources=[],
                model="safety-guardrail",
                used_fallback=False,
                safety_blocked=True,
                safety_reason=f"{input_safety['layer']}: {input_safety['reason']}",
                session_id=session_id,
                conversation_items_count=llama_stack_store.get_items_count(session_id),
            )

        conv_intent = detect_conversational_intent(message)
        if conv_intent is not None:
            reply_text = conv_intent["reply"]
            llama_stack_store.append_message(session_id, "user", message)
            llama_stack_store.append_message(session_id, "assistant", reply_text)
            return ChatResponse(
                reply=reply_text,
                sources=[],
                model="conversational-router",
                used_fallback=False,
                safety_blocked=False,
                session_id=session_id,
                active_use_case=conv_intent["intent"],
                interactive_menu=conv_intent.get("interactive_menu"),
                conversation_items_count=llama_stack_store.get_items_count(session_id),
            )

        prior_messages = llama_stack_store.get_recent_messages(session_id, limit=6)
        if not prior_messages and history:
            prior_messages = [{"role": m.role, "content": m.content} for m in history[-6:]]

        llama_stack_store.append_message(session_id, "user", message)

        tool_execution = detect_and_execute_fintech_tool(
            db=db,
            user_text=message,
            user_identifier=user_id,
            session_id=session_id,
        )
        sources = self.retrieve(message, top_k=top_k)

        if tool_execution is not None:
            use_case_code, tool_name, tool_output, formatted_hsm_reply, tool_interactive_menu = tool_execution
            output_safety = evaluate_output_safety(formatted_hsm_reply)
            if not output_safety["safe"]:
                blocked_reply = output_safety["safe_reply"] or "Respuesta bloqueada."
                llama_stack_store.append_message(session_id, "assistant", blocked_reply)
                return ChatResponse(
                    reply=blocked_reply,
                    sources=sources,
                    model="safety-guardrail",
                    safety_blocked=True,
                    safety_reason=f"{output_safety['layer']}: {output_safety['reason']}",
                    session_id=session_id,
                    active_use_case=use_case_code,
                    tool_executed=tool_name,
                    tool_output=tool_output,
                    conversation_items_count=llama_stack_store.get_items_count(session_id),
                )

            llama_stack_store.append_message(session_id, "assistant", formatted_hsm_reply)
            return ChatResponse(
                reply=formatted_hsm_reply,
                sources=sources,
                model="fintech-function-calling",
                used_fallback=False,
                safety_blocked=False,
                session_id=session_id,
                active_use_case=use_case_code,
                tool_executed=tool_name,
                tool_output=tool_output,
                interactive_menu=tool_interactive_menu,
                conversation_items_count=llama_stack_store.get_items_count(session_id),
            )

        active_flow = llama_stack_store.get_active_flow(session_id)

        if _is_unsupported_product_query(message) or not sources:
            no_match_reply = ZERO_HALLUCINATION_CONTINGENCY_MSG
            llama_stack_store.append_message(session_id, "assistant", no_match_reply)
            menu = (
                build_flow_return_interactive_menu(no_match_reply, active_flow)
                if active_flow
                else build_whatsapp_interactive_menu(no_match_reply)
            )
            return ChatResponse(
                reply=no_match_reply,
                sources=[],
                model="rag-policy-guard",
                used_fallback=True,
                safety_blocked=False,
                session_id=session_id,
                active_use_case="RN-03-CONTINGENCY",
                interactive_menu=menu,
                conversation_items_count=llama_stack_store.get_items_count(session_id),
            )

        reply_text, model_used, used_fallback = self._call_llm(
            user_message=message,
            sources=sources,
            history=prior_messages,
        )

        if active_flow:
            product_label = active_flow.get("product", "Crédito")
            resume_suffix = f"\n\n¿Te gustaría continuar con tu solicitud de {product_label} donde nos quedamos?"
            max_body_len = 400 - len(resume_suffix)
            if len(reply_text) > max_body_len:
                reply_text = reply_text[: max_body_len - 1].rstrip() + "…"
            reply_text = f"{reply_text}{resume_suffix}"
        elif len(reply_text) > 400:
            reply_text = reply_text[:397].rstrip() + "..."

        output_safety = evaluate_output_safety(reply_text)
        if not output_safety["safe"]:
            blocked_reply = output_safety["safe_reply"] or "Respuesta bloqueada."
            llama_stack_store.append_message(session_id, "assistant", blocked_reply)
            return ChatResponse(
                reply=blocked_reply,
                sources=sources,
                model=model_used,
                used_fallback=used_fallback,
                safety_blocked=True,
                safety_reason=f"{output_safety['layer']}: {output_safety['reason']}",
                session_id=session_id,
                conversation_items_count=llama_stack_store.get_items_count(session_id),
            )

        llama_stack_store.append_message(session_id, "assistant", reply_text)
        final_menu = (
            build_flow_return_interactive_menu(reply_text, active_flow)
            if active_flow
            else build_whatsapp_interactive_menu(reply_text)
        )
        return ChatResponse(
            reply=reply_text,
            sources=sources,
            model=model_used,
            used_fallback=used_fallback,
            safety_blocked=False,
            session_id=session_id,
            active_use_case="RAG-LEGAL",
            interactive_menu=final_menu,
            conversation_items_count=llama_stack_store.get_items_count(session_id),
        )


assistant_service = FinancialRAGAssistant()
