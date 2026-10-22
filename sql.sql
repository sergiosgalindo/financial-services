-- =============================================================================
-- ESQUEMA DE BASE DE DATOS: PLATAFORMA FINTECH OMNICANAL
-- SGBD: PostgreSQL (Compatible con extensiones pgvector para RAG)
-- =============================================================================

-- Habilitar extensión para identificadores únicos universales (Mitigación de riesgos en APIs)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Habilitar extensión para almacenamiento y búsqueda de vectores (Requerido para el Motor RAG)
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- 1. TABLA: USUARIOS / CLIENTES
-- Contiene la información core del cliente, su estado de riesgo y opt-ins.
-- -----------------------------------------------------------------------------
CREATE TABLE usuarios (
    usuario_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    telefono_whatsapp VARCHAR(20) UNIQUE NOT NULL, -- Formato E.164 (ej. +525512345678)
    email VARCHAR(150) UNIQUE NOT NULL,
    rfc_curp VARCHAR(20) UNIQUE NOT NULL, -- Utilizado para la clave dinámica del PDF
    score_crediticio INT CHECK (score_crediticio BETWEEN 300 AND 850),
    estado_cuenta VARCHAR(20) DEFAULT 'ACTIVO' CHECK (estado_cuenta IN ('ACTIVO', 'BLOQUEADO', 'SUSPENDIDO')),
    
    -- Control Crítico de Cumplimiento Regulatorio y Políticas de Meta (Opt-In)
    opt_in_whatsapp BOOLEAN DEFAULT FALSE NOT NULL,
    opt_in_llamadas BOOLEAN DEFAULT FALSE NOT NULL,
    fecha_opt_in TIMESTAMP WITH TIME ZONE,
    
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indices para optimizar búsquedas desde Webhooks entrantes
CREATE INDEX idx_usuarios_telefono ON usuarios(telefono_whatsapp);

-- -----------------------------------------------------------------------------
-- 2. TABLA: PRODUCTOS_FINANCIEROS
-- Catálogo de productos configurados en la plataforma (Estilo Mercado Libre).
-- -----------------------------------------------------------------------------
CREATE TABLE productos_financieros (
    producto_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre_producto VARCHAR(50) NOT NULL CHECK (nombre_producto IN ('PRESTAMO_PERSONAL', 'DINERO_EXPRESS', 'TARJETA_CREDITO', 'TARJETA_DEBITO')),
    tasa_interes_anual NUMERIC(5,2) NOT NULL, -- Ejemplo: 45.50 para 45.5%
    cat_promedio NUMERIC(5,2), -- Costo Anual Total
    plazo_minimo_dias INT NOT NULL, -- Dinero Express usa 7 días, Préstamos usa 30 (1 mes)
    plazo_maximo_dias INT NOT NULL, -- Préstamos usa 365 días (12 meses)
    activo BOOLEAN DEFAULT TRUE NOT NULL
);

-- -----------------------------------------------------------------------------
-- 3. TABLA: CUENTAS_Y_CREDITOS
-- Instancia de un producto financiero asignado o preaprobado para un usuario.
-- -----------------------------------------------------------------------------
CREATE TABLE cuentas_creditos (
    contrato_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID REFERENCES usuarios(usuario_id) ON DELETE RESTRICT,
    producto_id UUID REFERENCES productos_financieros(producto_id) ON DELETE RESTRICT,
    linea_credito_autorizada NUMERIC(15,2) NOT NULL,
    saldo_disponible NUMERIC(15,2) NOT NULL,
    saldo_retenido_deudis NUMERIC(15,2) DEFAULT 0.00,
    estado_credito VARCHAR(30) DEFAULT 'PREAPROBADO' 
        CHECK (estado_credito IN ('PREAPROBADO', 'PENDIENTE_VALIDACION', 'ACTIVO', 'AL_CORRIENTE', 'ATRASADO', 'LIQUIDADO')),
    fecha_apertura TIMESTAMP WITH TIME ZONE,
    fecha_vencimiento TIMESTAMP WITH TIME ZONE,
    fecha_creacion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_creditos_usuario ON cuentas_creditos(usuario_id);
CREATE INDEX idx_creditos_estado ON cuentas_creditos(estado_credito);

-- -----------------------------------------------------------------------------
-- 4. TABLA: TABLAS_AMORTIZACION_CUOTAS
-- Desglose de mensualidades o pagos cortos (7-28 días para Dinero Express).
-- -----------------------------------------------------------------------------
CREATE TABLE cuotas_amortizacion (
    cuota_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contrato_id UUID REFERENCES cuentas_creditos(contrato_id) ON DELETE CASCADE,
    numero_cuota INT NOT NULL, -- Ejemplo: 1 de 12
    monto_principal NUMERIC(15,2) NOT NULL,
    monto_interes NUMERIC(15,2) NOT NULL,
    monto_iva NUMERIC(15,2) DEFAULT 0.00,
    monto_total_cuota NUMERIC(15,2) NOT NULL,
    fecha_limite_pago DATE NOT NULL,
    estado_pago VARCHAR(20) DEFAULT 'PENDIENTE' CHECK (estado_pago IN ('PENDIENTE', 'PAGADO', 'PARCIAL', 'VENCIDO')),
    monto_pagado_acumulado NUMERIC(15,2) DEFAULT 0.00,
    fecha_pago_efectivo TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_cuotas_vencimiento ON cuotas_amortizacion(fecha_limite_pago, estado_pago);

-- -----------------------------------------------------------------------------
-- 5. TABLA: HISTORIAL_TRANSACCIONAL (PAGOS Y DISPERSIONES)
-- Triggers de conciliación para disparar el CU-04 (Comprobantes en PDF).
-- -----------------------------------------------------------------------------
CREATE TABLE transacciones (
    transaccion_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contrato_id UUID REFERENCES cuentas_creditos(contrato_id) ON DELETE RESTRICT,
    tipo_transaccion VARCHAR(20) NOT NULL CHECK (tipo_transaccion IN ('DISPERSION', 'ABONO_CUOTA', 'LIQUIDACION_ANTICIPADA', 'RENDIMIENTO_DIARIO')),
    monto NUMERIC(15,2) NOT NULL,
    metodo_pago VARCHAR(30) NOT NULL, -- 'SPEI', 'EFECTIVO_OXXO', 'SALDO_VIRTUAL'
    referencia_bancaria VARCHAR(100) UNIQUE NOT NULL, -- Clave de rastreo SPEI o ticket
    estado_transaccion VARCHAR(20) DEFAULT 'PROCESANDO' CHECK (estado_transaccion IN ('PROCESANDO', 'CONCILIADO', 'RECHAZADO')),
    fecha_transaccion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- 6. TABLA: BITÁCORA OMNICANAL DE INTERACCIONES Y DOCUMENTOS
-- Rastreo de envíos de WhatsApp, PDFs generados y llamadas IVR asociadas.
-- -----------------------------------------------------------------------------
CREATE TABLE bitacora_comunicaciones (
    comunicacion_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    usuario_id UUID REFERENCES usuarios(usuario_id) ON DELETE SET NULL,
    canal_utilizado VARCHAR(20) NOT NULL CHECK (canal_utilizado IN ('WHATSAPP', 'LLAMADA_VOZ')),
    caso_de_uso_codigo VARCHAR(10) NOT NULL, -- 'CU-01', 'CU-02', 'CU-03', 'CU-04'
    plantilla_hsm_nombre VARCHAR(100), -- Nombre registrado en Meta si aplica
    estado_entrega VARCHAR(20) DEFAULT 'ENVIADO' CHECK (estado_entrega IN ('ENVIADO', 'ENTREGADO', 'LEIDO', 'CONTESTADO', 'FALLIDO', 'OTP_VALIDADO', 'OTP_RECHAZADO')),
    
    -- Metadata del documento adjunto (En S3 con URL firmada)
    pdf_generado_nombre VARCHAR(150),
    s3_storage_path VARCHAR(255), 
    
    -- ID de tracking externo de proveedores (Meta Message ID / Twilio Call SID)
    proveedor_tracking_id VARCHAR(150) UNIQUE,
    fecha_registro TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_bitacora_tracking ON bitacora_comunicaciones(proveedor_tracking_id);

-- -----------------------------------------------------------------------------
-- 7. TABLA: BASE DE CONOCIMIENTO VECTORIAL (CONTRATOS Y POLÍTICAS - MOTOR RAG)
-- Almacena los fragmentos (chunks) normativos para consultas en lenguaje natural.
-- -----------------------------------------------------------------------------
CREATE TABLE base_conocimiento_rag (
    chunk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id UUID REFERENCES productos_financieros(producto_id) ON DELETE CASCADE,
    documento_origen_nombre VARCHAR(150) NOT NULL, -- ej. 'Contrato_Prestamo_V3.pdf'
    seccion_titulo VARCHAR(150), -- ej. 'Cláusula Cuarta: Intereses Moratorios'
    contenido_texto TEXT NOT NULL, -- El texto crudo del fragmento
    embedding_vector VECTOR(1536) -- Vector de 1536 dimensiones (Estándar de OpenAI text-embedding-3-small)
);

-- Índice de búsqueda vectorial para optimizar consultas de similitud coseno (RAG)
CREATE INDEX idx_rag_embedding ON base_conocimiento_rag USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100);