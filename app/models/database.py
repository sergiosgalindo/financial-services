import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

DEFAULT_SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "fintech.db",
)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

MEXICO_VAT_RATE = Decimal("0.16")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(64), primary_key=True, default=lambda: f"usr-{uuid.uuid4().hex[:8]}")
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    whatsapp_phone = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(150), unique=True, nullable=False)
    tax_id_rfc = Column(String(13), unique=True, nullable=False)
    credit_score = Column(Integer, default=650)
    account_status = Column(String(30), nullable=False, default="ACTIVO")
    opt_in_whatsapp = Column(Boolean, default=False)
    opt_in_calls = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    credit_accounts = relationship("CreditAccount", back_populates="user", cascade="all, delete-orphan")
    communication_logs = relationship("CommunicationLog", back_populates="user", cascade="all, delete-orphan")


class FinancialProduct(Base):
    __tablename__ = "financial_products"

    product_id = Column(Integer, primary_key=True, autoincrement=True)
    product_name = Column(String(100), nullable=False)
    product_type = Column(String(30), nullable=False, unique=True)
    annual_interest_rate = Column(Numeric(5, 2), nullable=False)
    average_cat = Column(Numeric(5, 2), nullable=False)
    min_term_days = Column(Integer, nullable=False)
    max_term_days = Column(Integer, nullable=False)
    active = Column(Boolean, default=True)


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    contract_id = Column(String(64), primary_key=True, default=lambda: f"ctr-{uuid.uuid4().hex[:8]}")
    user_id = Column(String(64), ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("financial_products.product_id"), nullable=False)
    approved_credit_line = Column(Numeric(12, 2), nullable=False)
    available_balance = Column(Numeric(12, 2), nullable=False)
    retained_balance = Column(Numeric(12, 2), default=Decimal("0.00"))
    credit_status = Column(String(30), nullable=False, default="PREAPROBADO", index=True)
    approval_date = Column(DateTime(timezone=True), nullable=True)
    expiration_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="credit_accounts")
    product = relationship("FinancialProduct")
    installments = relationship("AmortizationInstallment", back_populates="credit_account", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="credit_account", cascade="all, delete-orphan")


class AmortizationInstallment(Base):
    __tablename__ = "amortization_installments"

    installment_id = Column(String(64), primary_key=True, default=lambda: f"inst-{uuid.uuid4().hex[:8]}")
    contract_id = Column(String(64), ForeignKey("credit_accounts.contract_id", ondelete="CASCADE"), nullable=False, index=True)
    installment_number = Column(Integer, nullable=False)
    principal_amount = Column(Numeric(10, 2), nullable=False)
    interest_amount = Column(Numeric(10, 2), nullable=False)
    vat_amount = Column(Numeric(10, 2), nullable=False)
    total_installment_amount = Column(Numeric(10, 2), nullable=False)
    due_date = Column(Date, nullable=False, index=True)
    payment_status = Column(String(20), nullable=False, default="PENDIENTE", index=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    credit_account = relationship("CreditAccount", back_populates="installments")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String(64), primary_key=True, default=lambda: f"txn-{uuid.uuid4().hex[:8]}")
    contract_id = Column(String(64), ForeignKey("credit_accounts.contract_id"), nullable=False, index=True)
    transaction_type = Column(String(30), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(30), nullable=True)
    bank_reference = Column(String(100), nullable=True)
    transaction_status = Column(String(20), nullable=False, default="EXITOSA")
    transaction_date = Column(DateTime(timezone=True), default=utc_now)

    credit_account = relationship("CreditAccount", back_populates="transactions")


class CommunicationLog(Base):
    __tablename__ = "communication_logs"

    log_id = Column(String(64), primary_key=True, default=lambda: f"log-{uuid.uuid4().hex[:8]}")
    user_id = Column(String(64), ForeignKey("users.user_id"), nullable=False, index=True)
    contract_id = Column(String(64), ForeignKey("credit_accounts.contract_id"), nullable=True)
    channel = Column(String(20), nullable=False)
    use_case_code = Column(String(50), nullable=False)
    hsm_template_name = Column(String(100), nullable=True)
    delivery_status = Column(String(30), nullable=False)
    pdf_filename = Column(String(255), nullable=True)
    s3_storage_path = Column(String(500), nullable=True)
    provider_tracking_id = Column(String(100), nullable=True)
    sent_at = Column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", back_populates="communication_logs")


class RagKnowledgeChunk(Base):
    __tablename__ = "rag_knowledge_chunks"

    chunk_id = Column(Integer, primary_key=True, autoincrement=True)
    source_document = Column(String(100), nullable=False)
    section_title = Column(String(150), nullable=False)
    content_text = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def normalize_phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]
    return digits


def build_pdf_encryption_metadata(
    tax_id_rfc: str,
    whatsapp_phone: str,
    document_prefix: str,
    reference_id: str,
) -> Dict[str, str]:
    clean_rfc = (tax_id_rfc or "XXXX").strip().upper()[:4]
    clean_phone = re.sub(r"\D", "", whatsapp_phone or "0000")[-4:]
    password_rule = f"{clean_rfc}{clean_phone}"
    filename = f"{document_prefix}_{reference_id}.pdf"
    s3_path = f"s3://fintech-secure-docs-prod/{document_prefix.lower()}/{filename}"
    return {
        "pdf_filename": filename,
        "s3_storage_path": s3_path,
        "encryption_password_hint": "Primeros 4 caracteres de tu RFC en mayúsculas + últimos 4 dígitos de tu celular registrado",
        "derived_password_preview": password_rule,
    }


def _round_currency(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_french_amortization(
    requested_amount: float,
    product_type: str,
    annual_interest_rate: float,
    term_months: Optional[int] = None,
    term_days: Optional[int] = None,
    start_date: Optional[date] = None,
) -> Dict[str, Any]:
    principal = Decimal(str(requested_amount))
    annual_rate = Decimal(str(annual_interest_rate)) / Decimal("100")
    base_date = start_date or date.today()

    if product_type == "PRESTAMO_PERSONAL":
        periods = int(term_months or 6)
        period_rate = annual_rate / Decimal("12")
        step_days = 30
    elif product_type == "DINERO_EXPRESS":
        days = int(term_days or 14)
        periods = max(1, days // 7)
        period_rate = (annual_rate / Decimal("360")) * Decimal("7")
        step_days = 7
    else:
        periods = int(term_months or 6)
        period_rate = annual_rate / Decimal("12")
        step_days = 30

    effective_rate_with_vat = period_rate * (Decimal("1") + MEXICO_VAT_RATE)
    if effective_rate_with_vat > 0:
        factor = (Decimal("1") + effective_rate_with_vat) ** periods
        fixed_payment = principal * (effective_rate_with_vat * factor) / (factor - Decimal("1"))
    else:
        fixed_payment = principal / Decimal(str(periods))

    fixed_payment = _round_currency(fixed_payment)

    remaining_principal = principal
    schedule: List[Dict[str, Any]] = []
    total_interest = Decimal("0.00")
    total_vat = Decimal("0.00")
    total_paid = Decimal("0.00")

    for number in range(1, periods + 1):
        interest_part = _round_currency(remaining_principal * period_rate)
        vat_part = _round_currency(interest_part * MEXICO_VAT_RATE)

        if number == periods:
            principal_part = _round_currency(remaining_principal)
            installment_total = _round_currency(principal_part + interest_part + vat_part)
        else:
            principal_part = _round_currency(fixed_payment - interest_part - vat_part)
            if principal_part > remaining_principal:
                principal_part = _round_currency(remaining_principal)
            installment_total = _round_currency(principal_part + interest_part + vat_part)

        remaining_principal = _round_currency(max(Decimal("0.00"), remaining_principal - principal_part))
        due = base_date + timedelta(days=step_days * number)

        total_interest += interest_part
        total_vat += vat_part
        total_paid += installment_total

        schedule.append(
            {
                "installment_number": number,
                "principal_amount": float(principal_part),
                "interest_amount": float(interest_part),
                "vat_amount": float(vat_part),
                "total_installment_amount": float(installment_total),
                "remaining_balance": float(remaining_principal),
                "due_date": due.isoformat(),
                "payment_status": "SIMULADA",
            }
        )

    return {
        "product_type": product_type,
        "requested_amount": float(_round_currency(principal)),
        "periods": periods,
        "annual_interest_rate": float(annual_interest_rate),
        "periodic_payment": float(fixed_payment),
        "total_interest": float(_round_currency(total_interest)),
        "total_vat": float(_round_currency(total_vat)),
        "total_to_pay": float(_round_currency(total_paid)),
        "first_due_date": schedule[0]["due_date"] if schedule else base_date.isoformat(),
        "schedule": schedule,
    }


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    seed_initial_data()


def seed_initial_data() -> None:
    with SessionLocal() as db:
        if db.query(FinancialProduct).count() == 0:
            products = [
                FinancialProduct(
                    product_id=1,
                    product_name="Préstamo Personal Clásico",
                    product_type="PRESTAMO_PERSONAL",
                    annual_interest_rate=Decimal("45.50"),
                    average_cat=Decimal("58.20"),
                    min_term_days=30,
                    max_term_days=365,
                    active=True,
                ),
                FinancialProduct(
                    product_id=2,
                    product_name="Dinero Express Microcrédito",
                    product_type="DINERO_EXPRESS",
                    annual_interest_rate=Decimal("36.00"),
                    average_cat=Decimal("44.00"),
                    min_term_days=7,
                    max_term_days=28,
                    active=True,
                ),
                FinancialProduct(
                    product_id=3,
                    product_name="Tarjeta de Crédito Oro",
                    product_type="TARJETA_CREDITO",
                    annual_interest_rate=Decimal("52.00"),
                    average_cat=Decimal("68.40"),
                    min_term_days=30,
                    max_term_days=360,
                    active=True,
                ),
                FinancialProduct(
                    product_id=4,
                    product_name="Cuenta Débito Rendimiento Diario",
                    product_type="TARJETA_DEBITO",
                    annual_interest_rate=Decimal("10.50"),
                    average_cat=Decimal("0.00"),
                    min_term_days=1,
                    max_term_days=365,
                    active=True,
                ),
                FinancialProduct(
                    product_id=5,
                    product_name="Préstamo para Negocio Impulso",
                    product_type="PRESTAMO_NEGOCIO",
                    annual_interest_rate=Decimal("38.00"),
                    average_cat=Decimal("48.50"),
                    min_term_days=90,
                    max_term_days=730,
                    active=True,
                ),
            ]
            db.add_all(products)
            db.commit()
        elif not db.query(FinancialProduct).filter(FinancialProduct.product_type == "PRESTAMO_NEGOCIO").first():
            db.add(
                FinancialProduct(
                    product_id=5,
                    product_name="Préstamo para Negocio Impulso",
                    product_type="PRESTAMO_NEGOCIO",
                    annual_interest_rate=Decimal("38.00"),
                    average_cat=Decimal("48.50"),
                    min_term_days=90,
                    max_term_days=730,
                    active=True,
                )
            )
            db.commit()

        if db.query(User).count() == 0:
            users = [
                User(
                    user_id="usr-carlos-001",
                    first_name="Carlos",
                    last_name="Mendoza",
                    whatsapp_phone="522462168664",
                    email="carlos.mendoza@fintechdemo.mx",
                    tax_id_rfc="MECA850101HDF",
                    credit_score=745,
                    account_status="ACTIVO",
                    opt_in_whatsapp=True,
                    opt_in_calls=True,
                ),
                User(
                    user_id="usr-ana-002",
                    first_name="Ana Sofía",
                    last_name="Garza",
                    whatsapp_phone="525512345678",
                    email="ana.garza@fintechdemo.mx",
                    tax_id_rfc="GASA900514MDF",
                    credit_score=710,
                    account_status="ACTIVO",
                    opt_in_whatsapp=True,
                    opt_in_calls=True,
                ),
                User(
                    user_id="usr-roberto-003",
                    first_name="Roberto",
                    last_name="Vázquez",
                    whatsapp_phone="528187654321",
                    email="roberto.vazquez@fintechdemo.mx",
                    tax_id_rfc="VARO781122NL1",
                    credit_score=580,
                    account_status="BLOQUEADO_RIESGO",
                    opt_in_whatsapp=False,
                    opt_in_calls=False,
                ),
            ]
            db.add_all(users)
            db.commit()

        if db.query(CreditAccount).count() == 0:
            today = date.today()
            accounts = [
                CreditAccount(
                    contract_id="ctr-carlos-001",
                    user_id="usr-carlos-001",
                    product_id=1,
                    approved_credit_line=Decimal("50000.00"),
                    available_balance=Decimal("35000.00"),
                    retained_balance=Decimal("0.00"),
                    credit_status="AL_CORRIENTE",
                    approval_date=utc_now() - timedelta(days=30),
                    expiration_date=utc_now() + timedelta(days=335),
                ),
                CreditAccount(
                    contract_id="ctr-carlos-exp-001",
                    user_id="usr-carlos-001",
                    product_id=2,
                    approved_credit_line=Decimal("15000.00"),
                    available_balance=Decimal("15000.00"),
                    retained_balance=Decimal("0.00"),
                    credit_status="PREAPROBADO",
                    approval_date=utc_now() - timedelta(days=5),
                    expiration_date=utc_now() + timedelta(days=90),
                ),
                CreditAccount(
                    contract_id="ctr-ana-val-002",
                    user_id="usr-ana-002",
                    product_id=1,
                    approved_credit_line=Decimal("30000.00"),
                    available_balance=Decimal("30000.00"),
                    retained_balance=Decimal("0.00"),
                    credit_status="PENDIENTE_VALIDACION",
                    approval_date=utc_now() - timedelta(days=1),
                    expiration_date=utc_now() + timedelta(days=364),
                ),
            ]
            db.add_all(accounts)
            db.commit()

            installments = [
                AmortizationInstallment(
                    installment_id="inst-carlos-001",
                    contract_id="ctr-carlos-001",
                    installment_number=1,
                    principal_amount=Decimal("2200.00"),
                    interest_amount=Decimal("568.75"),
                    vat_amount=Decimal("91.00"),
                    total_installment_amount=Decimal("2859.75"),
                    due_date=today + timedelta(days=10),
                    payment_status="PENDIENTE",
                ),
                AmortizationInstallment(
                    installment_id="inst-carlos-002",
                    contract_id="ctr-carlos-001",
                    installment_number=2,
                    principal_amount=Decimal("2283.42"),
                    interest_amount=Decimal("496.83"),
                    vat_amount=Decimal("79.50"),
                    total_installment_amount=Decimal("2859.75"),
                    due_date=today + timedelta(days=40),
                    payment_status="PENDIENTE",
                ),
            ]
            db.add_all(installments)
            db.commit()

        if db.query(RagKnowledgeChunk).count() == 0:
            chunks = [
                RagKnowledgeChunk(
                    source_document="Contrato_Adhesion_Credito_2026.pdf",
                    section_title="Cláusula 4: Costo Anual Total (CAT) y Tasas de Interés Ordinarias",
                    content_text=(
                        "El Costo Anual Total (CAT) promedio sin IVA para Préstamo Personal Clásico es de 58.20% "
                        "con una tasa de interés ordinaria anual fija de 45.50%. Para Dinero Express Microcrédito, "
                        "el CAT promedio sin IVA es de 44.00% con tasa anual ordinaria fija de 36.00%. "
                        "Los intereses ordinarios causan el 16% de Impuesto al Valor Agregado (IVA) conforme a la LIVA."
                    ),
                ),
                RagKnowledgeChunk(
                    source_document="Contrato_Adhesion_Credito_2026.pdf",
                    section_title="Cláusula 7: Intereses Moratorios y Gastos de Cobranza",
                    content_text=(
                        "En caso de incumplimiento en el pago puntual de cualquier cuota de amortización en su fecha "
                        "límite de pago, el saldo vencido devengará intereses moratorios a razón de multiplicar por "
                        "1.5 veces la tasa de interés ordinaria anual aplicable, calculados diariamente sobre el "
                        "capital vencido más el IVA correspondiente. No se cobran penalizaciones por liquidación anticipada."
                    ),
                ),
                RagKnowledgeChunk(
                    source_document="Manual_Tarjetas_y_MSI_2026.pdf",
                    section_title="Sección 2: Reglas de Meses Sin Intereses (MSI) y Pago Mínimo",
                    content_text=(
                        "Las compras diferidas a Meses Sin Intereses (MSI) de 3, 6, 9 y 12 meses mantienen una tasa "
                        "del 0% siempre que el tarjetahabiente cubra al menos el Pago para no Generar Intereses antes "
                        "de la fecha límite de pago mensual. Si solo se cubre el Pago Mínimo, el saldo revolvente "
                        "no diferido generará intereses ordinarios a la tasa anual de 52.00% más IVA."
                    ),
                ),
                RagKnowledgeChunk(
                    source_document="Politica_Aclaraciones_y_Seguridad_2026.pdf",
                    section_title="Sección 5: Cargos No Reconocidos, Saldo Retenido y Cifrado PDF",
                    content_text=(
                        "Para reportar un cargo no reconocido, el titular dispone de 90 días naturales desde la fecha "
                        "de corte. Durante la investigación (máximo 45 días hábiles), el monto en disputa se registra "
                        "como saldo retenido en tránsito y no es exigible ni genera intereses moratorios. "
                        "Todos los estados de cuenta y contratos en PDF enviados por WhatsApp están protegidos con "
                        "contraseña compuesta por los primeros 4 caracteres del RFC en mayúsculas seguidos de los "
                        "últimos 4 dígitos del teléfono celular registrado."
                    ),
                ),
            ]
            db.add_all(chunks)
            db.commit()


def find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    if not identifier:
        return None
    direct = db.query(User).filter(User.user_id == identifier).first()
    if direct:
        return direct

    norm = normalize_phone_digits(identifier)
    if norm:
        by_exact = db.query(User).filter(User.whatsapp_phone == norm).first()
        if by_exact:
            return by_exact
        if len(norm) >= 10:
            last10 = norm[-10:]
            for candidate in db.query(User).all():
                if normalize_phone_digits(candidate.whatsapp_phone).endswith(last10):
                    return candidate
    return None


def simulate_loan_in_db(
    db: Session,
    user_identifier: str,
    product_type: str,
    requested_amount: float,
    term_months: Optional[int] = None,
    term_days: Optional[int] = None,
) -> Dict[str, Any]:
    user = find_user_by_identifier(db, user_identifier)
    if not user:
        raise ValueError(f"User '{user_identifier}' not found in financial database.")
    if user.account_status != "ACTIVO":
        raise PermissionError(
            f"User account status is '{user.account_status}'. Only 'ACTIVO' accounts can simulate credit."
        )
    if not user.opt_in_whatsapp:
        raise PermissionError(
            "Customer does not have an active WhatsApp opt-in (`opt_in_whatsapp=False`) required for CU-01."
        )

    product = (
        db.query(FinancialProduct)
        .filter(FinancialProduct.product_type == product_type, FinancialProduct.active.is_(True))
        .first()
    )
    if not product:
        raise ValueError(f"Financial product '{product_type}' is not available.")

    credit_account = (
        db.query(CreditAccount)
        .filter(
            CreditAccount.user_id == user.user_id,
            CreditAccount.credit_status.in_(["PREAPROBADO", "ACTIVO", "AL_CORRIENTE"]),
        )
        .order_by(CreditAccount.available_balance.desc())
        .first()
    )
    if not credit_account:
        raise ValueError("Customer has no pre-approved or active credit line available.")

    if product_type != "PRESTAMO_NEGOCIO" and Decimal(str(requested_amount)) > Decimal(str(credit_account.available_balance)):
        raise ValueError(
            f"Requested amount (${requested_amount:,.2f} MXN) exceeds available balance "
            f"(${float(credit_account.available_balance):,.2f} MXN)."
        )

    sim = calculate_french_amortization(
        requested_amount=requested_amount,
        product_type=product_type,
        annual_interest_rate=float(product.annual_interest_rate),
        term_months=term_months,
        term_days=term_days,
    )

    simulation_id = f"sim-{uuid.uuid4().hex[:8]}"
    pdf_meta = build_pdf_encryption_metadata(
        tax_id_rfc=user.tax_id_rfc,
        whatsapp_phone=user.whatsapp_phone,
        document_prefix="Simulacion_Tabla",
        reference_id=simulation_id,
    )

    tracking_id = f"wamid.HBgM{uuid.uuid4().hex[:16]}"
    comm_log = CommunicationLog(
        user_id=user.user_id,
        contract_id=credit_account.contract_id,
        channel="WHATSAPP",
        use_case_code="CU-01",
        hsm_template_name="prestamos_simulacion_pdf",
        delivery_status="ENVIADO",
        pdf_filename=pdf_meta["pdf_filename"],
        s3_storage_path=pdf_meta["s3_storage_path"],
        provider_tracking_id=tracking_id,
    )
    db.add(comm_log)
    db.commit()

    return {
        "simulation_id": simulation_id,
        "user_id": user.user_id,
        "customer_name": f"{user.first_name} {user.last_name}",
        "contract_id": credit_account.contract_id,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "requested_amount": sim["requested_amount"],
        "available_credit_line": float(credit_account.available_balance),
        "annual_interest_rate": float(product.annual_interest_rate),
        "average_cat": float(product.average_cat),
        "periods": sim["periods"],
        "periodic_payment": sim["periodic_payment"],
        "total_interest": sim["total_interest"],
        "total_vat": sim["total_vat"],
        "total_to_pay": sim["total_to_pay"],
        "first_due_date": sim["first_due_date"],
        "schedule": sim["schedule"],
        "pdf_metadata": pdf_meta,
        "hsm_template_name": "prestamos_simulacion_pdf",
        "provider_tracking_id": tracking_id,
    }


def process_ivr_validation_in_db(
    db: Session,
    user_identifier: str,
    contract_id: Optional[str] = None,
    validation_result: str = "VALIDADO",
    otp_code: str = "482910",
    call_sid: Optional[str] = None,
) -> Dict[str, Any]:
    user = find_user_by_identifier(db, user_identifier)
    if not user:
        raise ValueError(f"User '{user_identifier}' not found.")

    query = db.query(CreditAccount).filter(CreditAccount.user_id == user.user_id)
    if contract_id:
        query = query.filter(CreditAccount.contract_id == contract_id)
    account = query.order_by(CreditAccount.created_at.desc()).first()
    if not account:
        raise ValueError("No credit contract found for user.")

    voice_tracking = call_sid or f"CA{uuid.uuid4().hex[:20]}"
    voice_log = CommunicationLog(
        user_id=user.user_id,
        contract_id=account.contract_id,
        channel="LLAMADA_VOZ",
        use_case_code="CU-02",
        hsm_template_name=None,
        delivery_status="CONTESTADA_VALIDADA" if validation_result == "VALIDADO" else "FALLIDA",
        provider_tracking_id=voice_tracking,
    )
    db.add(voice_log)

    pdf_meta = build_pdf_encryption_metadata(
        tax_id_rfc=user.tax_id_rfc,
        whatsapp_phone=user.whatsapp_phone,
        document_prefix="Contrato_Credito",
        reference_id=account.contract_id,
    )

    if validation_result == "VALIDADO":
        account.credit_status = "ACTIVO"
        account.approval_date = utc_now()
        wa_tracking = f"wamid.HBgM{uuid.uuid4().hex[:16]}"
        wa_log = CommunicationLog(
            user_id=user.user_id,
            contract_id=account.contract_id,
            channel="WHATSAPP",
            use_case_code="CU-02",
            hsm_template_name="seguridad_validacion_contrato",
            delivery_status="ENVIADO",
            pdf_filename=pdf_meta["pdf_filename"],
            s3_storage_path=pdf_meta["s3_storage_path"],
            provider_tracking_id=wa_tracking,
        )
        db.add(wa_log)
    else:
        wa_tracking = None

    db.commit()

    return {
        "user_id": user.user_id,
        "customer_name": f"{user.first_name} {user.last_name}",
        "contract_id": account.contract_id,
        "previous_status": "PENDIENTE_VALIDACION",
        "new_credit_status": account.credit_status,
        "validation_result": validation_result,
        "otp_verified": validation_result == "VALIDADO" and bool(otp_code),
        "voice_call_sid": voice_tracking,
        "whatsapp_tracking_id": wa_tracking,
        "hsm_template_name": "seguridad_validacion_contrato" if validation_result == "VALIDADO" else None,
        "pdf_metadata": pdf_meta if validation_result == "VALIDADO" else None,
    }


def get_account_statement_from_db(
    db: Session,
    user_identifier: str,
    register_dispute_amount: Optional[float] = None,
) -> Dict[str, Any]:
    user = find_user_by_identifier(db, user_identifier)
    if not user:
        raise ValueError(f"User '{user_identifier}' not found.")

    account = (
        db.query(CreditAccount)
        .filter(CreditAccount.user_id == user.user_id)
        .order_by(CreditAccount.approved_credit_line.desc())
        .first()
    )
    if not account:
        raise ValueError("No credit account found for user.")

    if register_dispute_amount and register_dispute_amount > 0:
        dispute_dec = _round_currency(Decimal(str(register_dispute_amount)))
        account.retained_balance = _round_currency(Decimal(str(account.retained_balance or 0)) + dispute_dec)
        db.commit()

    pending_installments = (
        db.query(AmortizationInstallment)
        .filter(
            AmortizationInstallment.contract_id == account.contract_id,
            AmortizationInstallment.payment_status.in_(["PENDIENTE", "VENCIDA"]),
        )
        .order_by(AmortizationInstallment.installment_number.asc())
        .all()
    )

    next_installment = pending_installments[0] if pending_installments else None
    minimum_payment = float(next_installment.total_installment_amount) if next_installment else 0.0
    no_interest_payment = float(
        sum((Decimal(str(i.total_installment_amount)) for i in pending_installments[:2]), Decimal("0.00"))
    )
    due_date_str = next_installment.due_date.isoformat() if next_installment else (date.today() + timedelta(days=15)).isoformat()

    pdf_meta = build_pdf_encryption_metadata(
        tax_id_rfc=user.tax_id_rfc,
        whatsapp_phone=user.whatsapp_phone,
        document_prefix="Estado_Cuenta",
        reference_id=f"{account.contract_id}_{date.today().strftime('%Y%m')}",
    )

    tracking_id = f"wamid.HBgM{uuid.uuid4().hex[:16]}"
    comm_log = CommunicationLog(
        user_id=user.user_id,
        contract_id=account.contract_id,
        channel="WHATSAPP",
        use_case_code="CU-03",
        hsm_template_name="finanzas_corte_mensual",
        delivery_status="ENVIADO",
        pdf_filename=pdf_meta["pdf_filename"],
        s3_storage_path=pdf_meta["s3_storage_path"],
        provider_tracking_id=tracking_id,
    )
    db.add(comm_log)
    db.commit()

    return {
        "user_id": user.user_id,
        "customer_name": f"{user.first_name} {user.last_name}",
        "contract_id": account.contract_id,
        "credit_status": account.credit_status,
        "approved_credit_line": float(account.approved_credit_line),
        "available_balance": float(account.available_balance),
        "retained_balance": float(account.retained_balance or 0),
        "cutoff_period": date.today().strftime("%B %Y"),
        "payment_due_date": due_date_str,
        "minimum_payment": minimum_payment,
        "no_interest_payment": no_interest_payment,
        "pending_installments_count": len(pending_installments),
        "pdf_metadata": pdf_meta,
        "hsm_template_name": "finanzas_corte_mensual",
        "provider_tracking_id": tracking_id,
    }


def reconcile_payment_in_db(
    db: Session,
    user_identifier: str,
    amount: float,
    payment_method: str = "SPEI",
    bank_reference: Optional[str] = None,
    is_early_payoff: bool = False,
) -> Dict[str, Any]:
    user = find_user_by_identifier(db, user_identifier)
    if not user:
        raise ValueError(f"User '{user_identifier}' not found.")

    account = (
        db.query(CreditAccount)
        .filter(CreditAccount.user_id == user.user_id)
        .order_by(CreditAccount.approved_credit_line.desc())
        .first()
    )
    if not account:
        raise ValueError("No credit account found for user.")

    payment_dec = _round_currency(Decimal(str(amount)))
    ref = bank_reference or f"SPEI-{uuid.uuid4().hex[:10].upper()}"
    tx_type = "LIQUIDACION_ANTICIPADA" if is_early_payoff else "ABONO_CUOTA"

    transaction = Transaction(
        contract_id=account.contract_id,
        transaction_type=tx_type,
        amount=payment_dec,
        payment_method=payment_method,
        bank_reference=ref,
        transaction_status="EXITOSA",
    )
    db.add(transaction)

    pending_installments = (
        db.query(AmortizationInstallment)
        .filter(
            AmortizationInstallment.contract_id == account.contract_id,
            AmortizationInstallment.payment_status.in_(["PENDIENTE", "VENCIDA"]),
        )
        .order_by(AmortizationInstallment.installment_number.asc())
        .all()
    )

    paid_installment_numbers: List[int] = []
    if is_early_payoff:
        for inst in pending_installments:
            inst.payment_status = "PAGADO"
            inst.paid_at = utc_now()
            paid_installment_numbers.append(inst.installment_number)
        account.available_balance = account.approved_credit_line
        account.credit_status = "LIQUIDADO"
    else:
        if pending_installments:
            first_inst = pending_installments[0]
            first_inst.payment_status = "PAGADO"
            first_inst.paid_at = utc_now()
            paid_installment_numbers.append(first_inst.installment_number)
        new_avail = min(
            Decimal(str(account.approved_credit_line)),
            Decimal(str(account.available_balance)) + payment_dec,
        )
        account.available_balance = _round_currency(new_avail)
        account.credit_status = "AL_CORRIENTE"

    pdf_meta = build_pdf_encryption_metadata(
        tax_id_rfc=user.tax_id_rfc,
        whatsapp_phone=user.whatsapp_phone,
        document_prefix="Comprobante_Pago",
        reference_id=ref,
    )

    wa_tracking = f"wamid.HBgM{uuid.uuid4().hex[:16]}"
    wa_log = CommunicationLog(
        user_id=user.user_id,
        contract_id=account.contract_id,
        channel="WHATSAPP",
        use_case_code="CU-04",
        hsm_template_name="pago_conciliado_comprobante",
        delivery_status="ENVIADO",
        pdf_filename=pdf_meta["pdf_filename"],
        s3_storage_path=pdf_meta["s3_storage_path"],
        provider_tracking_id=wa_tracking,
    )
    db.add(wa_log)

    courtesy_call_sid = None
    if account.credit_status == "LIQUIDADO" and user.opt_in_calls:
        courtesy_call_sid = f"CA{uuid.uuid4().hex[:20]}"
        call_log = CommunicationLog(
            user_id=user.user_id,
            contract_id=account.contract_id,
            channel="LLAMADA_VOZ",
            use_case_code="CU-04",
            hsm_template_name=None,
            delivery_status="CONTESTADA_AGRADECIMIENTO_LIQUIDACION",
            provider_tracking_id=courtesy_call_sid,
        )
        db.add(call_log)

    db.commit()

    return {
        "transaction_id": transaction.transaction_id,
        "user_id": user.user_id,
        "customer_name": f"{user.first_name} {user.last_name}",
        "contract_id": account.contract_id,
        "transaction_type": tx_type,
        "amount_paid": float(payment_dec),
        "payment_method": payment_method,
        "bank_reference": ref,
        "paid_installments": paid_installment_numbers,
        "new_available_balance": float(account.available_balance),
        "new_credit_status": account.credit_status,
        "pdf_metadata": pdf_meta,
        "hsm_template_name": "pago_conciliado_comprobante",
        "whatsapp_tracking_id": wa_tracking,
        "courtesy_voice_call_sid": courtesy_call_sid,
    }


def list_customers_overview(db: Session) -> List[Dict[str, Any]]:
    users = db.query(User).order_by(User.created_at.asc()).all()
    results: List[Dict[str, Any]] = []
    for u in users:
        accounts = [
            {
                "contract_id": acc.contract_id,
                "product_id": acc.product_id,
                "approved_credit_line": float(acc.approved_credit_line),
                "available_balance": float(acc.available_balance),
                "retained_balance": float(acc.retained_balance or 0),
                "credit_status": acc.credit_status,
            }
            for acc in u.credit_accounts
        ]
        recent_logs = (
            db.query(CommunicationLog)
            .filter(CommunicationLog.user_id == u.user_id)
            .order_by(CommunicationLog.sent_at.desc())
            .limit(5)
            .all()
        )
        results.append(
            {
                "user_id": u.user_id,
                "full_name": f"{u.first_name} {u.last_name}",
                "whatsapp_phone": u.whatsapp_phone,
                "email": u.email,
                "tax_id_rfc": u.tax_id_rfc,
                "credit_score": u.credit_score,
                "account_status": u.account_status,
                "opt_in_whatsapp": u.opt_in_whatsapp,
                "opt_in_calls": u.opt_in_calls,
                "credit_accounts": accounts,
                "recent_communications": [
                    {
                        "log_id": lg.log_id,
                        "channel": lg.channel,
                        "use_case_code": lg.use_case_code,
                        "hsm_template_name": lg.hsm_template_name,
                        "delivery_status": lg.delivery_status,
                        "pdf_filename": lg.pdf_filename,
                    }
                    for lg in recent_logs
                ],
            }
        )
    return results


def evaluate_credit_scoring_and_originate_loan(
    db: Session,
    user_identifier: str,
    product_type: str,
    requested_amount: float,
    term_months: Optional[int] = None,
    term_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes the internal Credit Scoring & Risk Evaluation pipeline:
    1. Checks customer credit_score and account_status.
    2. Inspects pending and overdue installments across active credit accounts.
    3. Approves & disperses (inserting AmortizationInstallment + DISPERSION Transaction),
       places under evaluation (PENDIENTE_VALIDACION), or rejects with reason.
    """
    user = find_user_by_identifier(db, user_identifier)
    if not user:
        raise ValueError(f"User '{user_identifier}' not found.")

    product = (
        db.query(FinancialProduct)
        .filter(FinancialProduct.product_type == product_type, FinancialProduct.active.is_(True))
        .first()
    )
    if not product:
        raise ValueError(f"Financial product '{product_type}' not found.")

    accounts = (
        db.query(CreditAccount)
        .filter(CreditAccount.user_id == user.user_id)
        .order_by(CreditAccount.available_balance.desc())
        .all()
    )
    primary_account = accounts[0] if accounts else None

    contract_ids = [acc.contract_id for acc in accounts]
    pending_installments: List[AmortizationInstallment] = []
    overdue_installments: List[AmortizationInstallment] = []
    if contract_ids:
        all_unpaid = (
            db.query(AmortizationInstallment)
            .filter(
                AmortizationInstallment.contract_id.in_(contract_ids),
                AmortizationInstallment.payment_status.in_(["PENDIENTE", "VENCIDA"]),
            )
            .all()
        )
        pending_installments = [i for i in all_unpaid if i.payment_status == "PENDIENTE"]
        overdue_installments = [i for i in all_unpaid if i.payment_status == "VENCIDA"]

    total_pending_debt = float(
        sum((Decimal(str(i.total_installment_amount)) for i in pending_installments + overdue_installments), Decimal("0.00"))
    )
    avail_balance = float(primary_account.available_balance) if primary_account else 0.0
    score = int(user.credit_score or 0)

    sim = calculate_french_amortization(
        requested_amount=requested_amount,
        product_type=product_type,
        annual_interest_rate=float(product.annual_interest_rate),
        term_months=term_months,
        term_days=term_days,
    )

    if user.account_status != "ACTIVO" or score < 620:
        reason = (
            f"Score crediticio insuficiente ({score} pts) o estatus de cuenta ({user.account_status})"
        )
        decision = "RECHAZADO"
    elif len(overdue_installments) > 0:
        reason = f"Tienes {len(overdue_installments)} cuota(s) vencida(s) pendiente(s) de pago"
        decision = "RECHAZADO"
    elif (
        not primary_account
        or (
            product_type != "PRESTAMO_NEGOCIO"
            and Decimal(str(requested_amount)) > Decimal(str(primary_account.available_balance))
        )
    ):
        reason = (
            f"El monto solicitado (${requested_amount:,.2f} MXN) supera tu disponible actual "
            f"(${avail_balance:,.2f} MXN)"
        )
        decision = "RECHAZADO"
    elif (
        score < 720
        or requested_amount > 20000
        or product_type == "PRESTAMO_NEGOCIO"
        or len(pending_installments) >= 10
    ):
        reason = (
            f"Revisión crediticia requerida (Score: {score} pts, "
            f"{len(pending_installments)} cuotas vigentes por ${total_pending_debt:,.2f} MXN)"
        )
        decision = "EN_EVALUACION"
    else:
        reason = "Aprobación automática por buen historial crediticio y capacidad de pago"
        decision = "APROBADO_DEPOSITADO"

    bank_ref = None
    new_contract_id = primary_account.contract_id if primary_account else f"ctr-{uuid.uuid4().hex[:8]}"

    if decision == "APROBADO_DEPOSITADO" and primary_account:
        req_dec = _round_currency(Decimal(str(requested_amount)))
        primary_account.available_balance = _round_currency(
            max(Decimal("0.00"), Decimal(str(primary_account.available_balance)) - req_dec)
        )
        primary_account.credit_status = "ACTIVO"
        primary_account.approval_date = utc_now()

        existing_max_num = len(pending_installments)
        for idx, item in enumerate(sim["schedule"], start=1):
            db.add(
                AmortizationInstallment(
                    contract_id=primary_account.contract_id,
                    installment_number=existing_max_num + idx,
                    principal_amount=Decimal(str(item["principal_amount"])),
                    interest_amount=Decimal(str(item["interest_amount"])),
                    vat_amount=Decimal(str(item["vat_amount"])),
                    total_installment_amount=Decimal(str(item["total_installment_amount"])),
                    due_date=date.fromisoformat(item["due_date"]),
                    payment_status="PENDIENTE",
                )
            )

        bank_ref = f"SPEI-DISP-{uuid.uuid4().hex[:8].upper()}"
        db.add(
            Transaction(
                contract_id=primary_account.contract_id,
                transaction_type="DISPERSION",
                amount=req_dec,
                payment_method="SPEI",
                bank_reference=bank_ref,
                transaction_status="EXITOSA",
            )
        )
        avail_balance = float(primary_account.available_balance)

    elif decision == "EN_EVALUACION" and primary_account:
        primary_account.credit_status = "PENDIENTE_VALIDACION"

    db.add(
        CommunicationLog(
            user_id=user.user_id,
            contract_id=primary_account.contract_id if primary_account else None,
            channel="WHATSAPP",
            use_case_code="CU-01-ORIGINATION",
            hsm_template_name=f"prestamo_{decision.lower()}",
            delivery_status="ENVIADO",
            provider_tracking_id=f"wamid.orig.{uuid.uuid4().hex[:12]}",
        )
    )
    db.commit()

    return {
        "decision": decision,
        "reason": reason,
        "user_id": user.user_id,
        "customer_name": f"{user.first_name} {user.last_name}",
        "credit_score": score,
        "pending_installments_count": len(pending_installments),
        "overdue_installments_count": len(overdue_installments),
        "total_pending_debt": total_pending_debt,
        "contract_id": new_contract_id,
        "product_name": product.product_name,
        "product_type": product.product_type,
        "requested_amount": float(requested_amount),
        "periods": sim["periods"],
        "periodic_payment": sim["periodic_payment"],
        "total_to_pay": sim["total_to_pay"],
        "first_due_date": sim["first_due_date"],
        "bank_reference": bank_ref,
        "new_available_balance": avail_balance,
    }

