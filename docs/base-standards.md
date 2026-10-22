# Base Standards

## Language & Code Quality

- All source code, identifiers, database schemas, API contracts, comments, docstrings, and documentation must be written in English.
- User-facing assistant replies and Mexican financial product/contract descriptions remain in Spanish for end-user interaction.
- Use strict type annotations across Python 3.9+ modules and Pydantic v2 models.

## Architecture Principles

- Follow a clean Model-View-Controller (MVC) separation:
  - `app/models/`: Database ORM models, Pydantic schemas, Llama Stack conversation store, Fintech Function Calling tools, Semantic RAG assistant, Two-Layer Safety (`Prompt Guard` + `Llama Guard`), and WhatsApp Cloud API orchestrator.
  - `app/controllers/`: FastAPI route controllers for Chat, WhatsApp Cloud API, and Fintech Core APIs (Loan Simulation, IVR Validation, Payment Webhook).
  - `web/`: Responsive Bootstrap 5 single-page client interface.
- Maintain stateless horizontal scalability by persisting business records in the relational database (`SQLAlchemy`) and multi-turn conversation history in the Llama Stack store (`conversations.create` / `conversations.items.list`).
