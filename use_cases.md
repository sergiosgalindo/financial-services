# ESPECIFICACIÓN DE CASOS DE USO: ARQUITECTURA FINTECH OMNICANAL
> **Estatus:** Documento Técnico de Arquitectura y Negocio  
> **Área:** Ingeniería de Software / Célula Core Fintech  
> **Clasificación:** CONFIDENCIAL - Solo para uso interno  

---

## 1. Introducción y Alineación Estratégica

Este documento especifica los flujos de automatización conversacional y documental para cuatro productos financieros core. El diseño lógico se alinea con las reglas operativas de plataformas de alto volumen (Efecto Mercado Libre / Mercado Pago), optimizando la atención al cliente mediante una estrategia omnicanal inteligente.

### 🏛️ Reglas de Negocio por Producto

1. **Préstamo Personal (Modelo Mercado Crédito):** 
   - No se solicita de manera tradicional; funciona bajo un esquema de preaprobación ("por invitación") basado en el comportamiento e historial transaccional del usuario dentro del ecosistema.
   - Las opciones de amortización se configuran en plazos fijos mensuales que van de 1 a 12 meses.
2. **Dinero Express (Modelo Dinero Plus / Adelanto de Capital):** 
   - Diseñado principalmente como financiamiento de liquidez inmediata a corto plazo para comercios y vendedores recurrentes.
   - Restringe estrictamente sus plazos de pago a periodos micro: 7, 14, 21 o 28 días con cobro automatizado del saldo en cuenta.
3. **Tarjeta de Crédito:** 
   - Sin costo de anualidad física ni virtual, habilitada para compras a Meses Sin Intereses (MSI) dentro del e-commerce.
   - Exige un flujo obligatorio de validación de identidad biométrica antes de la activación del plástico o la firma de los contratos para mitigar riesgos de suplantación.
4. **Tarjeta de Débito:** 
   - Vinculada directamente a la cuenta digital a la vista. Cuenta con reglas de generación de rendimiento diario automatizado sobre el saldo disponible.

---

## 2. Arquitectura de Canales Tecnológicos

La orquestación de la atención automatizada se divide de manera balanceada en tres componentes tecnológicos clave:

*   **WhatsApp Business API:** Motor transaccional primario asíncrono. Encargado de la mensajería interactiva, alertas push autorizadas (Mensajes HSM) y el envío/recepción de archivos **PDF cifrados**.
*   **Canal de Voz (Llamadas Automatizadas IVR Outbound):** Canal síncrono secundario. Actúa como factor de autenticación de alta seguridad (Tokens dictados / Biometría de voz) para mitigar fraudes en transacciones críticas y apoyo en recuperación de cartera.
*   **Motor RAG (Retrieval-Augmented Generation):** El componente cognitivo embebido en las interfaces de WhatsApp. En lugar de delegar dudas abiertas a un agente humano, el motor RAG consulta en tiempo real bases de conocimientos vectoriales (contratos base, términos de uso, reglas del CAT, etc.) para responder con precisión legal y personalizada en lenguaje natural.

---

## 3. Matriz Detallada de Casos de Uso

### CU-01: Simulación e Ingesta de Crédito Conversacional

| Campo | Especificación Técnica y de Negocio |
| :--- | :--- |
| **ID / Nombre** | **CU-01** - Simulación e Ingesta de Crédito Conversacional |
| **Actores** | Cliente, WhatsApp Bot, Sistema Core Financiero, Motor RAG. |
| **Disparador** | El cliente escribe palabras clave en WhatsApp como *"necesito un préstamo"* o *"quiero simular un crédito"*. |
| **Flujo Principal** | 1. El cliente inicia la interacción por WhatsApp.<br>2. El sistema consulta el Core Financiero para identificar qué producto tiene preaprobado.<br>3. **Bifurcación de Regla:** <br>&nbsp;&nbsp;&nbsp;&nbsp;• Si aplica para *Préstamo Personal*, despliega opciones de 1 a 12 meses.<br>&nbsp;&nbsp;&nbsp;&nbsp;• Si aplica para *Dinero Express*, fuerza la interfaz a plazos fijos de 7, 14, 21 o 28 días.<br>4. Si el cliente interrumpe el flujo preguntando dudas como *"¿Qué es el CAT?"* o *"¿Cómo calculan el interés?"*, el **Motor RAG** procesa la pregunta y responde de inmediato basándose en las políticas oficiales vigentes.<br>5. Al confirmar el monto y plazo, el sistema compila y envía en el mismo chat la **Tabla de Amortización Proyectada en PDF**. |

### CU-02: Aprobación, Validación de Identidad y Firma de Contratos

| Campo | Especificación Técnica y de Negocio |
| :--- | :--- |
| **ID / Nombre** | **CU-02** - Aprobación, Validación de Identidad y Firma de Contratos |
| **Actores** | Cliente, Sistema de Riesgos, Canal de Voz (IVR Automatizado), WhatsApp API. |
| **Disparador** | El score de riesgos del Sistema Core cambia el estado de una solicitud a *"Aprobado - Requiere Validación"*. |
| **Flujo Principal** | 1. El sistema genera el **Contrato Legal en PDF** personalizado y protegido por contraseña en el backend.<br>2. Para evitar fraudes de identidad (especialmente en *Tarjeta de Crédito* y disposición de *Dinero Express*), el sistema congela el flujo de WhatsApp y **dispara una Llamada Telefónica Automatizada** de forma síncrona.<br>3. El IVR telefónico le solicita al cliente una confirmación activa (marcar un dígito o dictar un token OTP enviado por SMS).<br>4. Una vez validada la identidad de forma exitosa en la llamada, esta finaliza y el webhook del sistema libera el flujo en WhatsApp, enviando el link de descarga del contrato y los accesos para la **Firma Digital (e-firma)**. |

### CU-03: Distribución Proactiva de Estados de Cuenta Mensuales

| Campo | Especificación Técnica y de Negocio |
| :--- | :--- |
| **ID / Nombre** | **CU-03** - Distribución Proactiva de Estados de Cuenta Mensuales |
| **Actores** | Cronjob de Facturación, WhatsApp API, Cliente, Motor RAG. |
| **Disparador** | Llegada de la fecha de corte mensual parametrizada para el perfil del cliente. |
| **Flujo Principal** | 1. Un proceso masivo en el backend genera los **Estados de Cuenta en PDF** estructurados según el producto:<br>&nbsp;&nbsp;&nbsp;&nbsp;• *Tarjeta de Crédito:* Desglose de consumos, saldo al corte, pago mínimo y compras vigentes a MSI.<br>&nbsp;&nbsp;&nbsp;&nbsp;• *Tarjeta de Débito:* Resumen de saldos y detalle del rendimiento diario acumulado.<br>2. El sistema envía una notificación proactiva vía WhatsApp (Plantilla HSM aprobada) adjuntando el documento PDF protegido.<br>3. Si el cliente responde el mensaje indicando lenguaje natural de inconformidad (ej. *"No reconozco un cargo de este estado de cuenta"*), el **Motor RAG** interviene identificando la regla de negocio para disputas y le proporciona la guía exacta y el checklist de documentos para iniciar la aclaración formal. |

### CU-04: Notificación Transaccional de Comprobantes de Pago

| Campo | Especificación Técnica y de Negocio |
| :--- | :--- |
| **ID / Nombre** | **CU-04** - Notificación Transaccional de Comprobantes de Pago |
| **Actores** | Procesador de Pagos (SPEI/Corresponsal), Sistema Core, WhatsApp API, Canal de Voz. |
| **Disparador** | Recepción exitosa de un webhook de confirmación de pago por parte del procesador o tienda de conveniencia. |
| **Flujo Principal** | 1. El cliente realiza el pago de su mensualidad (ya sea mediante transferencia SPEI o depósito en efectivo en corresponsales autorizados).<br>2. Al conciliarse el saldo, el Core liquida la cuota del *Préstamo Personal* o libera la línea de la *Tarjeta de Crédito*.<br>3. El sistema dispara un mensaje inmediato a WhatsApp adjuntando el **Comprobante de Pago en PDF** como acuse legal de la transacción.<br>4. **Regla de Negocio Especial:** Si el abono corresponde a un pago extraordinario de liquidación total anticipada de un préstamo, el sistema complementa el flujo agendando una **Llamada Telefónica automatizada de cortesía** para confirmar la liberación definitiva de la línea y agradecer su lealtad comercial. |

---

## 4. Consideraciones Críticas de Seguridad y Privacidad

*   **Cifrado Dinámico de PDFs:** Ningún documento que contenga datos financieros del cliente puede ser enviado abierto a través de WhatsApp. El sistema configurará de manera obligatoria una contraseña de apertura para cada PDF (ej. Combinación de las primeras letras de su identificador fiscal RFC junto con los últimos dígitos de su número telefónico validado).
*   **Políticas de Opt-in Obligatorio:** Antes de activar cualquier flujo saliente (especialmente el envío mensual del Caso de Uso 3), el cliente debe otorgar su consentimiento explícito de comunicación financiera en la aplicación web o móvil principal.
