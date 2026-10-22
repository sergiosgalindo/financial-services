# Changelog

## [1.0.0] - 2026-10-20

### Added
- Initialized Spec-Driven Development feature `20261020-fintech-omnichannel-assistant`.
- Implemented 7 SQLAlchemy relational models (`User`, `FinancialProduct`, `CreditAccount`, `AmortizationInstallment`, `Transaction`, `CommunicationLog`, `RagKnowledgeChunk`) with automatic seeding in `app/models/database.py`.
- Implemented Fintech Use Cases `CU-01` (Loan Simulation & French Amortization), `CU-02` (IVR OTP Contract Validation), `CU-03` (Monthly Account Statement & Unrecognized Charge Retention), and `CU-04` (SPEI/OXXO Payment Reconciliation & Early Payoff Call Logging).
- Added Llama Stack conversation memory (`LlamaStackClientAdapter`) and Function Calling router in `app/models/llama_stack_store.py`.
- Added Two-Layer Defense in Depth (`Prompt Guard` + `Llama Guard`) in `app/models/safety.py`.
- Added Semantic RAG (`SentenceTransformer`) over `knowledge_base.json` and database chunks in `app/models/assistant.py`.
- Added Meta WhatsApp Cloud API webhook orchestrator (`GET /webhook`, `POST /webhook`, `POST /v1/webhooks/whatsapp`) in `app/models/whatsapp.py`.
- Built responsive Bootstrap 5 Fintech Console in `web/` and integration test suite in `tests/test_app_integration.py`.
