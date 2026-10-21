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
    get_early_payoff_quote,
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
            f"💰 *Simulación de {payload['product_name']}* _(informativa, sujeta a evaluación)_\n"
            f"• *Monto:* ${payload['requested_amount']:,.2f} MXN\n"
            f"• *Plan:* {payload['periods']} {unit_label} de *${payload['periodic_payment']:,.2f} MXN*\n"
            f"• *Total estimado:* ${payload['total_to_pay']:,.2f} MXN _(CAT {payload['average_cat']:.1f}% sin IVA)_\n\n"
            f"👇 ¿Quieres confirmar este plazo para evaluación, o prefieres probar otro plazo/monto en *Elegir plazo*?"
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
            f"✅ *Abono Aplicado a tu Crédito*\n"
            f"• *Recibido y aplicado:* *${payload['amount_paid']:,.2f} MXN* ({payload['payment_method']})\n"
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
            f"🏦 En breve tendrás el depósito en tu cuenta registrada. ¿Te puedo ayudar con algo más sobre tu crédito?"
        )
    if decision == "EN_EVALUACION":
        return (
            f"⏳ *Tenemos que evaluar tu préstamo por ${payload['requested_amount']:,.2f} MXN*\n"
            f"• *Detalle:* {payload['reason']}\n"
            f"• *Score:* {payload['credit_score']} pts ({payload['pending_installments_count']} pagos vigentes). Te notificaremos por aquí en breve."
        )
    return (
        f"⚠️ *Tuvimos un inconveniente al procesar tu préstamo por ${payload['requested_amount']:,.2f} MXN*\n"
        f"• *Motivo:* {payload['reason']}\n"
        f"• *Score:* {payload['credit_score']} pts — Disponible actual: ${payload['new_available_balance']:,.2f} MXN."
    )


def build_whatsapp_interactive_menu(body_text: Optional[str] = None) -> Dict[str, Any]:
    default_body = (
        "¡Hola! Soy el asistente de Servicios Financieros 🏦.\n"
        "Puedo ayudarte a revisar opciones de crédito, entender tus pagos o resolver una duda. ¿Qué necesitas hoy?"
    )
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
                    "title": "Préstamos y créditos",
                    "rows": [
                        {
                            "id": "menu_solicitar_prestamo",
                            "title": "Préstamo personal 💰",
                            "description": "Crédito a tu medida de 1 a 12 meses",
                        },
                        {
                            "id": "menu_dinero_express",
                            "title": "Dinero Express ⚡",
                            "description": "Corto plazo de 7 a 28 días",
                        },
                        {
                            "id": "menu_prestamo_negocio",
                            "title": "Crédito para negocio 🏪",
                            "description": "Financiamiento sujeto a evaluación",
                        },
                    ],
                },
                {
                    "title": "Mi crédito",
                    "rows": [
                        {
                            "id": "menu_estado_cuenta",
                            "title": "Estado de cuenta 🧾",
                            "description": "Consulta tu saldo y fecha de corte",
                        },
                        {
                            "id": "menu_hacer_abono",
                            "title": "Confirmar un pago 💳",
                            "description": "Reporta tu referencia y monto abonado",
                        },
                        {
                            "id": "menu_seguir_folio",
                            "title": "Cargo no reconocido 🛡️",
                            "description": "Reporta o da seguimiento a un cargo",
                        },
                    ],
                },
                {
                    "title": "Ayuda",
                    "rows": [
                        {
                            "id": "menu_banco_cat",
                            "title": "Tengo una duda ❓",
                            "description": "Consulta tasas, CAT y políticas",
                        },
                        {
                            "id": "menu_hablar_asesor",
                            "title": "Hablar con persona 👤",
                            "description": "Atención personalizada con un asesor",
                        },
                    ],
                },
            ],
        },
    }


def build_loan_purpose_menu(
    amount: Optional[float] = None,
    body_text: Optional[str] = None,
) -> Dict[str, Any]:
    amt_suffix = f"_{int(round(amount))}" if amount is not None else ""
    default_body = "Con gusto. ¿El préstamo sería para un gasto personal o para tu negocio?"
    rows = [
        {
            "id": f"proposito_personal{amt_suffix}",
            "title": "Préstamo personal 💰",
            "description": "De 1 a 12 meses para tus planes",
        },
    ]
    if amount is None or amount <= 15000:
        rows.append(
            {
                "id": f"proposito_express{amt_suffix}",
                "title": "Dinero Express ⚡",
                "description": "De 7 a 28 días para imprevistos",
            }
        )
    rows.extend(
        [
            {
                "id": f"proposito_negocio{amt_suffix}",
                "title": "Para mi negocio 🏪",
                "description": "Sujeto a evaluación para tu comercio",
            },
            {
                "id": "menu_principal",
                "title": "Menú principal 🏠",
                "description": "Volver a las opciones principales",
            },
        ]
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Tipo de Préstamo 💰",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona el propósito de tu crédito",
        },
        "action": {
            "button": "Elegir opción",
            "sections": [
                {
                    "title": "Opciones Disponibles",
                    "rows": rows,
                }
            ],
        },
    }


def build_loan_amount_menu(
    product_type: str = "PRESTAMO_PERSONAL",
    body_text: Optional[str] = None,
) -> Dict[str, Any]:
    default_body = "¿Qué cantidad te gustaría revisar? Puedes elegir una opción o escribirla en el chat:"
    if product_type == "DINERO_EXPRESS":
        rows = [
            {"id": "monto_express_1000", "title": "$1,000 MXN ⚡", "description": "Plazo de 7 a 28 días"},
            {"id": "monto_express_2000", "title": "$2,000 MXN ⚡", "description": "Plazo de 7 a 28 días"},
            {"id": "monto_express_4000", "title": "$4,000 MXN ⚡", "description": "Plazo de 7 a 28 días"},
            {"id": "monto_express_8000", "title": "$8,000 MXN ⚡", "description": "Plazo de 7 a 28 días"},
            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
        ]
    elif product_type == "PRESTAMO_NEGOCIO":
        rows = [
            {"id": "monto_negocio_50000", "title": "Hasta $50,000 💰", "description": "Capital de trabajo e inventario"},
            {"id": "monto_negocio_100000", "title": "De $50k a $200k 📈", "description": "Expansión y equipamiento"},
            {"id": "monto_negocio_250000", "title": "Más de $200,000 🏢", "description": "Nuevas sucursales o maquinaria"},
            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
        ]
    else:
        rows = [
            {"id": "monto_personal_5000", "title": "$5,000 MXN 💰", "description": "Pagos a tu medida en meses"},
            {"id": "monto_personal_10000", "title": "$10,000 MXN 💰", "description": "Pagos a tu medida en meses"},
            {"id": "monto_personal_20000", "title": "$20,000 MXN 💰", "description": "Pagos a tu medida en meses"},
            {"id": "monto_personal_30000", "title": "$30,000 MXN 💰", "description": "Pagos a tu medida en meses"},
            {"id": "ingresos_no_comprobables", "title": "Sin comprobante 📄", "description": "Evaluar alternativa Express"},
            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
        ]
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Monto a Solicitar 💰",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Elige un monto sugerido o escribe otro",
        },
        "action": {
            "button": "Elegir monto",
            "sections": [
                {
                    "title": "Montos Sugeridos",
                    "rows": rows,
                }
            ],
        },
    }


def build_loan_term_menu(
    product_type: str,
    amount: float,
    body_text: Optional[str] = None,
) -> Dict[str, Any]:
    amt = int(round(amount))
    kind = "express" if product_type == "DINERO_EXPRESS" else ("negocio" if product_type == "PRESTAMO_NEGOCIO" else "personal")
    unit_word = "días" if kind == "express" else "meses"
    default_body = f"Para ${amt:,.2f} MXN, ¿en cuántos {unit_word} te gustaría comparar el pago?"
    if kind == "express":
        rows = [
            {"id": f"plazo_express_7d_{amt}", "title": "7 días ⚡", "description": "Pago a corto plazo"},
            {"id": f"plazo_express_14d_{amt}", "title": "14 días (Recomendado) ⭐", "description": "2 pagos semanales"},
            {"id": f"plazo_express_21d_{amt}", "title": "21 días ⚡", "description": "3 pagos semanales"},
            {"id": f"plazo_express_28d_{amt}", "title": "28 días ⚡", "description": "4 pagos semanales"},
            {"id": f"cambiar_monto_{kind}", "title": "Cambiar monto 💰", "description": "Elegir otra cantidad"},
            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
        ]
    else:
        rows = [
            {"id": f"plazo_{kind}_3m_{amt}", "title": "3 meses 📅", "description": "Pago mensual fijo"},
            {"id": f"plazo_{kind}_6m_{amt}", "title": "6 meses (Recomendado) ⭐", "description": "Pago mensual equilibrado"},
            {"id": f"plazo_{kind}_9m_{amt}", "title": "9 meses 📅", "description": "Pago mensual accesible"},
            {"id": f"plazo_{kind}_12m_{amt}", "title": "12 meses 📅", "description": "Cuota mensual más baja"},
            {"id": f"cambiar_monto_{kind}", "title": "Cambiar monto 💰", "description": "Elegir otra cantidad"},
            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
        ]
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Elegir Plazo 📅",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona el plazo de pago",
        },
        "action": {
            "button": "Elegir plazo",
            "sections": [
                {
                    "title": "Plazos Disponibles",
                    "rows": rows,
                }
            ],
        },
    }


def build_loan_confirmation_menu(
    product_type: str,
    amount: float,
    term_num: int,
    term_unit: str,
    body_text: Optional[str] = None,
) -> Dict[str, Any]:
    amt = int(round(amount))
    kind = "express" if product_type == "DINERO_EXPRESS" else ("negocio" if product_type == "PRESTAMO_NEGOCIO" else "personal")
    prod_label = "Dinero Express" if kind == "express" else ("Préstamo para Negocio" if kind == "negocio" else "Préstamo Personal")
    term_label = f"{term_num} días" if term_unit == "d" else f"{term_num} meses"
    default_body = (
        f"Resumen de tu simulación:\n"
        f"• *Producto:* {prod_label}\n"
        f"• *Monto:* ${amt:,.2f} MXN\n"
        f"• *Plazo:* {term_label}\n\n"
        f"¿Así está bien para preparar una simulación?"
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": "Confirmar Simulación 📝",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Confirma para generar tu simulación",
        },
        "action": {
            "button": "Confirmar",
            "sections": [
                {
                    "title": "Confirmación",
                    "rows": [
                        {
                            "id": f"confirmar_sim_{kind}_{term_num}{term_unit}_{amt}",
                            "title": "Sí, simular ✅",
                            "description": "Calcular cuota estimada informativa",
                        },
                        {
                            "id": f"cambiar_plazo_{kind}_{amt}",
                            "title": "Cambiar plazo 📅",
                            "description": "Elegir otro plazo para el cálculo",
                        },
                        {
                            "id": f"cambiar_monto_{kind}",
                            "title": "Cambiar monto 💰",
                            "description": "Elegir otra cantidad",
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
    term_num: int = 6,
    term_unit: str = "m",
) -> Dict[str, Any]:
    amt = int(round(requested_amount))
    kind = "express" if product_type == "DINERO_EXPRESS" else ("negocio" if product_type == "PRESTAMO_NEGOCIO" else "personal")
    default_body = (
        f"💰 *Simulación por ${amt:,.2f} MXN*\n"
        f"¿Quieres probar otro monto o plazo, enviar a evaluación o dejarlo aquí por ahora?"
    )
    return {
        "type": "list",
        "header": {
            "type": "text",
            "text": f"Opciones de Crédito 💰",
        },
        "body": {
            "text": (body_text or default_body)[:1020],
        },
        "footer": {
            "text": "Selecciona el siguiente paso",
        },
        "action": {
            "button": "Siguiente paso",
            "sections": [
                {
                    "title": "Siguiente Paso",
                    "rows": [
                        {
                            "id": f"solicitar_{kind}_{term_num}{term_unit}_{amt}",
                            "title": "Enviar a evaluación 📝",
                            "description": "Registrar solicitud para revisión del core",
                        },
                        {
                            "id": f"cambiar_plazo_{kind}_{amt}",
                            "title": "Cambiar plazo 📅",
                            "description": "Comparar pagos con otro plazo",
                        },
                        {
                            "id": f"cambiar_monto_{kind}",
                            "title": "Cambiar monto 💰",
                            "description": "Simular con otra cantidad",
                        },
                        {
                            "id": "menu_banco_cat",
                            "title": "Tengo una duda ❓",
                            "description": "Consultar CAT, tasas o políticas",
                        },
                        {
                            "id": "cerrar_conversacion",
                            "title": "Dejarlo por ahora ❌",
                            "description": "Concluir la consulta por ahora",
                        },
                    ],
                }
            ],
        },
    }


def _friendly_error(exc: Exception, user_identifier: str) -> str:
    err_str = str(exc).lower()
    if "not found" in err_str:
        return (
            "No pude identificar una cuenta asociada a este número. "
            "Por tu seguridad, comunícate a nuestros canales oficiales o al *800-999-2026* para asistirte."
        )
    if "exceeds" in err_str or "limite" in err_str:
        return (
            "El monto solicitado excede el límite disponible en tu cuenta. "
            "¿Te gustaría revisar una cantidad menor?"
        )
    if "blocked" in err_str or "bloquead" in err_str or "rechazad" in err_str:
        return (
            "Tu cuenta presenta un estatus que requiere atención de un asesor. "
            "Por favor comunícate al *800-999-2026* para brindarte opciones."
        )
    return (
        "Tuvimos un inconveniente al consultar tu información. "
        "¿Te gustaría intentar nuevamente o prefieres que te comunique con un asesor?"
    )


def detect_conversational_intent(user_text: str) -> Optional[Dict[str, Any]]:
    norm = _normalize(user_text)

    if norm == "menu_banco_cat" or "banco y tasas cat" in norm or "tengo una duda" in norm:
        reply_msg = (
            "Con gusto resuelvo tus dudas sobre tasas, CAT, plazos, pagos o requisitos de nuestros créditos. "
            "¿Qué te gustaría consultar?"
        )
        return {
            "intent": "RAG-LEGAL",
            "reply": reply_msg,
            "interactive_menu": build_whatsapp_interactive_menu(reply_msg),
        }

    closing_patterns = [
        r"^(gracias|muchas gracias|mil gracias|eso es todo|adios|bye|hasta luego|cerrar_conversacion)$",
        r"\b(muchas gracias|eso seria todo|ya no necesito nada|dejarlo por ahora)\b",
    ]
    for pat in closing_patterns:
        if re.search(pat, norm):
            reply_msg = (
                "Gracias por escribirnos. Aquí estaré si necesitas revisar otra cosa. "
                "Cuida tus datos y recuerda que nunca te pediremos tu NIP ni tus códigos."
            )
            return {
                "intent": "closing_intent",
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
                "👤 *Atención con un Asesor*\n"
                "Con gusto te comunicamos. Llámanos sin costo al *800-999-2026* (Opción 2) o indícame tu duda para orientarte."
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
                "¡Hola! Soy el asistente de Servicios Financieros 🏦.\n"
                "Puedo ayudarte a revisar opciones de crédito, entender tus pagos o resolver una duda. ¿Qué necesitas hoy?"
            )
            return {
                "intent": "assistant_capabilities",
                "reply": reply_msg,
                "interactive_menu": build_whatsapp_interactive_menu(reply_msg),
            }

    return None


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


def detect_and_execute_fintech_tool(
    db: Session,
    user_text: str,
    user_identifier: str,
    session_id: str,
) -> Optional[Tuple[str, str, Dict[str, Any], str, Optional[Dict[str, Any]]]]:
    norm = _normalize(user_text)

    if norm == "cerrar_conversacion":
        llama_stack_store.set_active_flow(session_id, None)
        closing_msg = (
            "Gracias por escribirnos. Aquí estaré si necesitas revisar otra cosa. "
            "Cuida tus datos y recuerda que nunca te pediremos tu NIP ni tus códigos."
        )
        return (
            "CLOSING",
            "close_conversation",
            {"status": "closed"},
            closing_msg,
            build_whatsapp_interactive_menu(closing_msg),
        )

    if user_identifier.startswith("anon-"):
        is_personal_data_request = any(
            k in norm
            for k in [
                "menu_estado_cuenta",
                "estado de cuenta",
                "saldo",
                "cuanto debo",
                "pago minimo",
                "fecha limite",
                "menu_hacer_abono",
                "hacer un abono",
                "realice mi pago",
                "hice un pago",
                "pague",
                "abono",
                "menu_seguir_folio",
                "seguir folio",
                "cargo no reconocido",
            ]
        )
        if is_personal_data_request:
            anon_reply = (
                "No pude identificar una cuenta asociada a este número. "
                "Por tu seguridad, comunícate a nuestros canales oficiales o al *800-999-2026* para autenticarte."
            )
            return (
                "CU-ANON-AUTH",
                "auth_required",
                {"status": "unauthenticated"},
                anon_reply,
                build_whatsapp_interactive_menu(anon_reply),
            )

    if norm in ("continuar_solicitud", "si continuar solicitud", "si, continuar solicitud", "continuar con mi solicitud"):
        active_flow = llama_stack_store.get_active_flow(session_id)
        if active_flow:
            saved_reply = active_flow.get("reply", "Retomando tu solicitud.")
            saved_menu = active_flow.get("menu")
            return (
                "CU-FIN-001-RESUME",
                "resume_loan_flow",
                {"status": "resumed", "product": active_flow.get("product"), "step": active_flow.get("step")},
                saved_reply,
                saved_menu,
            )

    if any(f in norm for f in ["robo", "me robaron", "fraude", "clonaron", "suplantaron", "tarjeta clonada"]):
        fraud_reply = (
            "Siento que estés pasando por esto. Vamos a ayudarte a proteger tu cuenta. "
            "Comunícate de inmediato al *800-999-2026* (Opción 1) para el bloqueo de tu tarjeta "
            "y canalizar la investigación con un especialista."
        )
        return (
            "CU-03-FRAUD",
            "fraud_alert_escalation",
            {"action": "escalate_to_fraud_prevention"},
            fraud_reply,
            build_whatsapp_interactive_menu(fraud_reply),
        )

    if (
        norm == "ingresos_no_comprobables"
        or "sin ingresos comprobables" in norm
        or "no tengo comprobante" in norm
        or "sin comprobantes" in norm
    ):
        downgrade_reply = (
            "Gracias por contármelo. Puedo revisar si hay otra alternativa disponible para tu cuenta como Express Money. "
            "No puedo confirmar que sea aprobada hasta que el sistema la evalúe. "
            "¿Quieres que revisemos esa opción o prefieres hablar con un asesor?"
        )
        menu = {
            "type": "list",
            "header": {"type": "text", "text": "Alternativas ⚡"},
            "body": {"text": downgrade_reply[:1020]},
            "footer": {"text": "Elige una opción"},
            "action": {
                "button": "Ver alternativas",
                "sections": [
                    {
                        "title": "Opciones",
                        "rows": [
                            {"id": "proposito_express", "title": "Dinero Express ⚡", "description": "De 7 a 28 días con INE y CLABE"},
                            {"id": "menu_hablar_asesor", "title": "Hablar con asesor 👤", "description": "Atención especializada"},
                            {"id": "menu_principal", "title": "Menú principal 🏠", "description": "Volver al inicio"},
                        ],
                    }
                ],
            },
        }
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": "Express Money",
                "product_type": "DINERO_EXPRESS",
                "step": "elegir_monto",
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
                "product_type": "PRESTAMO_NEGOCIO",
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
        if "menos de 1" in norm:
            step2_reply = (
                "Gracias. Al tener menos de 1 año de operación, evaluaremos tu solicitud con opciones iniciales. "
                "¿Qué monto aproximado necesitas para invertir?"
            )
        elif "mas de 3" in norm:
            step2_reply = (
                "Excelente, con más de 3 años tu comercio cuenta con trayectoria activa y solidez. "
                "¿Qué monto aproximado necesitas para invertir?"
            )
        else:
            step2_reply = (
                "Perfecto, tu negocio ya tiene trayectoria. "
                "¿Qué monto aproximado necesitas para invertir?"
            )
        step2_menu = build_business_loan_amount_menu(step2_reply)
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": "Préstamo para Negocio",
                "product_type": "PRESTAMO_NEGOCIO",
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

    purpose_match = re.match(r"^proposito_(personal|express|negocio)(?:_(\d+))?$", norm)
    active_flow = llama_stack_store.get_active_flow(session_id) or {}
    is_text_purpose_reply = active_flow.get("step") == "descubrimiento_proposito" and any(
        p in norm for p in ["personal", "gasto personal", "express", "corto plazo", "negocio", "comercio", "tienda"]
    )

    if purpose_match or is_text_purpose_reply:
        if purpose_match:
            kind, amt_str = purpose_match.groups()
            amount = float(amt_str) if amt_str else active_flow.get("amount")
        else:
            if "negocio" in norm or "tienda" in norm or "comercio" in norm:
                kind = "negocio"
            elif "express" in norm or "corto" in norm:
                kind = "express"
            else:
                kind = "personal"
            amount = active_flow.get("amount")

        if kind == "express":
            product_type = "DINERO_EXPRESS"
            prod_label = "Dinero Express"
        elif kind == "negocio":
            product_type = "PRESTAMO_NEGOCIO"
            prod_label = "Préstamo para Negocio"
        else:
            product_type = "PRESTAMO_PERSONAL"
            prod_label = "Préstamo Personal"

        if amount is not None:
            term_menu = build_loan_term_menu(product_type, amount)
            term_unit_word = "días" if kind == "express" else "meses"
            reply = f"Gracias. Para tu {prod_label} de ${amount:,.2f} MXN, ¿en cuántos {term_unit_word} te gustaría comparar el pago?"
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "product_type": product_type,
                    "amount": amount,
                    "step": "elegir_plazo",
                    "reply": reply,
                    "menu": term_menu,
                },
            )
            return ("CU-01-DISCOVERY", "ask_loan_details", {"product": prod_label, "amount": amount}, reply, term_menu)
        else:
            if kind == "negocio":
                tenure_reply = (
                    "¡Gran paso! Impulsa tu comercio con financiamiento a tu medida. "
                    "¿Qué antigüedad de operación formal o informal tiene tu negocio actualmente?"
                )
                tenure_menu = build_business_loan_tenure_menu(tenure_reply)
                llama_stack_store.set_active_flow(
                    session_id,
                    {
                        "product": prod_label,
                        "product_type": product_type,
                        "step": "antiguedad_negocio",
                        "reply": tenure_reply,
                        "menu": tenure_menu,
                    },
                )
                return ("CU-FIN-001", "qualify_business_loan_tenure", {"product": prod_label}, tenure_reply, tenure_menu)
            amt_menu = build_loan_amount_menu(product_type)
            reply = f"¡Excelente! Para tu {prod_label}, ¿qué cantidad te gustaría revisar?"
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "product_type": product_type,
                    "step": "elegir_monto",
                    "reply": reply,
                    "menu": amt_menu,
                },
            )
            return ("CU-01-DISCOVERY", "ask_loan_details", {"product": prod_label}, reply, amt_menu)

    if norm.startswith("cambiar_monto_"):
        kind = norm.replace("cambiar_monto_", "")
        product_type = "DINERO_EXPRESS" if kind == "express" else ("PRESTAMO_NEGOCIO" if kind == "negocio" else "PRESTAMO_PERSONAL")
        amt_menu = build_loan_amount_menu(product_type)
        reply = "¿Qué cantidad te gustaría revisar ahora?"
        return ("CU-01-DISCOVERY", "ask_loan_details", {"step": "cambiar_monto"}, reply, amt_menu)

    if norm.startswith("cambiar_plazo_"):
        parts = norm.split("_")
        kind = parts[2] if len(parts) > 2 else "personal"
        amount = float(parts[3]) if len(parts) > 3 else (active_flow.get("amount") or 10000.0)
        product_type = "DINERO_EXPRESS" if kind == "express" else ("PRESTAMO_NEGOCIO" if kind == "negocio" else "PRESTAMO_PERSONAL")
        term_menu = build_loan_term_menu(product_type, amount)
        reply = f"¿En qué plazo prefieres comparar los pagos para ${amount:,.2f} MXN?"
        return ("CU-01-DISCOVERY", "ask_loan_details", {"step": "cambiar_plazo"}, reply, term_menu)

    monto_discovery_match = re.match(r"^monto_(express|personal|negocio)_(\d+)$", norm)
    active_is_amount_step = active_flow.get("step") == "elegir_monto"
    explicit_amount = _extract_explicit_amount(user_text)

    if monto_discovery_match or (active_is_amount_step and explicit_amount is not None):
        if monto_discovery_match:
            kind, amt_str = monto_discovery_match.groups()
            amount = float(amt_str)
        else:
            amount = explicit_amount
            prod_type_act = active_flow.get("product_type", "PRESTAMO_PERSONAL")
            kind = "express" if prod_type_act == "DINERO_EXPRESS" else ("negocio" if prod_type_act == "PRESTAMO_NEGOCIO" else "personal")

        if kind == "express":
            product_type = "DINERO_EXPRESS"
            prod_label = "Dinero Express"
        elif kind == "negocio":
            product_type = "PRESTAMO_NEGOCIO"
            prod_label = "Préstamo para Negocio"
        else:
            product_type = "PRESTAMO_PERSONAL"
            prod_label = "Préstamo Personal"

        term_menu = build_loan_term_menu(product_type, amount)
        term_unit_word = "días" if kind == "express" else "meses"
        reply = f"Gracias. Para tu {prod_label} de ${amount:,.2f} MXN, ¿en cuántos {term_unit_word} te gustaría comparar el pago?"
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": prod_label,
                "product_type": product_type,
                "amount": amount,
                "step": "elegir_plazo",
                "reply": reply,
                "menu": term_menu,
            },
        )
        return ("CU-01-DISCOVERY", "ask_loan_details", {"product": prod_label, "amount": amount}, reply, term_menu)

    term_match = re.match(r"^plazo_(personal|negocio|express)_(\d+)(m|d)_(\d+)$", norm)
    active_is_term_step = active_flow.get("step") == "elegir_plazo"
    text_month_match = re.search(r"\b(\d{1,2})\s*mes", norm)
    text_day_match = re.search(r"\b(7|14|21|28)\s*dia", norm)

    if term_match or (active_is_term_step and (text_month_match or text_day_match)):
        if term_match:
            kind, num_str, unit, amt_str = term_match.groups()
            term_num = int(num_str)
            term_unit = unit
            amount = float(amt_str)
        else:
            prod_type_act = active_flow.get("product_type", "PRESTAMO_PERSONAL")
            kind = "express" if prod_type_act == "DINERO_EXPRESS" else ("negocio" if prod_type_act == "PRESTAMO_NEGOCIO" else "personal")
            amount = float(active_flow.get("amount", 10000.0))
            if text_day_match:
                term_num = int(text_day_match.group(1))
                term_unit = "d"
            else:
                term_num = int(text_month_match.group(1))
                term_unit = "m"

        product_type = "DINERO_EXPRESS" if kind == "express" or term_unit == "d" else ("PRESTAMO_NEGOCIO" if kind == "negocio" else "PRESTAMO_PERSONAL")
        prod_label = "Dinero Express" if product_type == "DINERO_EXPRESS" else ("Préstamo para Negocio" if product_type == "PRESTAMO_NEGOCIO" else "Préstamo Personal")

        conf_menu = build_loan_confirmation_menu(product_type, amount, term_num, term_unit)
        term_word = f"{term_num} días" if term_unit == "d" else f"{term_num} meses"
        reply = (
            f"Resumen de tu simulación:\n"
            f"• *Producto:* {prod_label}\n"
            f"• *Monto:* ${amount:,.2f} MXN\n"
            f"• *Plazo:* {term_word}\n\n"
            f"¿Así está bien para preparar una simulación?"
        )
        llama_stack_store.set_active_flow(
            session_id,
            {
                "product": prod_label,
                "product_type": product_type,
                "amount": amount,
                "term_num": term_num,
                "term_unit": term_unit,
                "step": "confirmar_simulacion",
                "reply": reply,
                "menu": conf_menu,
            },
        )
        return ("CU-01-DISCOVERY", "ask_loan_details", {"step": "confirmar_simulacion"}, reply, conf_menu)

    confirm_sim_match = re.match(r"^confirmar_sim_(personal|negocio|express)_(\d+)(m|d)_(\d+)$", norm)
    active_is_confirm_step = active_flow.get("step") == "confirmar_simulacion"
    affirmative_words = ["si", "ok", "correcto", "va", "si por favor", "adelante", "preparar", "simular", "de acuerdo", "bien"]
    is_affirmative_confirm = active_is_confirm_step and any(norm == w or norm.startswith(f"{w} ") for w in affirmative_words)

    if confirm_sim_match or is_affirmative_confirm:
        if confirm_sim_match:
            kind, num_str, unit, amt_str = confirm_sim_match.groups()
            term_num = int(num_str)
            term_unit = unit
            amount = float(amt_str)
        else:
            term_num = int(active_flow.get("term_num", 6))
            term_unit = active_flow.get("term_unit", "m")
            amount = float(active_flow.get("amount", 10000.0))
            prod_type_act = active_flow.get("product_type", "PRESTAMO_PERSONAL")
            kind = "express" if prod_type_act == "DINERO_EXPRESS" else ("negocio" if prod_type_act == "PRESTAMO_NEGOCIO" else "personal")

        product_type = "DINERO_EXPRESS" if kind == "express" or term_unit == "d" else ("PRESTAMO_NEGOCIO" if kind == "negocio" else "PRESTAMO_PERSONAL")
        prod_label = "Dinero Express" if product_type == "DINERO_EXPRESS" else ("Préstamo para Negocio" if product_type == "PRESTAMO_NEGOCIO" else "Préstamo Personal")

        term_months = term_num if term_unit == "m" else None
        term_days = term_num if term_unit == "d" else None

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
                term_num=term_num,
                term_unit=term_unit,
            )
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "product_type": product_type,
                    "amount": amount,
                    "term_num": term_num,
                    "term_unit": term_unit,
                    "step": "simulado",
                    "reply": reply,
                    "menu": menu,
                },
            )
            return ("CU-01", "simulate_loan", output, reply, menu)
        except (ValueError, PermissionError) as exc:
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-01", "simulate_loan", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    originate_match = re.match(r"^(?:solicitar|sim|contratar)_(plazo|express|negocio|personal)_(\d+)(m|d)_(\d+)$", norm)
    if originate_match:
        kind, num_str, unit, amt_str = originate_match.groups()
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
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-01-ORIGINATION", "originate_loan_with_scoring", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    is_early_payoff = any(k in norm for k in ["liquidar", "liquidacion anticipada", "liquidar mi credito"])
    if is_early_payoff and "?" not in user_text:
        try:
            quote = get_early_payoff_quote(db, user_identifier)
            llama_stack_store.append_tool_interaction(session_id, "get_early_payoff_quote", {"user_id": user_identifier}, quote)
            reply = (
                f"💳 *Liquidación Anticipada*\n"
                f"Para liquidar tu crédito hoy, el saldo principal pendiente es de *${quote['outstanding_principal']:,.2f} MXN* "
                f"por tus {quote['pending_installments_count']} cuotas restantes, con $0.00 de penalización por pago anticipado. "
                f"¿Deseas aplicar el pago completo?"
            )
            return ("CU-04-QUOTE", "get_early_payoff_quote", quote, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-04-QUOTE", "get_early_payoff_quote", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    is_payment = any(
        k in norm
        for k in [
            "menu_hacer_abono",
            "hacer un abono",
            "confirmar un pago",
            "realice mi pago",
            "hice un pago",
            "registrar pago",
            "conciliar pago",
            "pague por spei",
            "pague en oxxo",
            "abono",
            "abone",
        ]
    )
    if is_payment:
        ref_match = re.search(r"\b([a-zA-Z0-9]{8,30})\b", user_text)
        found_ref = None
        if ref_match:
            candidate = ref_match.group(1)
            if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
                found_ref = candidate

        text_without_ref = user_text.replace(found_ref, "") if found_ref else user_text
        payment_amount = _extract_explicit_amount(text_without_ref)

        if found_ref and payment_amount:
            method = "EFECTIVO_OXXO" if "oxxo" in norm else "SPEI"
            args = {
                "user_id": user_identifier,
                "amount": payment_amount,
                "payment_method": method,
                "bank_reference": found_ref,
                "is_early_payoff": False,
            }
            try:
                output = reconcile_payment_in_db(
                    db=db,
                    user_identifier=user_identifier,
                    amount=payment_amount,
                    payment_method=method,
                    bank_reference=found_ref,
                    is_early_payoff=False,
                )
                llama_stack_store.append_tool_interaction(session_id, "reconcile_payment", args, output)
                reply = format_hsm_template("pago_conciliado_comprobante", output)
                return ("CU-04", "reconcile_payment", output, reply, build_whatsapp_interactive_menu(reply))
            except ValueError as exc:
                friendly = _friendly_error(exc, user_identifier)
                return ("CU-04", "reconcile_payment", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))
        else:
            reply = "Compárteme la referencia o clave de rastreo y el monto de tu pago para que podamos revisarlo en el sistema."
            return ("CU-04-PAYMENT", "ask_payment_details", {}, reply, build_whatsapp_interactive_menu(reply))

    is_dispute = any(
        d in norm for d in ["cargo no reconocido", "no reconozco", "menu_seguir_folio", "seguir folio"]
    )
    if is_dispute:
        dispute_amount = _extract_explicit_amount(user_text)
        if dispute_amount:
            try:
                output = get_account_statement_from_db(
                    db=db,
                    user_identifier=user_identifier,
                    register_dispute_amount=dispute_amount,
                )
                folio = f"FOL-{output['contract_id'][-4:].upper()}"
                llama_stack_store.append_tool_interaction(session_id, "get_account_statement", {"register_dispute_amount": dispute_amount}, output)
                reply = (
                    f"Siento la situación. Registramos tu reporte con el folio *{folio}*.\n"
                    f"• Monto protegido: *${dispute_amount:,.2f} MXN* en aclaración.\n"
                    f"• No te será exigible ni generará intereses durante la revisión (hasta 45 días hábiles)."
                )
                return ("CU-03", "get_account_statement", output, reply, build_whatsapp_interactive_menu(reply))
            except ValueError as exc:
                friendly = _friendly_error(exc, user_identifier)
                return ("CU-03", "get_account_statement", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))
        else:
            reply = "Siento mucho lo ocurrido. Por favor compárteme el monto y la fecha aproximada del cargo que no reconoces para registrar tu reporte."
            return ("CU-03-DISPUTE", "ask_dispute_details", {}, reply, build_whatsapp_interactive_menu(reply))

    is_account_statement = any(
        k in norm
        for k in [
            "menu_estado_cuenta",
            "estado de cuenta",
            "corte mensual",
            "saldo disponible",
            "cuanto debo",
            "pago minimo",
            "fecha limite de pago",
        ]
    )
    if is_account_statement:
        try:
            output = get_account_statement_from_db(
                db=db,
                user_identifier=user_identifier,
            )
            llama_stack_store.append_tool_interaction(session_id, "get_account_statement", {"user_id": user_identifier}, output)
            reply = format_hsm_template("finanzas_corte_mensual", output)
            return ("CU-03", "get_account_statement", output, reply, build_whatsapp_interactive_menu(reply))
        except ValueError as exc:
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-03", "get_account_statement", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    if any(
        k in norm
        for k in [
            "menu_validar_contrato",
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
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-02", "validate_identity_contract", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    is_explicit_direct_simulation = (
        (norm.startswith("simula ") or norm.startswith("cotiza "))
        and explicit_amount is not None
        and (text_month_match or text_day_match)
    )
    if is_explicit_direct_simulation:
        amount = explicit_amount
        if "negocio" in norm:
            product_type = "PRESTAMO_NEGOCIO"
            prod_label = "Préstamo para Negocio"
        elif "express" in norm or text_day_match:
            product_type = "DINERO_EXPRESS"
            prod_label = "Dinero Express"
        else:
            product_type = "PRESTAMO_PERSONAL"
            prod_label = "Préstamo Personal"

        term_months = int(text_month_match.group(1)) if text_month_match else (None if product_type == "DINERO_EXPRESS" else 6)
        term_days = int(text_day_match.group(1)) if text_day_match else (14 if product_type == "DINERO_EXPRESS" else None)
        term_num = term_days if product_type == "DINERO_EXPRESS" else (term_months or 6)
        term_unit = "d" if product_type == "DINERO_EXPRESS" else "m"

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
                term_num=term_num,
                term_unit=term_unit,
            )
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "product": prod_label,
                    "product_type": product_type,
                    "amount": amount,
                    "term_num": term_num,
                    "term_unit": term_unit,
                    "step": "simulado",
                    "reply": reply,
                    "menu": menu,
                },
            )
            return ("CU-01", "simulate_loan", output, reply, menu)
        except (ValueError, PermissionError) as exc:
            friendly = _friendly_error(exc, user_identifier)
            return ("CU-01", "simulate_loan", {"error": str(exc)}, friendly, build_whatsapp_interactive_menu(friendly))

    has_loan_intent = (
        any(
            k in norm
            for k in [
                "menu_solicitar_prestamo",
                "menu_dinero_express",
                "solicitar prestamo",
                "prestamo",
                "prestas",
                "prestar",
                "credito",
                "dinero express",
                "express money",
                "tabla de amortizacion",
            ]
        )
        or explicit_amount is not None
    ) and "?" not in user_text and not any(
        excluded in norm
        for excluded in [
            "tasa",
            "cat",
            "moratorio",
            "atras",
            "bloque",
            "requisitos",
            "comprobante",
            "hipotec",
            "playa",
        ]
    )

    if has_loan_intent:
        if explicit_amount is not None:
            amount = explicit_amount
            prompt_reply = f"Con gusto. ¿El préstamo de ${amount:,.2f} MXN sería para un gasto personal o para tu negocio?"
            purpose_menu = build_loan_purpose_menu(amount=amount, body_text=prompt_reply)
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "step": "descubrimiento_proposito",
                    "amount": amount,
                    "reply": prompt_reply,
                    "menu": purpose_menu,
                },
            )
            return (
                "CU-01-DISCOVERY",
                "ask_loan_details",
                {"step": "descubrimiento_proposito", "amount": amount},
                prompt_reply,
                purpose_menu,
            )
        else:
            prompt_reply = "¡Claro que sí! Con gusto te ayudo 😊. ¿El préstamo sería para un gasto personal o para tu negocio?"
            purpose_menu = build_loan_purpose_menu(amount=None, body_text=prompt_reply)
            llama_stack_store.set_active_flow(
                session_id,
                {
                    "step": "descubrimiento_proposito",
                    "amount": None,
                    "reply": prompt_reply,
                    "menu": purpose_menu,
                },
            )
            return (
                "CU-01-DISCOVERY",
                "ask_loan_details",
                {"step": "descubrimiento_proposito"},
                prompt_reply,
                purpose_menu,
            )

    return None

