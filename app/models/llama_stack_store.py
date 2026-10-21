import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.database import (
    calculate_french_amortization,
    evaluate_credit_scoring_and_originate_loan,
    get_account_statement_from_db,
    process_ivr_validation_in_db,
    reconcile_payment_in_db,
    simulate_loan_in_db,
)


@dataclass
class ConversationItem:
    id: str
    type: str
    role: Optional[str] = None
    content: Optional[str] = None
    name: Optional[str] = None
    call_id: Optional[str] = None
    arguments: Optional[str] = None
    output: Optional[str] = None


@dataclass
class ConversationListResponse:
    data: List[ConversationItem] = field(default_factory=list)


class _ConversationsItemsAPI:
    def __init__(self, store: Dict[str, List[ConversationItem]]) -> None:
        self._store = store

    def list(self, conversation_id: str) -> ConversationListResponse:
        items = list(self._store.get(conversation_id, []))
        return ConversationListResponse(data=items)

    def create(self, conversation_id: str, item: ConversationItem) -> ConversationItem:
        if conversation_id not in self._store:
            self._store[conversation_id] = []
        self._store[conversation_id].append(item)
        return item


class _ConversationsAPI:
    def __init__(self) -> None:
        self._store: Dict[str, List[ConversationItem]] = {}
        self.items = _ConversationsItemsAPI(self._store)

    def create(self, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        conv_id = f"conv_{uuid.uuid4().hex[:12]}"
        self._store[conv_id] = []
        return {"id": conv_id, "metadata": metadata or {}}

    def reset(self, conversation_id: str) -> None:
        self._store[conversation_id] = []


class LlamaStackClientAdapter:
    """Llama Stack compatible conversation memory store."""

    def __init__(self) -> None:
        self.conversations = _ConversationsAPI()
        self._session_to_conversation: Dict[str, str] = {}
        self._active_flow: Dict[str, Dict[str, Any]] = {}

    def set_active_flow(self, session_id: str, flow: Optional[Dict[str, Any]]) -> None:
        if flow is None:
            self._active_flow.pop(session_id, None)
        else:
            self._active_flow[session_id] = flow

    def get_active_flow(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._active_flow.get(session_id)

    def get_or_create_conversation_id(self, session_id: str) -> str:
        if session_id not in self._session_to_conversation:
            created = self.conversations.create(metadata={"session_id": session_id})
            self._session_to_conversation[session_id] = created["id"]
        return self._session_to_conversation[session_id]

    def append_message(self, session_id: str, role: str, content: str) -> str:
        conv_id = self.get_or_create_conversation_id(session_id)
        self.conversations.items.create(
            conv_id,
            ConversationItem(
                id=f"msg_{uuid.uuid4().hex[:10]}",
                type="message",
                role=role,
                content=content,
            ),
        )
        return conv_id

    def append_tool_interaction(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        output: Dict[str, Any],
    ) -> str:
        conv_id = self.get_or_create_conversation_id(session_id)
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        self.conversations.items.create(
            conv_id,
            ConversationItem(
                id=f"fc_{uuid.uuid4().hex[:10]}",
                type="function_call",
                name=tool_name,
                call_id=call_id,
                arguments=json.dumps(arguments, ensure_ascii=False),
            ),
        )
        self.conversations.items.create(
            conv_id,
            ConversationItem(
                id=f"fco_{uuid.uuid4().hex[:10]}",
                type="function_call_output",
                call_id=call_id,
                output=json.dumps(output, ensure_ascii=False),
            ),
        )
        return conv_id

    def get_recent_messages(self, session_id: str, limit: int = 8) -> List[Dict[str, str]]:
        conv_id = self.get_or_create_conversation_id(session_id)
        listing = self.conversations.items.list(conv_id)
        messages = [
            {"role": item.role, "content": item.content}
            for item in listing.data
            if item.type == "message" and item.role in ("user", "assistant") and item.content
        ]
        return messages[-limit:]

    def get_items_count(self, session_id: str) -> int:
        conv_id = self.get_or_create_conversation_id(session_id)
        return len(self.conversations.items.list(conv_id).data)

    def clear_session(self, session_id: str) -> bool:
        self._active_flow.pop(session_id, None)
        conv_id = self._session_to_conversation.get(session_id)
        if conv_id:
            self.conversations.reset(conv_id)
            return True
        return False


llama_stack_store = LlamaStackClientAdapter()


def _normalize(text: str) -> str:
    lowered = (text or "").lower().strip()
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def format_hsm_template(template_name: str, payload: Dict[str, Any]) -> str:
    if template_name == "prestamos_simulacion_pdf":
        unit_label = "pagos semanales" if payload.get("product_type") == "DINERO_EXPRESS" else "meses"
        return (
            f"💰 *Simulación de {payload['product_name']}*\n"
            f"• *Monto:* ${payload['requested_amount']:,.2f} MXN\n"
            f"• *Plan sugerido:* {payload['periods']} {unit_label} de *${payload['periodic_payment']:,.2f} MXN*\n"
            f"• *Total a pagar:* ${payload['total_to_pay']:,.2f} MXN _(CAT {payload['average_cat']:.1f}%)_\n\n"
            f"👇 Toca *Elegir plazo* para confirmar tu plazo y procesar tu préstamo."
        )
    if template_name == "seguridad_validacion_contrato":
        return (
            f"🔐 *Crédito Activado*\n"
            f"Hola *{payload['customer_name']}*, tu contrato *{payload['contract_id']}* quedó *{payload['new_credit_status']}* y listo para usarse."
        )
    if template_name == "finanzas_corte_mensual":
        retained_note = (
            f"\n• *En aclaración:* ${payload['retained_balance']:,.2f} MXN _(protegido)_"
            if payload.get("retained_balance", 0) > 0
            else ""
        )
        return (
            f"🧾 *Estado de Cuenta*\n"
            f"• *Saldo disponible:* *${payload['available_balance']:,.2f} MXN*\n"
            f"• *Pago mínimo:* ${payload['minimum_payment']:,.2f} MXN\n"
            f"• *Fecha límite:* {payload['payment_due_date']}"
            f"{retained_note}"
        )
    if template_name == "pago_conciliado_comprobante":
        return (
            f"✅ *Abono Aplicado*\n"
            f"• *Pagado:* *${payload['amount_paid']:,.2f} MXN* ({payload['payment_method']})\n"
            f"• *Nuevo disponible:* *${payload['new_available_balance']:,.2f} MXN*\n"
            f"• *Referencia:* {payload['bank_reference']}"
        )
    return json.dumps(payload, ensure_ascii=False)


def format_loan_origination_message(payload: Dict[str, Any]) -> str:
    decision = payload.get("decision")
    unit_label = "pagos semanales" if payload.get("product_type") == "DINERO_EXPRESS" else "meses"
    if decision == "APROBADO_DEPOSITADO":
        return (
            f"🎉 *¡Felicidades, {payload['customer_name']}! Tu préstamo fue aprobado.*\n"
            f"• *Plan:* *${payload['requested_amount']:,.2f} MXN* a {payload['periods']} {unit_label} de *${payload['periodic_payment']:,.2f} MXN*\n"
            f"• *Score verificado:* {payload['credit_score']} pts — Folio `{payload['bank_reference']}`\n"
            f"🏦 En breve tendrás el depósito en tu cuenta registrada."
        )
    if decision == "EN_EVALUACION":
        return (
            f"⏳ *Tenemos que evaluar tu préstamo por ${payload['requested_amount']:,.2f} MXN*\n"
            f"• *Detalle:* {payload['reason']}\n"
            f"• *Score:* {payload['credit_score']} pts ({payload['pending_installments_count']} pagos pendientes). Te notificaremos por aquí en breve."
        )
    return (
        f"⚠️ *Tuvimos un error al procesar tu préstamo por ${payload['requested_amount']:,.2f} MXN*\n"
        f"• *Motivo:* {payload['reason']}\n"
        f"• *Score:* {payload['credit_score']} pts — Disponible actual: ${payload['new_available_balance']:,.2f} MXN."
    )


def build_whatsapp_interactive_menu(body_text: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds a native Meta WhatsApp Cloud API Interactive List ('Ver opciones') payload
    with row titles strictly <= 24 chars and descriptions <= 72 chars.
    """
    default_body = "¡Hola! Soy tu Asistente Financiero 🏦.\nToca *Ver opciones* para ayudarte:"
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Servicios Financieros 🏦",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Toca para seleccionar una opción",
        },
        "action": {
            "button": "Ver opciones",
            "sections": [
                {
                    "title": "Operaciones",
                    "rows": [
                        {
                            "id": "menu_estado_cuenta",
                            "title": "Estado de cuenta 🧾",
                            "description": "Consulta tu saldo y fecha de pago",
                        },
                        {
                            "id": "menu_hacer_abono",
                            "title": "Hacer un abono 💳",
                            "description": "Abona rápido por SPEI u OXXO",
                        },
                        {
                            "id": "menu_solicitar_prestamo",
                            "title": "Solicitar préstamo 💰",
                            "description": "Préstamo Personal a tu medida",
                        },
                        {
                            "id": "menu_dinero_express",
                            "title": "Express Money ⚡",
                            "description": "Sin comprobantes (solo INE y CLABE)",
                        },
                        {
                            "id": "menu_prestamo_negocio",
                            "title": "Préstamo Negocio 🏪",
                            "description": "Financiamiento para tu comercio",
                        },
                        {
                            "id": "menu_validar_contrato",
                            "title": "Validar contrato 🔐",
                            "description": "Activa tu crédito con código OTP",
                        },
                        {
                            "id": "menu_seguir_folio",
                            "title": "Seguir folio 📄",
                            "description": "Reporta cargos no reconocidos",
                        },
                        {
                            "id": "menu_banco_cat",
                            "title": "Banco y Tasas CAT 🔑",
                            "description": "Tasas, CAT y Meses Sin Intereses",
                        },
                        {
                            "id": "menu_hablar_asesor",
                            "title": "Hablar con asesor 👤",
                            "description": "Atención ejecutiva directa",
                        },
                    ],
                }
            ],
        },
    }


def build_business_loan_tenure_menu(body_text: Optional[str] = None) -> Dict[str, Any]:
    default_body = (
        "¡Gran paso! Impulsa tu comercio con financiamiento a tu medida. "
        "¿Qué antigüedad de operación formal o informal tiene tu negocio actualmente?"
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Préstamo Negocio 🏪",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona la antigüedad de tu negocio",
        },
        "action": {
            "button": "Elegir antigüedad",
            "sections": [
                {
                    "title": "Antigüedad de Operación",
                    "rows": [
                        {
                            "id": "negocio_antiguedad_menos_1",
                            "title": "Menos de 1 año 🌱",
                            "description": "Negocio de reciente apertura",
                        },
                        {
                            "id": "negocio_antiguedad_1_3",
                            "title": "Entre 1 y 3 años ⭐",
                            "description": "Comercio con trayectoria activa",
                        },
                        {
                            "id": "negocio_antiguedad_mas_3",
                            "title": "Más de 3 años 🏆",
                            "description": "Negocio consolidado",
                        },
                        {
                            "id": "menu_principal",
                            "title": "Menú principal 🏠",
                            "description": "Volver a las opciones principales",
                        },
                    ],
                }
            ],
        },
    }


def build_business_loan_amount_menu(body_text: Optional[str] = None) -> Dict[str, Any]:
    default_body = (
        "Perfecto, tu negocio ya tiene trayectoria. "
        "¿Qué monto aproximado necesitas para invertir?"
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Monto de Inversión 🏪",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona el rango de inversión",
        },
        "action": {
            "button": "Elegir monto",
            "sections": [
                {
                    "title": "Monto para tu Negocio",
                    "rows": [
                        {
                            "id": "monto_negocio_50000",
                            "title": "Hasta $50,000 💰",
                            "description": "Capital de trabajo e inventario",
                        },
                        {
                            "id": "monto_negocio_100000",
                            "title": "De $50,000 a $200,000 📈",
                            "description": "Expansión y equipamiento",
                        },
                        {
                            "id": "monto_negocio_250000",
                            "title": "Más de $200,000 🏢",
                            "description": "Nuevas sucursales o maquinaria",
                        },
                        {
                            "id": "menu_principal",
                            "title": "Menú principal 🏠",
                            "description": "Volver a las opciones principales",
                        },
                    ],
                }
            ],
        },
    }


def build_flow_return_interactive_menu(
    body_text: str,
    active_flow: Dict[str, Any],
) -> Dict[str, Any]:
    product_label = active_flow.get("product", "Crédito")
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": f"Solicitud: {product_label[:11]} 🔄",
        },
        "body": {
            "text": body_text[:1020],
        },
        "footer": {
            "text": "Continúa donde te quedaste",
        },
        "action": {
            "button": "Continuar",
            "sections": [
                {
                    "title": "Retomar Solicitud",
                    "rows": [
                        {
                            "id": "continuar_solicitud",
                            "title": "Sí, continuar ▶️",
                            "description": f"Retomar solicitud de {product_label}"[:72],
                        },
                        {
                            "id": "menu_hablar_asesor",
                            "title": "Hablar con asesor 👤",
                            "description": "Atención con un asesor especializado",
                        },
                        {
                            "id": "menu_principal",
                            "title": "Menú principal 🏠",
                            "description": "Volver a las opciones principales",
                        },
                    ],
                }
            ],
        },
    }


def build_loan_simulation_interactive_menu(
    requested_amount: float = 12000.0,
    body_text: Optional[str] = None,
    product_type: str = "PRESTAMO_PERSONAL",
) -> Dict[str, Any]:
    """
    Builds a WhatsApp Interactive List with radio-button loan simulation options
    across 3, 6, 9, and 12 monthly installments plus Dinero Express 14 & 28 days.
    """
    amt = int(round(requested_amount))
    rate = 38.00 if product_type == "PRESTAMO_NEGOCIO" else 45.50
    kind_prefix = "negocio" if product_type == "PRESTAMO_NEGOCIO" else "plazo"
    sim_3m = calculate_french_amortization(amt, product_type, rate, term_months=3)
    sim_6m = calculate_french_amortization(amt, product_type, rate, term_months=6)
    sim_9m = calculate_french_amortization(amt, product_type, rate, term_months=9)
    sim_12m = calculate_french_amortization(amt, product_type, rate, term_months=12)
    sim_14d = calculate_french_amortization(min(amt, 15000), "DINERO_EXPRESS", 36.00, term_days=14)
    sim_28d = calculate_french_amortization(min(amt, 15000), "DINERO_EXPRESS", 36.00, term_days=28)

    default_body = f"💰 *Préstamo por ${amt:,.2f} MXN*\nToca *Elegir plazo* para seleccionar tus pagos:"

    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": f"Planes por ${amt:,.0f} MXN 💰",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona un plazo para procesar tu préstamo",
        },
        "action": {
            "button": "Elegir plazo",
            "sections": [
                {
                    "title": "Plazos Disponibles",
                    "rows": [
                        {
                            "id": f"sim_{kind_prefix}_3m_{amt}",
                            "title": "3 meses 📅",
                            "description": f"${sim_3m['periodic_payment']:,.2f}/mes • Total: ${sim_3m['total_to_pay']:,.2f}",
                        },
                        {
                            "id": f"sim_{kind_prefix}_6m_{amt}",
                            "title": "6 meses (Recomendado) ⭐",
                            "description": f"${sim_6m['periodic_payment']:,.2f}/mes • Total: ${sim_6m['total_to_pay']:,.2f}",
                        },
                        {
                            "id": f"sim_{kind_prefix}_9m_{amt}",
                            "title": "9 meses 📅",
                            "description": f"${sim_9m['periodic_payment']:,.2f}/mes • Total: ${sim_9m['total_to_pay']:,.2f}",
                        },
                        {
                            "id": f"sim_{kind_prefix}_12m_{amt}",
                            "title": "12 meses (Cuota baja) 📅",
                            "description": f"${sim_12m['periodic_payment']:,.2f}/mes • Total: ${sim_12m['total_to_pay']:,.2f}",
                        },
                        {
                            "id": f"sim_express_14d_{min(amt, 15000)}",
                            "title": "Express 14 días ⚡",
                            "description": f"2 pagos de ${sim_14d['periodic_payment']:,.2f}",
                        },
                        {
                            "id": f"sim_express_28d_{min(amt, 15000)}",
                            "title": "Express 28 días ⚡",
                            "description": f"4 pagos de ${sim_28d['periodic_payment']:,.2f}",
                        },
                        {
                            "id": f"contratar_{kind_prefix}_6m_{amt}",
                            "title": "Contratar préstamo ✅",
                            "description": "Confirmar este plazo y depositar",
                        },
                        {
                            "id": "menu_principal",
                            "title": "Menú principal 🏠",
                            "description": "Volver a las opciones principales",
                        },
                    ],
                }
            ],
        },
    }


def detect_conversational_intent(user_text: str) -> Optional[Dict[str, Any]]:
    norm = _normalize(user_text)

    if norm == "menu_banco_cat" or "banco y tasas cat" in norm or "banco y afore" in norm:
        reply_msg = (
            "🔑 *Tasas y CAT*\n"
            "• *Préstamo Personal:* Tasa 45.5% anual (CAT 58.2%).\n"
            "• *Express Money:* Tasa 36.0% anual (CAT 44.0%).\n"
            "• *Préstamo Negocio:* Tasa 38.0% anual (CAT 48.5%)."
        )
        return {
            "intent": "RAG-LEGAL",
            "reply": reply_msg,
            "interactive_menu": build_whatsapp_interactive_menu(reply_msg),
        }

    human_patterns = [
        r"^menu_hablar_asesor$",
        r"\b(hablar|pasar|comunicar|transferir|contactar|conectar)\b.*\b(humano|persona|asesor|agente|ejecutivo|operador|representante)\b",
        r"\b(quiero|necesito|solicito|pido)\b.*\b(humano|persona|asesor|agente|ejecutivo|operador)\b",
        r"\b(un\s+humano|un\s+asesor|un\s+ejecutivo|atencion\s+humana|agente\s+humano|hablar\s+con\s+asesor)\b",
    ]
    for pat in human_patterns:
        if re.search(pat, norm):
            reply_msg = (
                "👤 *Atención con un Ejecutivo*\n"
                "Llámanos sin costo al *800-999-2026* (Opción 2) o escribe a aclaraciones@fintech-omnichannel.mx."
            )
            return {
                "intent": "human_escalation",
                "reply": reply_msg,
                "interactive_menu": build_whatsapp_interactive_menu(reply_msg),
            }

    capability_patterns = [
        r"^menu_principal$",
        r"\b(en\s+que\s+(mas\s+)?me\s+puedes\s+(apoyar|ayudar)|que\s+(mas\s+)?puedes\s+hacer|como\s+me\s+puedes\s+ayudar|cuales\s+son\s+tus\s+funciones|menu\s+de\s+opciones|ver\s+opciones|mostrar\s+menu)\b",
        r"^(hola|buenos\s+dias|buenas\s+tardes|buenas\s+noches|hey|menu|opciones|ayuda)$",
    ]
    for pat in capability_patterns:
        if re.search(pat, norm):
            reply_msg = (
                "¡Hola! Soy tu Asistente Financiero 🏦.\n"
                "Toca *Ver opciones* abajo para consultar tu saldo, abonar o solicitar crédito (Personal, Express o Negocio)."
            )
            return {
                "intent": "assistant_capabilities",
                "reply": reply_msg,
                "interactive_menu": build_whatsapp_interactive_menu(reply_msg),
            }

    return None


def build_loan_amount_discovery_menu(body_text: Optional[str] = None) -> Dict[str, Any]:
    """
    Builds a WhatsApp Interactive List allowing the user to pick a suggested loan amount
    or simply reply in chat with any custom amount they need.
    """
    default_body = (
        "¡Claro! Con gusto te ayudo 😊.\n"
        "¿Qué tipo de préstamo buscas y qué monto necesitas?"
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Solicitar Préstamo 💰",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Escribe el monto en el chat o elige uno aquí",
        },
        "action": {
            "button": "Elegir monto",
            "sections": [
                {
                    "title": "Montos y Opciones",
                    "rows": [
                        {
                            "id": "monto_express_2000",
                            "title": "$2,000 (Express) ⚡",
                            "description": "Solo INE y CLABE • Sin comprobantes",
                        },
                        {
                            "id": "monto_express_4000",
                            "title": "$4,000 (Express) ⚡",
                            "description": "Solo INE y CLABE • Sin comprobantes",
                        },
                        {
                            "id": "monto_personal_5000",
                            "title": "$5,000 (Personal) 💰",
                            "description": "Ver plazos para $5,000 MXN",
                        },
                        {
                            "id": "monto_personal_10000",
                            "title": "$10,000 (Personal) 💰",
                            "description": "Ver plazos para $10,000 MXN",
                        },
                        {
                            "id": "monto_personal_20000",
                            "title": "$20,000 (Personal) 💰",
                            "description": "Ver plazos para $20,000 MXN",
                        },
                        {
                            "id": "ingresos_no_comprobables",
                            "title": "Sin comprobante 🔄",
                            "description": "Cambiar a Express Money al instante",
                        },
                        {
                            "id": "menu_prestamo_negocio",
                            "title": "Préstamo Negocio 🏪",
                            "description": "Para impulsar tu tienda o comercio",
                        },
                        {
                            "id": "menu_principal",
                            "title": "Menú principal 🏠",
                            "description": "Volver a las opciones principales",
                        },
                    ],
                }
            ],
        },
    }


def _extract_explicit_amount(text: str) -> Optional[float]:
    norm = _normalize(text)
    mil_match = re.search(r"\b(\d{1,3}(?:\.\d+)?)\s*mil\b", norm)
    if mil_match:
        try:
            return float(mil_match.group(1)) * 1000.0
        except ValueError:
            pass

    cleaned = norm.replace(",", "")
    cleaned = re.sub(r"\b\d{1,2}\s*(mes|meses|dia|dias|semanas|pagos|cuotas|ano|anos)\b", "", cleaned)
    matches = re.findall(r"\$?\s*(\d{3,7}(?:\.\d{1,2})?)", cleaned)
    for raw in reversed(matches):
        try:
            val = float(raw)
            if val >= 500:
                return val
        except ValueError:
            continue
    return None


def _extract_amount(text: str, default: float = 10000.0) -> float:
    explicit = _extract_explicit_amount(text)
    return explicit if explicit is not None else default


def _was_recently_in_loan_flow(session_id: str) -> Tuple[bool, Optional[str], Optional[float]]:
    recent = llama_stack_store.get_recent_messages(session_id, limit=6)
    in_flow = False
    preferred_type: Optional[str] = None
    last_simulated_amount: Optional[float] = None
    for msg in reversed(recent):
        raw_content = msg.get("content", "")
        norm_c = _normalize(raw_content)
        if any(
            w in norm_c
            for w in [
                "que monto necesitas",
                "que monto te gustaria",
                "que monto aproximado necesitas",
                "que tipo de prestamo",
                "dinero express",
                "express money",
                "prestamo personal",
                "prestamo para negocio",
                "simulacion de",
                "elegir plazo",
            ]
        ):
            in_flow = True
        if last_simulated_amount is None and ("simulacion de" in norm_c or "elegir plazo" in norm_c):
            extracted = _extract_explicit_amount(raw_content)
            if extracted is not None:
                last_simulated_amount = extracted
        if preferred_type is None:
            if ("dinero express" in norm_c or "express money" in norm_c) and "prestamo personal" not in norm_c:
                preferred_type = "DINERO_EXPRESS"
            elif "prestamo para negocio" in norm_c or "impulsa tu comercio" in norm_c:
                preferred_type = "PRESTAMO_NEGOCIO"
            elif "prestamo personal" in norm_c and "dinero express" not in norm_c:
                preferred_type = "PRESTAMO_PERSONAL"
    return in_flow, preferred_type, last_simulated_amount


def detect_and_execute_fintech_tool(
    db: Session,
    user_text: str,
    user_identifier: str,
    session_id: str,
) -> Optional[Tuple[str, str, Dict[str, Any], str, Optional[Dict[str, Any]]]]:
    """
    Inspects user message or interactive list selection for Fintech transactional intents (CU-01..CU-04, CU-FIN-001),
    executes the corresponding SQLAlchemy database operation, records the
    function call in Llama Stack memory, and returns:
    (use_case_code, tool_name, tool_output, formatted_reply, interactive_menu).
    """
    norm = _normalize(user_text)

    if norm in ("continuar_solicitud", "si continuar solicitud", "si, continuar solicitud", "continuar con mi solicitud"):
        active_flow = llama_stack_store.get_active_flow(session_id)
        if active_flow:
            saved_reply = active_flow["reply"]
            saved_menu = active_flow["menu"]
            return (
                "CU-FIN-001-RESUME",
                "resume_loan_flow",
                {"status": "resumed", "product": active_flow.get("product"), "step": active_flow.get("step")},
                saved_reply,
                saved_menu,
            )

    if (
        norm == "ingresos_no_comprobables"
        or "sin ingresos comprobables" in norm
        or "no tengo comprobante" in norm
        or "sin comprobantes" in norm
    ):
        downgrade_reply = (
            "¡No te preocupes! 😊 Te ofrecemos *Express Money* (RN-02): "
            "no requiere comprobantes de ingresos complejos, solo validar tu INE y Cuenta CLABE.\n"
            "¿Qué monto de $1,000 a $15,000 MXN necesitas?"
        )
        menu = build_loan_amount_discovery_menu(downgrade_reply)
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": "Express Money",
                "step": "monto_express",
                "reply": downgrade_reply,
                "menu": menu,
            },
        )
        return (
            "CU-FIN-001-RN02",
            "downgrade_to_express_money",
            {"rule": "RN-02", "offered_product": "DINERO_EXPRESS", "requirements": ["INE", "CLABE"]},
            downgrade_reply,
            menu,
        )

    is_business_loan_start = (
        norm == "menu_prestamo_negocio"
        or (
            any(
                b in norm
                for b in [
                    "prestamo para negocio",
                    "prestamo negocio",
                    "credito para mi tienda",
                    "credito para mi negocio",
                    "credito para negocio",
                ]
            )
            and "?" not in user_text
            and "atras" not in norm
            and "bloque" not in norm
            and "inter" not in norm
        )
    )
    if is_business_loan_start:
        step1_reply = (
            "¡Gran paso! Impulsa tu comercio con financiamiento a tu medida. "
            "¿Qué antigüedad de operación formal o informal tiene tu negocio actualmente?"
        )
        step1_menu = build_business_loan_tenure_menu(step1_reply)
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": "Préstamo para Negocio",
                "step": "antiguedad_negocio",
                "reply": step1_reply,
                "menu": step1_menu,
            },
        )
        return (
            "CU-FIN-001",
            "qualify_business_loan_tenure",
            {"product": "PRESTAMO_NEGOCIO", "step": "antiguedad"},
            step1_reply,
            step1_menu,
        )

    is_business_tenure_step = (
        norm.startswith("negocio_antiguedad_")
        or any(
            t in norm
            for t in [
                "menos de 1 ano",
                "entre 1 y 3 anos",
                "mas de 3 anos",
            ]
        )
    )
    if is_business_tenure_step:
        step2_reply = (
            "Perfecto, tu negocio ya tiene trayectoria. "
            "¿Qué monto aproximado necesitas para invertir?"
        )
        step2_menu = build_business_loan_amount_menu(step2_reply)
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": "Préstamo para Negocio",
                "step": "monto_negocio",
                "tenure": user_text,
                "reply": step2_reply,
                "menu": step2_menu,
            },
        )
        return (
            "CU-FIN-001",
            "qualify_business_loan_amount",
            {"product": "PRESTAMO_NEGOCIO", "step": "monto_inversion", "tenure": user_text},
            step2_reply,
            step2_menu,
        )

    monto_discovery_match = re.match(r"^monto_(express|personal|negocio)_(\d+)$", norm)
    if monto_discovery_match:
        kind, amt_str = monto_discovery_match.groups()
        amount = float(amt_str)
        if kind == "express":
            product_type = "DINERO_EXPRESS"
            term_months = None
            term_days = 14
            prod_label = "Express Money"
        elif kind == "negocio":
            product_type = "PRESTAMO_NEGOCIO"
            term_months = 6
            term_days = None
            prod_label = "Préstamo para Negocio"
        else:
            product_type = "PRESTAMO_PERSONAL"
            term_months = 6
            term_days = None
            prod_label = "Préstamo Personal"

        args = {
            "user_id": user_identifier,
            "product_type": product_type,
            "requested_amount": amount,
            "term_months": term_months,
            "term_days": term_days,
        }
        try:
            output = simulate_loan_in_db(
                db=db,
                user_identifier=user_identifier,
                product_type=product_type,
                requested_amount=amount,
                term_months=term_months,
                term_days=term_days,
            )
            llama_stack_store.append_tool_interaction(session_id, "simulate_loan", args, output)
            reply = format_hsm_template("prestamos_simulacion_pdf", output)
            menu = build_loan_simulation_interactive_menu(
                requested_amount=amount,
                body_text=reply,
                product_type=product_type,
            )
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "step": "elegir_plazo",
                    "amount": amount,
                    "reply": reply,
                    "menu": menu,
                },
            )
            return ("CU-01", "simulate_loan", output, reply, menu)
        except (ValueError, PermissionError) as exc:
            err_payload = {"error": str(exc), "user_id": user_identifier}
            return ("CU-01", "simulate_loan", err_payload, f"⚠️ {exc}", build_whatsapp_interactive_menu())

    sim_radio_match = re.match(r"^(?:sim|contratar)_(plazo|express|negocio)_(\d+)(m|d)_(\d+)$", norm)
    if sim_radio_match:
        kind, num_str, unit, amt_str = sim_radio_match.groups()
        amount = float(amt_str)
        if kind == "express" or unit == "d":
            product_type = "DINERO_EXPRESS"
            term_months = None
            term_days = int(num_str)
        elif kind == "negocio":
            product_type = "PRESTAMO_NEGOCIO"
            term_months = int(num_str)
            term_days = None
        else:
            product_type = "PRESTAMO_PERSONAL"
            term_months = int(num_str)
            term_days = None

        args = {
            "user_id": user_identifier,
            "product_type": product_type,
            "requested_amount": amount,
            "term_months": term_months,
            "term_days": term_days,
        }
        try:
            output = evaluate_credit_scoring_and_originate_loan(
                db=db,
                user_identifier=user_identifier,
                product_type=product_type,
                requested_amount=amount,
                term_months=term_months,
                term_days=term_days,
            )
            llama_stack_store.set_active_flow(session_id, None)
            llama_stack_store.append_tool_interaction(session_id, "originate_loan_with_scoring", args, output)
            reply = format_loan_origination_message(output)
            return ("CU-01-ORIGINATION", "originate_loan_with_scoring", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            err_payload = {"error": str(exc), "user_id": user_identifier}
            return ("CU-01-ORIGINATION", "originate_loan_with_scoring", err_payload, f"⚠️ {exc}", build_whatsapp_interactive_menu())

    explicit_amount = _extract_explicit_amount(user_text)
    in_loan_flow, remembered_product_type, last_simulated_amount = _was_recently_in_loan_flow(session_id)

    term_only_month_match = re.search(r"\b(\d{1,2})\s*mes", norm)
    term_only_day_match = re.search(r"\b(7|14|21|28)\s*dia", norm)
    if (
        in_loan_flow
        and last_simulated_amount is not None
        and explicit_amount is None
        and (term_only_month_match or term_only_day_match)
        and "simul" not in norm
        and "cotiz" not in norm
        and "?" not in user_text
    ):
        amount = last_simulated_amount
        if term_only_day_match:
            product_type = "DINERO_EXPRESS"
            term_months = None
            term_days = int(term_only_day_match.group(1))
        else:
            product_type = remembered_product_type or "PRESTAMO_PERSONAL"
            if product_type == "DINERO_EXPRESS":
                product_type = "PRESTAMO_PERSONAL"
            term_months = max(1, min(12, int(term_only_month_match.group(1))))
            term_days = None

        args = {
            "user_id": user_identifier,
            "product_type": product_type,
            "requested_amount": amount,
            "term_months": term_months,
            "term_days": term_days,
        }
        try:
            output = evaluate_credit_scoring_and_originate_loan(
                db=db,
                user_identifier=user_identifier,
                product_type=product_type,
                requested_amount=amount,
                term_months=term_months,
                term_days=term_days,
            )
            llama_stack_store.set_active_flow(session_id, None)
            llama_stack_store.append_tool_interaction(session_id, "originate_loan_with_scoring", args, output)
            reply = format_loan_origination_message(output)
            return ("CU-01-ORIGINATION", "originate_loan_with_scoring", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            err_payload = {"error": str(exc), "user_id": user_identifier}
            return ("CU-01-ORIGINATION", "originate_loan_with_scoring", err_payload, f"⚠️ {exc}", build_whatsapp_interactive_menu())

    has_loan_keywords = (
        any(
            k in norm
            for k in [
                "menu_solicitar_prestamo",
                "menu_dinero_express",
                "solicitar prestamo",
                "simul",
                "cotiz",
                "prestamo",
                "credito",
                "dinero express",
                "express money",
                "tabla de amortizacion",
            ]
        )
        and "?" not in user_text
        and not any(
            other in norm
            for other in [
                "validar contrato",
                "estado de cuenta",
                "realice mi pago",
                "liquidar mi credito",
                "tasa",
                "cat",
                "moratorio",
                "atras",
                "bloque",
                "hipotec",
                "playa",
                "requisitos",
            ]
        )
    )

    if has_loan_keywords or (in_loan_flow and explicit_amount is not None and "?" not in user_text):
        if explicit_amount is None:
            is_small_hint = any(
                w in norm for w in ["no muy grande", "pequeno", "poco", "chico", "corto", "express", "menu_dinero_express"]
            )
            only_selected_personal = "prestamo personal" in norm or norm == "personal"
            only_selected_express = "dinero express" in norm or "express money" in norm or norm == "express" or norm == "menu_dinero_express"

            if only_selected_personal and in_loan_flow:
                prompt_reply = (
                    "¡Excelente! Para tu *Préstamo Personal* (1 a 12 meses), "
                    "¿qué monto necesitas solicitar?"
                )
                prod_label = "Préstamo Personal"
            elif only_selected_express:
                prompt_reply = (
                    "¡Claro! Con *Express Money* (7 a 28 días) solo validamos tu INE y Cuenta CLABE (sin comprobantes).\n"
                    "¿Qué monto de $1,000 a $15,000 MXN necesitas?"
                )
                prod_label = "Express Money"
            elif is_small_hint:
                prompt_reply = (
                    "¡Claro que sí! 😊 Para un préstamo pequeño te conviene *Express Money* (solo INE y CLABE) o un *Préstamo Personal* corto.\n"
                    "¿Qué tipo de préstamo prefieres y qué monto necesitas?"
                )
                prod_label = "Préstamo Personal"
            else:
                prompt_reply = (
                    "¡Claro que sí! Con gusto te ayudo 😊.\n"
                    "¿Qué tipo de préstamo buscas (*Préstamo Personal*, *Express Money* o *Préstamo para Negocio*) y qué monto necesitas?"
                )
                prod_label = "Préstamo Personal"

            discovery_menu = build_loan_amount_discovery_menu(prompt_reply)
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "step": "descubrimiento_monto",
                    "reply": prompt_reply,
                    "menu": discovery_menu,
                },
            )
            return (
                "CU-01-DISCOVERY",
                "ask_loan_details",
                {"status": "awaiting_amount_and_type"},
                prompt_reply,
                discovery_menu,
            )

        if "negocio" in norm or "tienda" in norm or remembered_product_type == "PRESTAMO_NEGOCIO":
            product_type = "PRESTAMO_NEGOCIO"
            prod_label = "Préstamo para Negocio"
        elif (
            "express" in norm
            or "dias" in norm
            or "menu_dinero_express" in norm
            or remembered_product_type == "DINERO_EXPRESS"
        ):
            product_type = "DINERO_EXPRESS"
            prod_label = "Express Money"
        else:
            product_type = "PRESTAMO_PERSONAL"
            prod_label = "Préstamo Personal"

        amount = explicit_amount
        term_months = 6
        term_days = 14
        month_match = re.search(r"(\d{1,2})\s*mes", norm)
        if month_match:
            term_months = max(1, min(12, int(month_match.group(1))))
        day_match = re.search(r"(7|14|21|28)\s*dia", norm)
        if day_match:
            term_days = int(day_match.group(1))
            product_type = "DINERO_EXPRESS"

        args = {
            "user_id": user_identifier,
            "product_type": product_type,
            "requested_amount": amount,
            "term_months": term_months if product_type != "DINERO_EXPRESS" else None,
            "term_days": term_days if product_type == "DINERO_EXPRESS" else None,
        }
        try:
            output = simulate_loan_in_db(
                db=db,
                user_identifier=user_identifier,
                product_type=product_type,
                requested_amount=amount,
                term_months=args["term_months"],
                term_days=args["term_days"],
            )
            llama_stack_store.append_tool_interaction(session_id, "simulate_loan", args, output)
            reply = format_hsm_template("prestamos_simulacion_pdf", output)
            menu = build_loan_simulation_interactive_menu(
                requested_amount=amount,
                body_text=reply,
                product_type=product_type,
            )
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "step": "elegir_plazo",
                    "amount": amount,
                    "reply": reply,
                    "menu": menu,
                },
            )
            return ("CU-01", "simulate_loan", output, reply, menu)
        except (ValueError, PermissionError) as exc:
            err_payload = {"error": str(exc), "user_id": user_identifier}
            llama_stack_store.append_tool_interaction(session_id, "simulate_loan", args, err_payload)
            return ("CU-01", "simulate_loan", err_payload, f"⚠️ No fue posible completar la simulación: {exc}", None)

    if any(
        k in norm
        for k in [
            "menu_validar_contrato",
            "contratar prestamo",
            "validar contrato",
            "validacion de contrato",
            "codigo otp",
            "activar mi contrato",
            "ivr",
            "confirmar otp",
        ]
    ):
        otp_match = re.search(r"\b(\d{4,6})\b", norm)
        otp_code = otp_match.group(1) if otp_match else "482910"
        args = {"user_id": user_identifier, "validation_result": "VALIDADO", "otp_code": otp_code}
        try:
            output = process_ivr_validation_in_db(
                db=db,
                user_identifier=user_identifier,
                validation_result="VALIDADO",
                otp_code=otp_code,
            )
            llama_stack_store.append_tool_interaction(session_id, "validate_identity_contract", args, output)
            reply = format_hsm_template("seguridad_validacion_contrato", output)
            return ("CU-02", "validate_identity_contract", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            err_payload = {"error": str(exc)}
            return ("CU-02", "validate_identity_contract", err_payload, f"⚠️ Error al validar contrato: {exc}", None)

    if any(
        k in norm
        for k in [
            "menu_estado_cuenta",
            "menu_seguir_folio",
            "seguir folio",
            "estado de cuenta",
            "corte mensual",
            "saldo disponible",
            "cuanto debo",
            "pago minimo",
            "fecha limite de pago",
            "cargo no reconocido",
            "no reconozco un cargo",
        ]
    ):
        is_dispute = any(
            d in norm for d in ["cargo no reconocido", "no reconozco", "menu_seguir_folio", "seguir folio"]
        )
        dispute_amount = _extract_amount(user_text, default=850.0) if is_dispute else None
        args = {"user_id": user_identifier, "register_dispute_amount": dispute_amount}
        try:
            output = get_account_statement_from_db(
                db=db,
                user_identifier=user_identifier,
                register_dispute_amount=dispute_amount,
            )
            llama_stack_store.append_tool_interaction(session_id, "get_account_statement", args, output)
            reply = format_hsm_template("finanzas_corte_mensual", output)
            if is_dispute:
                reply += (
                    f"\n🛡️ *Folio FOL-{output['contract_id'][-4:].upper()}:* "
                    f"${dispute_amount:,.2f} MXN protegidos en aclaración sin intereses."
                )
            return ("CU-03", "get_account_statement", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            err_payload = {"error": str(exc)}
            return ("CU-03", "get_account_statement", err_payload, f"⚠️ No se pudo consultar el estado de cuenta: {exc}", None)

    if any(
        k in norm
        for k in [
            "menu_hacer_abono",
            "hacer un abono",
            "realice mi pago",
            "hice un pago",
            "registrar pago",
            "conciliar pago",
            "pague por spei",
            "pague en oxxo",
            "liquidar mi credito",
            "liquidacion anticipada",
        ]
    ):
        is_early = "liquid" in norm or "anticipad" in norm
        method = "EFECTIVO_OXXO" if "oxxo" in norm else "SPEI"
        amount = _extract_amount(user_text, default=15000.0 if is_early else 2859.75)
        args = {
            "user_id": user_identifier,
            "amount": amount,
            "payment_method": method,
            "is_early_payoff": is_early,
        }
        try:
            output = reconcile_payment_in_db(
                db=db,
                user_identifier=user_identifier,
                amount=amount,
                payment_method=method,
                is_early_payoff=is_early,
            )
            llama_stack_store.append_tool_interaction(session_id, "reconcile_payment", args, output)
            reply = format_hsm_template("pago_conciliado_comprobante", output)
            return ("CU-04", "reconcile_payment", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            err_payload = {"error": str(exc)}
            return ("CU-04", "reconcile_payment", err_payload, f"⚠️ No fue posible conciliar el pago: {exc}", None)

    return None
