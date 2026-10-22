### ⚙️ Componentes de la Arquitectura

1. **Orquestador Conversacional (Backend for Frontend - BFF):** 
   - Desarrollado en Node.js (TypeScript) o Python (FastAPI).
   - Recibe los webhooks entrantes de Meta. Administra las sesiones activas, las máquinas de estado de los usuarios y distribuye la carga: si es un flujo de datos estructurado (como una selección de menú), lo envía al Core Financiero; si es una consulta abierta, delega al motor RAG.
2. **Motor RAG (Retrieval-Augmented Generation):**
   - **Ingesta:** Los contratos base de préstamos, las tablas de CAT vigentes, los términos de Months Without Interest (MSI) y manuales de usuario se fragmentan (*chunking* de 512 tokens con overlap de 10%) y se transforman mediante modelos de *embedding*.
   - **Almacenamiento:** Los vectores se indexan en una base de datos vectorial (ej. Pinecone o PostgreSQL + `pgvector`).
   - **Ejecución:** Al recibir un mensaje libre, el buscador vectorial recupera los 3 fragmentos normativos más relevantes (*Top-K*), y se los inyecta al contexto del LLM (Large Language Model) junto con un prompt de sistema estricto: *"Eres el asistente oficial de Mercado Pago. Responde únicamente basándote en el contexto provisto. Si no tienes la información, deriva amablemente a un ejecutivo humano"*.
3. **Core Financiero e Ingesta de Documentación:**
   - Consume bases relacionales ACID (como PostgreSQL) encargadas del ledger o libro contable del usuario.
   - Cuenta con un microservicio de generación dinámica de reportes (PDF Generator) que toma plantillas HTML estructuradas, inserta la metadata financiera del cliente (tabla de amortización o estado de cuenta) y aplica una librería de cifrado nativo simétrico (AES-256) antes de depositar el archivo temporal en un *bucket* seguro de Amazon S3 con URLs firmadas con expiración de 10 minutos.
4. **Módulo de Integración Telefónica (Voz / IVR):**
   - Integrado mediante APIs CPaaS (como Twilio o MessageBird).
   - El microservicio de orquestación, al detectar un cambio de estado del crédito a "Pendiente de Validación", emite un comando `POST /Calls` al proveedor de voz. El IVR procesa la llamada y retorna el estatus del PIN numérico ingresado por el usuario mediante señales DTMF vía webhook, destrabando la entrega del contrato en WhatsApp en menos de 3 milisegundos.