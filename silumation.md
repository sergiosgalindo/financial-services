import os
import math
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# =============================================================================
# 1. CONFIGURACIÓN DE BASE DE DATOS Y MODELOS (ORM)
# =============================================================================
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/fintech_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Usuario(Base):
    __tablename__ = 'usuarios'
    usuario_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nombre = Column(String, nullable=False)
    telefono_whatsapp = Column(String, unique=True, nullable=False)
    rfc_curp = Column(String, unique=True, nullable=False)
    opt_in_whatsapp = Column(Boolean, default=False)

class ProductoFinanciero(Base):
    __tablename__ = 'productos_financieros'
    producto_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nombre_producto = Column(String, nullable=False) # 'PRESTAMO_PERSONAL' o 'DINERO_EXPRESS'
    tasa_interes_anual = Column(Numeric(5, 2), nullable=False)

# =============================================================================
# 2. ESQUEMAS DE ENTRADA (PAYLOADS DE WHATSAPP)
# =============================================================================
class WhatsAppMessageHook(BaseModel):
    message_id: str
    sender_phone: str # Formato E.164
    message_text: str

app = FastAPI(title="Fintech Omnichannel Orchestrator API Simulation")

# =============================================================================
# 3. FUNCIONES MOCK: SERVICIO DE PDFS Y MOTOR RAG
# =============================================================================
def simular_motor_rag(query_texto: str, producto_tipo: str) -> str:
    """
    Simula la extensión pgvector realizando un query de similitud coseno.
    Trae fragmentos de contratos reales indexados.
    """
    query_clean = query_texto.lower()
    if "interés" in query_clean or "tasa" in query_clean:
        if producto_tipo == "DINERO_EXPRESS":
            return "[Contexto RAG: Cláusula 3.2 de Adelanto de Capital Comercial] La tasa es fija por evento diario. No capitaliza si se liquida en el plazo corto de 7-28 días."
        return "[Contexto RAG: Cláusula 5.1 de Mercado Crédito] El interés ordinario se calcula mensualmente sobre saldos insolutos utilizando una tasa fija anual asignada por score."
    if "cat" in query_clean:
        return "[Contexto RAG: Transparencia Financiera] El Costo Anual Total (CAT) promedio es informativo y no incluye IVA. Se calcula anualmente para fines comparativos."
    
    return "[Contexto RAG: Centro de Ayuda] Para más dudas, puedes consultar los términos y condiciones generales en la sección legal de tu app de Mercado Pago."

def generar_y_cifrar_pdf_amortizacion(usuario: Usuario, cuotas: list) -> str:
    """
    Simula el microservicio de renderizado y seguridad.
    Cifra el PDF combinando los 4 primeros caracteres del RFC y los últimos 4 del celular.
    """
    clave_pdf = f"{usuario.rfc_curp[:4].upper()}{usuario.telefono_whatsapp[-4:]}"
    s3_mock_path = f"s3://fintech-bucket-secure/amortizaciones/{usuario.usuario_id}_{int(datetime.now().timestamp())}.pdf"
    print(f"🔒 [PDF SERVICE] Archivo generado en {s3_mock_path}. Protegido con contraseña: '{clave_pdf}'")
    return s3_mock_path

def enviar_mensaje_whatsapp_api(telefono: str, texto_mensaje: str, pdf_url: Optional[str] = None):
    """Simula la invocación de la API saliente (Cloud API de Meta)"""
    print(f"🚀 [WHATSAPP OUTBOUND API] -> Enviando a {telefono}")
    print(f"💬 Mensaje: {texto_mensaje}")
    if pdf_url:
        print(f"📎 Archivo Adjunto (PDF): {pdf_url}")
    print("-" * 50)

# =============================================================================
# 4. ENDPOINT PRINCIPAL: WEBHOOK DE ENTRADA DE WHATSAPP (ORQUESTADOR)
# =============================================================================
@app.post("/v1/webhooks/whatsapp")
async def recibir_mensaje_whatsapp(payload: WhatsAppMessageHook, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        # 1. Identificar al usuario en el Core por su número telefónico
        usuario = db.query(Usuario).filter(Usuario.telefono_whatsapp == payload.sender_phone).first()
        if not usuario:
            # Flujo alternativo si no está registrado
            return {"status": "ignored", "reason": "Usuario no registrado en la plataforma fintech"}
        
        # Validar Opt-In de mensajería exigido por Meta
        if not usuario.opt_in_whatsapp:
            return {"status": "blocked", "reason": "Usuario no cuenta con políticas de Opt-In activas"}

        texto_recibido = payload.message_text.strip()
        texto_lower = texto_recibido.lower()

        # =====================================================================
        # CASO DE USO 01: SIMULACIÓN DE CRÉDITO CON REGLAS DE NEGOCIO ESTILO ML
        # =====================================================================
        if "simular" in texto_lower or "necesito" in texto_lower:
            # Simulación Mock: Evaluamos qué producto asignarle (Regla de negocio basada en el cliente)
            # En producción, se buscaría en la tabla 'cuentas_creditos' el estado 'PREAPROBADO'
            producto = db.query(ProductoFinanciero).filter(
                ProductoFinanciero.nombre_producto == "PRESTAMO_PERSONAL"
            ).first()
            
            if not producto:
                raise HTTPException(status_code=500, detail="Productos no configurados en el core")

            # Asumimos montos y plazos por defecto si el usuario no los dictó (ej. 'Simular 5000')
            monto_solicitado = 5000.00
            
            # Aplicación de Reglas de Negocio Cruzadas:
            if producto.nombre_producto == "DINERO_EXPRESS":
                plazo_cuotas = 4 # 4 semanas / periodos cortos (7, 14, 21, 28 días)
                frecuencia_dias = 7
                nombre_interfaz = "Dinero Express (Capital de Trabajo)"
            else: # PRESTAMO_PERSONAL
                plazo_cuotas = 6 # 6 meses estándar (Rango 1 a 12)
                frecuencia_dias = 30
                nombre_interfaz = "Préstamo Personal (Mercado Crédito)"

            # Cálculo financiero básico (Amortización cuotas fijas francesas)
            tasa_mensual = (float(producto.tasa_interes_anual) / 100) / 12
            factor = (1 + tasa_mensual) ** plazo_cuotas
            cuota_mensual = monto_solicitado * (tasa_mensual * factor) / (factor - 1)

            # Estructurar la matriz de cuotas para el PDF
            lista_cuotas = []
            for i in range(1, plazo_cuotas + 1):
                lista_cuotas.append({
                    "numero_cuota": i,
                    "monto_total": round(cuota_mensual, 2),
                    "fecha_vencimiento": (datetime.now() + timedelta(days=i * frecuencia_dias)).strftime("%Y-%m-%d")
                })

            # Disparar procesos en segundo plano para no bloquear el webhook de Meta (Asíncrono)
            background_tasks.add_task(
                procesar_envio_simulacion, 
                usuario, nombre_interfaz, monto_solicitado, plazo_cuotas, lista_cuotas
            )
            return {"status": "processing", "flow": "CU-01_SIMULATION"}

        # =====================================================================
        # INTERVENCIÓN DEL MOTOR RAG: CONSULTAS ABIERTAS SOBRE POLÍTICAS / CAT / TASAS
        # =====================================================================
        elif any(keyword in texto_lower for keyword in ["tasa", "interes", "cat", "contrato", "comision"]):
            # Determinar dinámicamente el tipo de producto asignado al usuario
            producto_tipo = "PRESTAMO_PERSONAL" 
            
            # Consultar base de conocimiento vectorial simulación
            contexto_legal = simular_motor_rag(texto_recibido, producto_tipo)
            
            # Prompt de inyección al LLM integrado en el flujo del Bot
            respuesta_bot = (
                f"Hola {usuario.nombre}. Revisando las regulaciones de tu contrato de crédito, te informo:\n\n"
                f"{contexto_legal}\n\n"
                f"¿Deseas continuar con tu proceso de contratación o simular un monto diferente?"
            )
            
            background_tasks.add_task(enviar_mensaje_whatsapp_api, usuario.telefono_whatsapp, respuesta_bot)
            return {"status": "processing", "flow": "RAG_COGNITIVE_RESPONSE"}

        else:
            # Flujo por defecto / Menú de opciones interactivo
            mensaje_menu = (
                f"Hola {usuario.nombre}, bienvenido a la asistencia financiera. 📲\n"
                f"Por favor selecciona o escribe una opción:\n"
                f"1. *Simular Préstamo* (Cotizar tu línea disponible)\n"
                f"2. *Estado de Cuenta* (Ver tus fechas límites y saldo)\n"
                f"O hazme cualquier pregunta abierta sobre tus intereses o contratos."
            )
            background_tasks.add_task(enviar_mensaje_whatsapp_api, usuario.telefono_whatsapp, mensaje_menu)
            return {"status": "processing", "flow": "MENU_FALLBACK"}

    finally:
        db.close()

# =============================================================================
# 5. SUB-PROCESOS ASÍNCRONOS (WORKERS BACKGROUND)
# =============================================================================
