# Development Plan

Status: completed

## Tasks

- [x] TASK-001: Create relational database engine, 7 SQLAlchemy ORM models, seed data, and Fintech business operations (`app/models/database.py`)
  - Depends on: none
  - Deliverable: `app/models/database.py` with automatic schema creation, seeded users (including demo and live WhatsApp user), products, credit accounts, installments, RAG chunks, and CU-01..CU-04 persistence methods
  - Validate: database initializes and seeds cleanly in SQLite/PostgreSQL

- [x] TASK-002: Create Pydantic request/response contracts (`app/models/schemas.py`)
  - Depends on: TASK-001
  - Deliverable: Typed schemas for Chat, Loan Simulation (`CU-01`), IVR Validation (`CU-02`), Account Statement (`CU-03`), Payment Reconciliation (`CU-04`), WhatsApp Webhook, Diagnostics, and Metrics
  - Validate: schema validation unit checks pass

- [x] TASK-003: Implement Two-Layer Safety (`app/models/safety.py`) and Llama Stack Conversation Store & Fintech Function Calling (`app/models/llama_stack_store.py`)
  - Depends on: TASK-001, TASK-002
  - Deliverable: `Prompt Guard` + `Llama Guard` checks, `LlamaStackClientAdapter` conversation memory, HSM template builder, PDF password generator, and Fintech tool execution (`simulate_loan`, `get_account_statement`, `initiate_contract_validation`, `record_payment`)
  - Validate: tool calls and safety checks execute deterministically

- [x] TASK-004: Implement Semantic RAG & LLM Assistant (`app/models/assistant.py`) and Financial Knowledge Base (`knowledge_base.json`)
  - Depends on: TASK-003
  - Deliverable: `knowledge_base.json` with Mexican fintech legal clauses (`CAT`, ordinary/moratory interest, `MSI`, unrecognized charge disputes, PDF encryption) and `app/models/assistant.py` combining RAG, Function Calling, and Llama 3.1 generation
  - Validate: RAG queries return high-similarity chunks and grounded Spanish responses

- [x] TASK-005: Implement WhatsApp Cloud API Orchestrator (`app/models/whatsapp.py`) and FastAPI Controllers (`app/controllers/*`, `app/main.py`)
  - Depends on: TASK-004
  - Deliverable: WhatsApp webhook processing (`wamid` deduplication, Mexican `521` phone normalization, opt-in verification, Meta Graph API client), `chat_controller.py`, `fintech_controller.py`, `whatsapp_controller.py`, and `app/main.py`
  - Validate: FastAPI app boots and serves all endpoints

- [x] TASK-006: Build Responsive Bootstrap 5 Fintech Web UI (`web/index.html`, `web/styles.css`, `web/app.js`) and Deployment Artifacts (`Dockerfile`, `requirements.txt`, `README.md`, `CHANGELOG.md`)
  - Depends on: TASK-005
  - Deliverable: Interactive Web UI with Chat, Loan Simulator, Customer Inspector, and English project documentation
  - Validate: `GET /` serves the UI and static assets

- [x] TASK-007: Create and run comprehensive integration tests (`tests/test_app_integration.py`)
  - Depends on: TASK-006
  - Deliverable: Automated `pytest` suite covering CU-01..CU-04, RAG, Database, Safety, Llama Stack memory, and WhatsApp webhooks
  - Validate: `pytest -v` passes 100%
