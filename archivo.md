+-----------------------+
|   Cliente / Usuario   |
+-----------+-----------+
|
+------------------------+------------------------+
| (Texto / PDFs)         | (Llamadas de Voz)      | (SPEI / Efectivo)
v                        v                        v
+----------+----------+  +----------+----------+  +----------+----------+
| WhatsApp Business   |  | Proveedor de Voz    |  | Pasarela de Pagos   |
| API (Meta Platform) |  | (Twilio / Amazon Ch)|  | / Corresponsalías   |
+----------+----------+  +----------+----------+  +----------+----------+
|                        |                        |
| (Webhooks HTTPS)       | (Webhooks SIP/Status)  | (Webhooks REST)
+------------------------+------------------------+
|
v
+----------------+----------------+
|     Capa de API Gateway /       |
|    Balanceador de Carga        |
+----------------+----------------+
|
v
+----------------+----------------+
|  Microservicio de Orquestación |
|      Conversacional (BFF)       |
+--------+--------------+---------+
|              |
+-----------------------+              +-----------------------+
|                                                              |
v                                                              v
+---------------+---------------+                              +---------------+---------------+
|       Motor Cognitivo RAG     |                              |   Microservicio Core Fintech  |
|  (Gestión de Conocimiento)    |                              |    (Préstamos, Débito, TC)    |
+---------------+---------------+                              +---------------+---------------+
| - Orquestador (LangChain)     |                              | - Motor de Riesgos e Ingesta  |
| - Embeddings (OpenAI / Ada)   |                              | - Generador de PDFs (Cifrados)|
| - Base Vectorial (Pinecone /  |                              | - Base Relacional (PostgreSQL)|
|   pgvector)                   |                              |   (Saldos, Tasas, Contratos)  |
| - LLM 