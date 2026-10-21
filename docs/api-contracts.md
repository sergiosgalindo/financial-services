# API Contracts

## Core Endpoints

| Method | Path | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Health check returning status, LLM configuration, and database readiness |
| `GET` | `/api/diagnostics` | Full system diagnostics including DB tables, RAG chunks, safety status, and WhatsApp configuration |
| `GET` | `/api/metrics` | Production latency (`avg`, `p95`, `max`) and request counter metrics |
| `POST` | `/api/chat` | Interactive chat endpoint supporting RAG, Fintech Function Calling, Llama Stack memory, and Safety |
| `POST` | `/api/conversation/reset` | Clears conversation history in Llama Stack for a session or phone number |
| `GET` | `/webhook` | Meta WhatsApp Cloud API webhook verification challenge (`hub.mode`, `hub.verify_token`, `hub.challenge`) |
| `POST` | `/webhook` | Meta WhatsApp Cloud API incoming event handler with `BackgroundTasks` and `wamid` deduplication |
| `POST` | `/v1/webhooks/whatsapp` | Direct WhatsApp webhook endpoint for omnichannel router integration |
| `POST` | `/v1/loans/simulate` | CU-01 Loan Simulation (`PRESTAMO_PERSONAL` & `DINERO_EXPRESS`) with French amortization and encrypted PDF metadata |
| `POST` | `/v1/security/ivr-validation` | CU-02 IVR OTP validation webhook unlocking `PENDIENTE_VALIDACION` contracts to `ACTIVO` |
| `GET` | `/v1/accounts/{user_id}/statement` | CU-03 Monthly account statement, available balance, retained balance, and next installment details |
| `POST` | `/v1/payments/reconcile` | CU-04 Payment reconciliation (`SPEI` / `EFECTIVO_OXXO`) updating balance and triggering early-payoff call logs |
| `GET` | `/v1/customers` | Lists demo fintech customers, credit accounts, and communication logs for dashboard inspection |
