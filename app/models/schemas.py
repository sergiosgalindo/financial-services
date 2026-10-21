from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[ChatMessage] = Field(default_factory=list)
    session_id: Optional[str] = Field(default="web-default-session")
    user_id: Optional[str] = Field(default="usr-carlos-001")
    top_k: int = Field(default=3, ge=1, le=5)


class RetrievedSource(BaseModel):
    id: str
    category: str
    question: str
    answer: str
    score: float


class ChatResponse(BaseModel):
    reply: str
    sources: List[RetrievedSource] = Field(default_factory=list)
    model: str
    used_fallback: bool = False
    safety_blocked: bool = False
    safety_reason: Optional[str] = None
    session_id: Optional[str] = None
    active_use_case: Optional[str] = None
    tool_executed: Optional[str] = None
    tool_output: Optional[Dict[str, Any]] = None
    interactive_menu: Optional[Dict[str, Any]] = None
    conversation_items_count: int = 0


class ConversationResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class LoanSimulationRequest(BaseModel):
    user_id: str = Field(..., description="Customer ID or WhatsApp phone number")
    product_type: Literal["PRESTAMO_PERSONAL", "DINERO_EXPRESS"] = Field(default="PRESTAMO_PERSONAL")
    requested_amount: float = Field(..., gt=0)
    term_months: Optional[int] = Field(default=6, ge=1, le=12)
    term_days: Optional[int] = Field(default=None, ge=7, le=28)


class AmortizationInstallmentSchema(BaseModel):
    installment_number: int
    principal_amount: float
    interest_amount: float
    vat_amount: float
    total_installment_amount: float
    remaining_balance: float
    due_date: str
    payment_status: str


class LoanSimulationResponse(BaseModel):
    simulation_id: str
    user_id: str
    customer_name: str
    contract_id: str
    product_name: str
    product_type: str
    requested_amount: float
    available_credit_line: float
    annual_interest_rate: float
    average_cat: float
    periods: int
    periodic_payment: float
    total_interest: float
    total_vat: float
    total_to_pay: float
    first_due_date: str
    schedule: List[AmortizationInstallmentSchema]
    pdf_metadata: Dict[str, str]
    hsm_template_name: str
    provider_tracking_id: str


class IVRValidationRequest(BaseModel):
    user_id: str = Field(..., description="Customer ID or WhatsApp phone number")
    contract_id: Optional[str] = None
    validation_result: Literal["VALIDADO", "RECHAZADO"] = Field(default="VALIDADO")
    otp_code: str = Field(default="482910", min_length=4, max_length=8)
    call_sid: Optional[str] = None


class PaymentWebhookRequest(BaseModel):
    user_id: str = Field(..., description="Customer ID or WhatsApp phone number")
    amount: float = Field(..., gt=0)
    payment_method: Literal["SPEI", "EFECTIVO_OXXO", "INTERNO"] = Field(default="SPEI")
    bank_reference: Optional[str] = None
    is_early_payoff: bool = Field(default=False)
