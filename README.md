# Fintech Omnichannel Assistant (`servicios-financieros`)

Production-ready Financial Services Orchestrator built with **FastAPI (MVC)**, **SQLAlchemy 2.0 Relational Database**, **Meta WhatsApp Cloud API**, **Llama (`llama3.1:8b`)**, **Semantic RAG (`SentenceTransformer`)**, **Llama Stack Conversation Memory**, and **Two-Layer Defense in Depth (`Prompt Guard` + `Llama Guard`)**.

## Key Capabilities

1. **Conversational Dialog Engine & Meta WhatsApp Compliance:**
   - **Flow A (Guided Loan Discovery & Origination):** Purpose selection (Personal / Business), tenure qualification, tolerant term parsing (supports bare numbers like `10` or natural language `10 meses`), simulation confirmation, French amortization breakdown, and scoring-based contract origination.
   - **Flow B (RAG Interruption & Contextual Resumption):** Answers policy questions within 400 characters, preserves active session context, and seamlessly resumes with affirmative text (`si`, `claro`, `por favor`).
   - **Meta WhatsApp Constraints:** Interactive list menus compliant with Meta character limits (buttons <= 20 chars, titles <= 24 chars, descriptions <= 72 chars).

2. **Relational Core Database (7 SQLAlchemy Models):**
   - `users`: Customer profile, normalized WhatsApp phone, RFC, credit score, account status, and `opt_in_whatsapp` / `opt_in_calls`.
   - `financial_products`: `PRESTAMO_PERSONAL` (45.50% APR / 58.20% CAT), `DINERO_EXPRESS` (36.00% APR / 44.00% CAT), `TARJETA_CREDITO`, and `TARJETA_DEBITO`.
   - `credit_accounts`: Pre-approved and active credit lines (`PREAPROBADO`, `PENDIENTE_VALIDACION`, `ACTIVO`, `AL_CORRIENTE`, `ATRASADO`, `LIQUIDADO`).
   - `amortization_installments`: Scheduled installments with principal, ordinary interest, and `16%` Mexican VAT (`IVA`).
   - `transactions`: Ledger for `DISPERSION`, `ABONO_CUOTA`, `LIQUIDACION_ANTICIPADA`, and `RENDIMIENTO_DIARIO`.
   - `communication_logs`: Omnichannel audit trail (`WHATSAPP` and `LLAMADA_VOZ`) tracking HSM templates and encrypted PDF paths.
   - `rag_knowledge_chunks`: Database-backed legal clauses synchronized with `knowledge_base.json`.

3. **Four Fintech Use Cases (`CU-01` to `CU-04`) & Function Calling:**
   - **CU-01 (`simulate_loan` / `POST /v1/loans/simulate`):** French fixed-installment amortization calculator for `PRESTAMO_PERSONAL` (1–12 months) and `DINERO_EXPRESS` (7–28 days), generating password-protected PDF metadata (`{RFC[:4]}{PHONE[-4:]}`) and dispatching `prestamos_simulacion_pdf`.
   - **CU-02 (`validate_identity_contract` / `POST /v1/security/ivr-validation`):** IVR OTP identity verification transitioning `PENDIENTE_VALIDACION` contracts to `ACTIVO` and dispatching `seguridad_validacion_contrato`.
   - **CU-03 (`get_account_statement` / `GET /v1/accounts/{user_id}/statement`):** Monthly cut summary (`finanzas_corte_mensual`), available/retained balances, and unrecognized-charge dispute protection.
   - **CU-04 (`reconcile_payment` / `POST /v1/payments/reconcile`):** Real-time `SPEI` and `EFECTIVO_OXXO` payment reconciliation (`pago_conciliado_comprobante`) plus automated courtesy voice call logging upon `LIQUIDACION_ANTICIPADA`.

4. **Safety, Privacy & Compliance:**
   - **Two-Layer Safety:** `Prompt Guard` (Layer 1) for prompt injection defense; `Llama Guard` (Layer 2) for financial crime/unsafe content filtering.
   - **Sensitive Data Masking:** Automated regex interception protecting NIP, CVV, passwords, and OTP tokens.
   - **Fraud Emergency Routing:** Direct priority escalation to `800-999-2026` upon theft/cloning reports.
   - **Opt-out Management:** Automatic compliance deregistration on `BAJA` / `STOP`.

## Quickstart

### Local Development
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker Compose (API + PostgreSQL with pgvector)
```bash
docker compose up -d --build
```

### Automated Integration Tests
```bash
pytest -v
```

## Documentation
- [Documentación Técnica y Guía de Operación](docs/sistema_arquitectura_y_operacion.md)
- [Especificación de Flujo WhatsApp](flujo_conversacion_whatsapp.md)
- [Contratos de API REST](docs/api-contracts.md)
