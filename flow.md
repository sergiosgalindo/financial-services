### 🎯 Flujo de Ejecución del Script Simulado

1. **Recepción del Webhook:** Cuando el cliente escribe al WhatsApp de la financiera *"necesito dinero"*, la API de Meta redirige el JSON al endpoint `/v1/webhooks/whatsapp`.
2. **Validación del Estado:** El script comprueba en la base relacional si el número telefónico existe y si tiene el `opt_in_whatsapp` en `True`.
3. **Inferencia Financiera:** Al detectar la intención de simulación, ejecuta la lógica matemática de cuotas, detectando dinámicamente si se le ofrece *Préstamo Personal* (plazo mensual largo) o *Dinero Express* (plazo semanal corto) según su perfil.
4. **Seguridad Documental:** Envía la información al subproceso de renderizado para compilar y aplicar la contraseña del PDF combinando la metadata confidencial del usuario (`rfc_curp` + `telefono_whatsapp`), depositándolo en la nube de almacenamiento.
5. **Activación del RAG:** Si el usuario no simula, sino que hace preguntas como *"¿Cómo calculan el interés?"*, el script desvía el flujo al bloque de ejecución RAG, recupera las cláusulas normativas exactas del contrato de la base de datos y le da una respuesta con blindaje legal.


Con este script simulado, la arquitectura propuesta queda completamente funcional a nivel de prototipo de código. Dime cómo te gustaría proceder:
* ¿Quieres que añadamos el endpoint para simular la **Llamada de Voz Automatizada (IVR de Validación)** con Twilio del Caso de Uso 02?
* ¿Prefieres generar una **suite de pruebas unitarias (Testing)** con datos de prueba estructurados para validar los cálculos de las cuotas?
