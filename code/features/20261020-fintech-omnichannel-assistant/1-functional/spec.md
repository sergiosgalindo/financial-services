# Functional Specification: Fintech Omnichannel Assistant

## Problem

Financial institution customers require instant, accurate, and compliant self-service across WhatsApp and Web to simulate personal and express loans, validate credit contracts via voice/OTP, consult monthly statements or unrecognized charges, reconcile payments (`SPEI`/`OXXO`), and clarify legal contract clauses (`CAT`, ordinary/moratory interest, `MSI`) without hallucinations or security leaks.

## Users

- **Banking Customers (`Usuarios`):** Active and pre-approved customers interacting via WhatsApp Cloud API or the Web Assistant UI.
- **Risk & Operations Analysts:** Staff monitoring communication logs, credit statuses, payment reconciliations, and safety blocks.

## User Stories

- **US-01 (CU-01 Loan Simulation & PDF Quote):** As a customer with an active or pre-approved line, I can simulate a `PRESTAMO_PERSONAL` (1–12 months) or `DINERO_EXPRESS` (7–28 days) loan and receive an exact French amortization schedule along with password-protected PDF metadata (`{RFC[:4]}{PHONE[-4:]}`) via the `prestamos_simulacion_pdf` template.
- **US-02 (CU-02 Contract Identity Validation):** As a customer with a `PENDIENTE_VALIDACION` contract, I can trigger or complete IVR OTP validation (`seguridad_validacion_contrato`) so my credit transitions to `ACTIVO` and my encrypted contract PDF is dispatched.
- **US-03 (CU-03 Monthly Statement & Dispute Guidance):** As an active borrower, I can check my monthly statement summary (`finanzas_corte_mensual`), available balance, and retained balance, or report an unrecognized charge to receive instant RAG-backed dispute steps and provisional retention rules.
- **US-04 (CU-04 Payment Reconciliation & Early Payoff):** As a borrower making a payment via `SPEI` or `EFECTIVO_OXXO`, my installment is marked `PAGADO`, my `available_balance` is updated, I receive a `pago_conciliado_comprobante` receipt, and if I liquidate early (`LIQUIDACION_ANTICIPADA`), an automated thank-you voice call is logged.
- **US-05 (Semantic RAG & Conversational Escalation):** As a user asking about `CAT`, moratory interest, `MSI`, or asking for human agent assistance, I receive grounded answers from `knowledge_base.json` and `rag_knowledge_chunks` without robotic prefixes, or immediate escalation details when requesting a human.

## Acceptance Criteria

1. All 7 relational tables (`users`, `financial_products`, `credit_accounts`, `amortization_installments`, `transactions`, `communication_logs`, `rag_knowledge_chunks`) are automatically initialized and seeded on startup.
2. French amortization calculation accurately computes principal, ordinary interest, and `16%` VAT (`IVA`) for both monthly (`PRESTAMO_PERSONAL`) and daily (`DINERO_EXPRESS`) terms.
3. Every outbound WhatsApp notification verifies `opt_in_whatsapp = True` and records a `communication_logs` entry.
4. Two-layer Defense in Depth (`Prompt Guard` + `Llama Guard`) intercepts prompt injections and unsafe payloads before reaching business tools or the user.
5. Llama Stack (`LlamaStackClientAdapter`) persists `message`, `function_call`, and `function_call_output` items per session/phone number.

## Edge Cases

- Customer with `account_status != 'ACTIVO'` or `opt_in_whatsapp == False` attempting to simulate a loan or receive WhatsApp templates returns a clear compliance error (`403 Forbidden` or descriptive assistant message).
- Duplicate WhatsApp webhook deliveries with the same `wamid` are ignored idempotently.
- Mexican WhatsApp phone numbers (`521...` vs `52...` vs last 10 digits) match existing customer records reliably.

## Out of Scope

- Live core-banking wire transfers over external SPEI rails (simulated via transactional ledger updates).
- External Twilio audio streaming hardware (simulated via IVR webhook and `LLAMADA_VOZ` communication logs).
