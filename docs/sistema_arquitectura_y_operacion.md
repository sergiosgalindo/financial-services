# Documentación Técnica y Guía de Operación: Asistente Omnicanal Fintech

## 1. Introducción y Propósito del Sistema

El **Asistente Omnicanal Fintech** es un orquestador conversacional de servicios financieros diseñado para interactuar con clientes a través de la **API Cloud de WhatsApp de Meta**, interfaces web y sistemas de voz (IVR). El sistema automatiza desde la prospección, calificación y simulación de créditos hasta la consulta de estados de cuenta, conciliación de pagos y reporte de fraudes.

### Stack Tecnológico
- **Backend**: FastAPI (Python 3.11), arquitectura MVC asíncrona.
- **Base de Datos Relacional**: SQLAlchemy 2.0 con soporte dual: SQLite (desarrollo local) y PostgreSQL 16 con extensión `pgvector` (producción).
- **Modelo de Lenguaje (LLM)**: Llama 3.1 8B (vía Ollama local o Groq/vLLM en la nube).
- **RAG Semántico**: Embeddings multilingües con `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` y búsqueda por similitud de coseno sobre cláusulas normativas.
- **Seguridad en Dos Capas**:
  - *Capa 1 (Prompt Guard)*: Detección y bloqueo de inyecciones de prompt y evasión de instrucciones de sistema.
  - *Capa 2 (Llama Guard)*: Filtrado de contenido inapropiado, delitos financieros y suplantación de identidad.
  - *Protección de Datos Sensibles*: Detección por regex y enmascaramiento estricto de NIP, CVV, contraseñas y códigos OTP.
- **Canal de Entrega**: Meta WhatsApp Cloud API (Graph API v25.0) con soporte para mensajes de texto y menús interactivos tipo lista (`interactive list`).

---

## 2. Arquitectura General del Sistema

```mermaid
flowchart TD
    Customer["Cliente (WhatsApp / Web)"] -->|POST /webhook| WHRouter["WhatsApp Webhook Controller"]
    WHRouter --> Lock["Phone Mutex Lock & Deduplicador (wamid)"]
    Lock --> SafetyIn["Capa 1 & 2: Prompt Guard + Llama Guard"]
    SafetyIn --> StateEngine["Motor de Estados y Enrutador de Intenciones"]
    
    StateEngine -->|Flujo A: Originación| DBFlow["Simulador / Scoring / Amortización (CU-01)"]
    StateEngine -->|CU-02..CU-04| FinTools["Herramientas Financieras (IVR, Aclaraciones, Pagos)"]
    StateEngine -->|Flujo B: Pregunta Normativa| RAGEngine["RAG Semántico (Cláusulas Legales)"]
    
    RAGEngine --> LLM["Llama 3.1 8B (Ollama / Groq)"]
    LLM --> SafetyOut["Capa 2: Llama Guard Output Safety"]
    
    DBFlow --> Formatter["Formateador HSM & Menús Interactivos"]
    FinTools --> Formatter
    SafetyOut --> Formatter
    
    Formatter --> MetaAPI["Meta Graph API (Mensajes / Listas)"]
    MetaAPI --> Customer
```

---

## 3. Máquina de Estados Conversacional (Dialog Management)

El asistente implementa una máquina de estados conversacional estricta, diseñada para respetar los contratos de negocio mexicanos y las limitaciones de interfaz de WhatsApp.

### 3.1 Flujo A: Solicitud y Originación de Crédito

```text
[Inicio: "Quiero 1000 pesos"]
        │
        ▼
1. Propósito (elegir_proposito):
   ¿El préstamo de $1,000.00 MXN sería para un gasto personal o para tu negocio?
   [Menú: Gasto personal | Para mi negocio]
        │
        ▼
2. Calificación / Plazo (elegir_plazo):
   (Si negocio: valida antigüedad; si personal: pasa directo a plazo).
   "Para tu Préstamo para Negocio de $1,000.00 MXN, ¿en cuántos meses te gustaría comparar el pago?"
   [Tolerancia: Acepta botones de lista O texto libre: "10", "12 meses", "6", "a 10", "en 10"]
        │
        ▼
3. Resumen y Confirmación (confirmar_simulacion):
   Resumen de tu simulación:
   • Producto: Préstamo para Negocio
   • Monto: $1,000.00 MXN
   • Plazo: 10 meses
   ¿Así está bien para preparar una simulación?
   [Acepta: Botón "Sí, simular" O respuestas afirmativas: "Si", "sí", "claro", "adelante", "va"]
        │
        ▼
4. Simulación Oficial (simulado):
   💰 Simulación de Préstamo para Negocio Impulso
   • Monto: $1,000.00 MXN
   • Plan: 10 meses de $121.29 MXN
   • Total estimado: $1,212.96 MXN (CAT 48.5% sin IVA)
   👇 ¿Quieres confirmar este plazo para evaluación, o prefieres probar otro plazo/monto?
   [Opciones: Solicitar este plazo | Elegir otro plazo | Cambiar monto]
        │
        ▼
5. Originación y Scoring (CU-01-ORIGINATION):
   (Si responde "Si", "solicitar", "lo quiero", "contratar" o pulsa el botón).
   Ejecuta motor de scoring:
   • Aprobado: Asigna folio oficial, clave de contrato y fechas de pago.
   • En revisión: Si el cliente cuenta con deudas activas preexistentes o score bajo.
   • Rechazado: Si el usuario se encuentra en lista negra o bloqueado.
```

### 3.2 Flujo B: Interrupción por Preguntas Frecuentes y Reanudación

Si el usuario hace una pregunta sobre políticas en medio de una solicitud (ej. *"¿Cobran comisión por apertura o penalización por pagar antes?"*):

1. **Persistencia de Estado**: La sesión activa se mantiene intacta en `LlamaStackStore`.
2. **Respuesta RAG Concisa**: Se busca la cláusula exacta en la base de conocimientos y se sintetiza en menos de 400 caracteres:
   > *"No se cobran penalizaciones por liquidación anticipada en ningún momento..."*
3. **Sufijo de Reanudación**: Se adjunta automáticamente:
   > *"¿Te gustaría continuar con tu solicitud de Préstamo para Negocio donde nos quedamos?"*
4. **Reanudación Transparente**: Al escribir cualquier respuesta afirmativa (`si`, `sí`, `continuar`, `claro`, `por favor`), el sistema devuelve de inmediato la pregunta y menú donde se encontraba el usuario, sin reiniciar la solicitud.

---

## 4. Matriz de Casos de Uso Financieros (CU-01 a CU-04)

| Caso de Uso | Función Principal | Endpoint REST | Descripción y Reglas |
| :--- | :--- | :--- | :--- |
| **CU-01** | `simulate_loan_in_db` / `evaluate_credit_scoring_and_originate_loan` | `POST /v1/loans/simulate` | Amortización francesa. Calcula cuota fija, desglose de capital, interés ordinario y 16% de IVA sobre interés. Genera contraseña segura para PDF cifrado (`{RFC[:4]}{PHONE[-4:]}`). |
| **CU-02** | `validate_ivr_otp_in_db` | `POST /v1/security/ivr-validation` | Valida código OTP de 6 dígitos emitido vía llamada de voz (IVR). Cambia estado de contrato de `PENDIENTE_VALIDACION` a `ACTIVO`. |
| **CU-03** | `get_account_statement_data` / `register_unrecognized_charge_dispute` | `GET /v1/accounts/{user_id}/statement` | Estado de cuenta mensual, desglose de saldo disponible y retención preventiva de cargos no reconocidos (`Saldo Retenido en Tránsito`). |
| **CU-04** | `reconcile_payment_in_db` / `get_early_payoff_quote` | `POST /v1/payments/reconcile` | Conciliación de pagos SPEI y OXXO en tiempo real. Cotización de liquidación anticipada con $0.00 de penalización. |
| **CU-03-FRAUD** | Manejador de Fraude y Robo | Conversacional | Desvío prioritario ante menciones de robo, clonación o suplantación a la línea directa de emergencias: `800-999-2026`. |
| **RN-04** | `register_whatsapp_opt_out` | Conversacional | Ante mensajes como `BAJA`, `STOP` o `CANCELAR`, desactiva `opt_in_whatsapp` y cesa la comunicación comercial. |

---

## 5. Especificaciones de Menús Interactivos de WhatsApp

Para evitar errores de validación de la Graph API de Meta (`HTTP 400 - Parameter value is invalid`):
- **Botón principal del menú (`action.button`)**: Máximo 20 caracteres (actual: `"Siguiente paso"`, `"Continuar"`, `"Elegir monto"`).
- **Título de fila (`row.title`)**: Máximo 24 caracteres (ej. `"Para mi negocio 💼"`, `"12 meses"`).
- **Descripción de fila (`row.description`)**: Máximo 72 caracteres.
- **Sección (`section.title`)**: Máximo 24 caracteres.

---

## 6. Guía de Puesta en Producción

### 6.1 Despliegue con Docker Compose (Recomendado)

El proyecto incluye configuración completa para orquestar la API y la base de datos PostgreSQL:

```bash
# 1. Clonar el repositorio y acceder a la carpeta
cd servicios-financieros

# 2. Configurar variables de entorno
cp .env.example .env
nano .env

# 3. Construir y levantar servicios en segundo plano
docker compose up -d --build

# 4. Verificar salud de los contenedores
docker compose ps
curl http://localhost:8000/api/health
```

### 6.2 Variables de Entorno de Producción (`.env`)

```ini
# Configuración del Servidor
APP_PORT=8000
ENVIRONMENT=production

# Base de Datos PostgreSQL
DATABASE_URL=postgresql+psycopg2://fintech_user:fintech_pass@fintech-db:5432/fintech_db

# Meta WhatsApp Cloud API
WHATSAPP_ACCESS_TOKEN=EAAG... (Token permanente del System User)
WHATSAPP_PHONE_NUMBER_ID=109283746501928
WHATSAPP_VERIFY_TOKEN=token-seguro-verificacion-webhook-2026
WHATSAPP_API_VERSION=v25.0

# Proveedor de LLM en la Nube (Groq / vLLM)
# Para producción sin GPU dedicada local, se recomienda Groq (latencia < 400ms):
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant

# RAG y Caché de Modelos
EMBEDDING_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
HF_HOME=/app/.cache/huggingface
```

### 6.3 Configuración de Webhook en Meta Business Manager
1. Ingresa a [Meta for Developers](https://developers.facebook.com/) > Tu Aplicación > **WhatsApp** > **Configuración**.
2. En **Webhook**:
   - URL de devolución de llamada: `https://tu-dominio.com/webhook`
   - Token de verificación: El valor definido en `WHATSAPP_VERIFY_TOKEN`.
3. Suscríbete al evento: `messages`.

---

## 7. Pruebas y Diagnóstico

### Ejecución de Pruebas Unitarias e Integración
```bash
pytest -v
```
*Cobertura: 20 pruebas que validan los 4 casos de uso, RAG, Llama Guard, deduplicación de mensajes, cálculo de amortización francesa, desvío de fraudes, opt-out y resiliencia conversacional.*

### Endpoints de Monitoreo
- **Salud del Sistema**: `GET /api/health`
- **Diagnóstico General**: `GET /api/diagnostics` (valida conteo de usuarios, contratos, chunks de RAG y conexión a BD).
- **Métricas de Latencia**: `GET /api/metrics` (promedio, percentil 95 y máximo de tiempo de respuesta).
