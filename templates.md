## 5. Catálogo de Plantillas de Mensajes de WhatsApp (Componentes HSM)

Las siguientes plantillas corresponden a mensajes salientes estructurados de tipo transaccional ("Utility"). Deben registrarse y aprobarse en el Meta Business Suite antes de su implementación en producción.

### Plantilla HSM - CU-01: Entrega de Tabla de Amortización (Simulación)
* **Nombre de la plantilla:** `prestamos_simulacion_pdf`
* **Categoría:** Utility (Utilidad)
* **Texto de la Plantilla:**
> "Hola, {{1}}. 📊 Hemos generado con éxito la simulación para tu {{2}}. Adjunto a este mensaje encontrarás tu **Tabla de Amortización en PDF** con el desglose de tus cuotas proyectadas de forma transparente. 
> 
> * Recuerda que este documento tiene una vigencia de {{3}} horas. 
> * Para abrir el archivo, utiliza como contraseña tus {{4}}.
> 
> Si tienes alguna duda conceptual sobre las tasas o el CAT, escríbela aquí mismo y nuestro asistente inteligente te responderá de inmediato."

### Plantilla HSM - CU-02: Bloqueo de Seguridad y Token (Validación de Contratos)
* **Nombre de la plantilla:** `seguridad_validacion_contrato`
* **Categoría:** Authentication / Utility
* **Texto de la Plantilla:**
> "Estimado(a) {{1}}, tu solicitud de {{2}} ha sido preaprobada con éxito. 🎉
> 
> 🔒 Por motivos de seguridad y para mitigar fraudes de suplantación de identidad, **recibirás una llamada telefónica automatizada en los próximos 60 segundos** en tu línea registrada. Por favor, escucha las instrucciones y confirma tu identidad.
> 
> Una vez validado el canal de voz, liberaremos tu contrato digital en este chat para su firma formal."

### Plantilla HSM - CU-03: Distribución de Estado de Cuenta Mensual
* **Nombre de la plantilla:** `finanzas_corte_mensual`
* **Categoría:** Utility (Utilidad)
* **Texto de la Plantilla:**
> "Hola, {{1}}. Te informamos que tu estado de cuenta de {{2}} ha cortado. 📆
> 
> * **Pago Mínimo / Mensualidad:** \${{3}}
> * **Fecha Límite de Pago:** {{4}}
> 
> Hemos adjuntado tu **Estado de Cuenta Oficial en PDF** protegido para tu revisión. Recuerda que puedes realizar tu abono mediante transferencia SPEI o depósito en tiendas de conveniencia de forma inmediata. Si no reconoces algún cargo, responde a este mensaje para ayudarte a iniciar una aclaración."

### Plantilla HSM - CU-04: Confirmación y Recibo Transaccional
* **Nombre de la plantilla:** `pago_conciliado_comprobante`
* **Categoría:** Utility (Utilidad)
* **Texto de la Plantilla:**
> "¡Pago Recibido, {{1}}! ✅ 
> Hemos procesado exitosamente tu abono de \${{2}} a tu {{3}}. 
> 
> En el archivo **PDF adjunto** compartimos tu comprobante digital de pago y el saldo actualizado de tu cuenta. Agradecemos tu puntualidad en el ecosistema financiero. ¡Gracias por tu confianza!"

---

## 6. Arquitectura Técnica del Sistema Omnicanal

La solución requiere una infraestructura desacoplada basada en microservicios, utilizando un patrón de diseño orientado a eventos (Event-Driven Architecture) para garantizar la concurrencia masiva y la consistencia eventual de los saldos financieros.

### 📐 Diagrama de Bloques Funcional

