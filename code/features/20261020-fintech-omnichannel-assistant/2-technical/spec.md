# Technical Specification: Fintech Omnichannel Assistant

## Architecture Impact

- Implements a modular FastAPI MVC application under `app/` backed by SQLAlchemy 2.0 ORM (`sqlite:///./fintech.db` by default, configurable via `DATABASE_URL` for PostgreSQL).
- Integrates `SentenceTransformer` (`paraphrase-multilingual-MiniLM-L12-v2`) with lexical fallback for deterministic and low-latency semantic retrieval over `knowledge_base.json` and database `rag_knowledge_chunks`.
- Embeds a Llama Stack conversation adapter (`LlamaStackClientAdapter`) storing user messages, tool calls (`function_call`), tool outputs (`function_call_output`), and assistant responses.

## Data Model

Seven SQLAlchemy ORM models in `app/models/database.py` mapping 1-to-1 with the relational specification:
- `User` (`users`): `user_id` (UUID string PK), `first_name`, `last_name`, `whatsapp_phone` (unique), `email` (unique), `tax_id_rfc` (unique), `credit_score`, `account_status`, `opt_in_whatsapp`, `opt_in_calls`, `created_at`, `updated_at`.
- `FinancialProduct` (`financial_products`): `product_id` (PK), `product_name`, `product_type` (`PRESTAMO_PERSONAL`, `DINERO_EXPRESS`, `TARJETA_CREDITO`, `TARJETA_DEBITO`), `annual_interest_rate`, `average_cat`, `min_term_days`, `max_term_days`, `active`.
- `CreditAccount` (`credit_accounts`): `contract_id` (UUID string PK), `user_id` (FK), `product_id` (FK), `approved_credit_line`, `available_balance`, `retained_balance`, `credit_status`, `approval_date`, `expiration_date`.
- `AmortizationInstallment` (`amortization_installments`): `installment_id` (UUID string PK), `contract_id` (FK), `installment_number`, `principal_amount`, `interest_amount`, `vat_amount`, `total_installment_amount`, `due_date`, `payment_status`, `paid_at`.
- `Transaction` (`transactions`): `transaction_id` (UUID string PK), `contract_id` (FK), `transaction_type`, `amount`, `payment_method`, `bank_reference`, `transaction_status`, `transaction_date`.
- `CommunicationLog` (`communication_logs`): `log_id` (UUID string PK), `user_id` (FK), `contract_id` (FK), `channel`, `use_case_code`, `hsm_template_name`, `delivery_status`, `pdf_filename`, `s3_storage_path`, `provider_tracking_id`, `sent_at`.
- `RagKnowledgeChunk` (`rag_knowledge_chunks`): `chunk_id` (PK), `source_document`, `section_title`, `content_text`, `updated_at`.

## API / Interfaces

- `POST /v1/loans/simulate`: Validates user status and credit line, calculates French amortization (`16%` VAT on interest), generates encrypted PDF metadata (`{RFC[:4]}{PHONE[-4:]}`), logs `CU-01` (`prestamos_simulacion_pdf`), and returns `LoanSimulationResponse`.
- `POST /v1/security/ivr-validation`: Processes `CU-02` OTP result (`VALIDADO` / `RECHAZADO`), transitions `PENDIENTE_VALIDACION` -> `ACTIVO`, and logs `seguridad_validacion_contrato`.
- `GET /v1/accounts/{user_id}/statement`: Returns `CU-03` monthly statement data and logs `finanzas_corte_mensual` when dispatched.
- `POST /v1/payments/reconcile`: Executes `CU-04` payment application (`ABONO_CUOTA` or `LIQUIDACION_ANTICIPADA`), updates `available_balance`, logs `pago_conciliado_comprobante`, and triggers a `LLAMADA_VOZ` log on full payoff.
- `GET /webhook` & `POST /webhook` (plus `POST /v1/webhooks/whatsapp`): Meta WhatsApp Cloud API verification and asynchronous message processing with `BackgroundTasks`, `wamid` deduplication, per-phone concurrency locks, and phone number normalization.
- `POST /api/chat`, `POST /api/conversation/reset`, `GET /api/health`, `GET /api/diagnostics`, `GET /api/metrics`.

## UI / UX Impact

- Single-page Bootstrap 5 interface in `web/` offering a live chat console, customer selector, interactive CU-01 Loan Simulator, CU-02/CU-04 action triggers, and real-time database/RAG inspection.

## Security

- **Layer 1 (`Prompt Guard`):** Lexical and structural jailbreak/override detector (`is_prompt_injection`).
- **Layer 2 (`Llama Guard`):** Policy safety classifier (`check_llama_guard`) inspecting both user input and assistant output, preventing unauthorized financial advice, tax evasion, fraud, or PII leakage.
- **Document Encryption Metadata:** Password derivation using `{RFC[:4].upper()}{PHONE[-4:]}` for simulated PDF statements and contracts.

## Testing Strategy

- Automated `pytest` integration suite (`tests/test_app_integration.py`) testing all endpoints, database seeding, CU-01 through CU-04 flows, RAG retrieval, Llama Stack memory, safety guardrails, and WhatsApp Cloud API webhooks.

## Risks

- External LLM latency or offline local Ollama: mitigated via deterministic tool fallback synthesis when the upstream LLM is unreachable, ensuring 100% uptime for financial simulations and account queries.
