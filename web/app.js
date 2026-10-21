const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const customerSelect = document.getElementById("customerSelect");
const healthBadge = document.getElementById("healthBadge");
const resetBtn = document.getElementById("resetBtn");
const sourcesList = document.getElementById("sourcesList");
const customersList = document.getElementById("customersList");
const refreshCustomersBtn = document.getElementById("refreshCustomersBtn");
const loanSimForm = document.getElementById("loanSimForm");
const simResultBox = document.getElementById("simResultBox");

const waOptionsOverlay = document.getElementById("waOptionsOverlay");
const waSheetRows = document.getElementById("waSheetRows");
const closeWaSheetBtn = document.getElementById("closeWaSheetBtn");
const openOptionsTopBtn = document.getElementById("openOptionsTopBtn");
const openOptionsQuickBtn = document.getElementById("openOptionsQuickBtn");
const openOptionsInputBtn = document.getElementById("openOptionsInputBtn");

const sessionId = "web-fintech-" + Math.random().toString(36).substring(2, 8);

const DEFAULT_WA_MENU_ROWS = [
  {
    id: "menu_estado_cuenta",
    title: "Estado de cuenta 🧾",
    description: "Consulta tu saldo y fechas de pago",
  },
  {
    id: "menu_hacer_abono",
    title: "Hacer un abono 💳",
    description: "Abona fácil y rápido por SPEI u OXXO",
  },
  {
    id: "menu_solicitar_prestamo",
    title: "Solicitar préstamo 💰",
    description: "Recibe tu préstamo con tabla de pagos",
  },
  {
    id: "menu_dinero_express",
    title: "Dinero Express ⚡",
    description: "Microcrédito rápido de 7 a 28 días",
  },
  {
    id: "menu_validar_contrato",
    title: "Validar contrato 🔐",
    description: "Activa tu crédito con tu código OTP",
  },
  {
    id: "menu_seguir_folio",
    title: "Seguir folio 📄",
    description: "Consulta reportes y cargos no reconocidos",
  },
  {
    id: "menu_banco_cat",
    title: "Banco y Tasas CAT 🔑",
    description: "Información general, MSI y contraseñas PDF",
  },
  {
    id: "menu_hablar_asesor",
    title: "Hablar con asesor 👤",
    description: "Atención ejecutiva personalizada",
  },
];

function renderWaSheetMenu(menuPayload) {
  let rows = DEFAULT_WA_MENU_ROWS;
  if (
    menuPayload &&
    menuPayload.action &&
    Array.isArray(menuPayload.action.sections) &&
    menuPayload.action.sections[0] &&
    Array.isArray(menuPayload.action.sections[0].rows)
  ) {
    rows = menuPayload.action.sections[0].rows;
  }

  waSheetRows.innerHTML = rows
    .map(
      (r) => `
      <div class="wa-sheet-row" data-row-id="${r.id}" data-row-title="${r.title}">
        <div>
          <div class="wa-sheet-row-title">${r.title}</div>
          <div class="wa-sheet-row-desc">${r.description || ""}</div>
        </div>
        <div class="wa-sheet-radio"></div>
      </div>
    `
    )
    .join("");

  waSheetRows.querySelectorAll(".wa-sheet-row").forEach((el) => {
    el.addEventListener("click", () => {
      const rowId = el.getAttribute("data-row-id");
      const rowTitle = el.getAttribute("data-row-title");
      closeWaSheet();
      sendChatMessage(rowId, rowTitle);
    });
  });
}

function openWaSheet(menuPayload = null) {
  renderWaSheetMenu(menuPayload);
  waOptionsOverlay.classList.remove("d-none");
}

function closeWaSheet() {
  waOptionsOverlay.classList.add("d-none");
}

closeWaSheetBtn.addEventListener("click", closeWaSheet);
waOptionsOverlay.addEventListener("click", (e) => {
  if (e.target === waOptionsOverlay) {
    closeWaSheet();
  }
});
openOptionsTopBtn.addEventListener("click", () => openWaSheet());
openOptionsQuickBtn.addEventListener("click", () => openWaSheet());
openOptionsInputBtn.addEventListener("click", () => openWaSheet());

function appendBubble(role, text, blocked = false, interactiveMenu = null) {
  const div = document.createElement("div");
  div.className = `chat-bubble ${blocked ? "blocked" : role}`;
  const textSpan = document.createElement("div");
  textSpan.textContent = text;
  div.appendChild(textSpan);

  if (interactiveMenu && role === "assistant") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wa-inline-menu-btn";
    btn.innerHTML = `<span>☰</span> <span>${
      (interactiveMenu.action && interactiveMenu.action.button) || "Ver opciones"
    }</span>`;
    btn.addEventListener("click", () => openWaSheet(interactiveMenu));
    div.appendChild(btn);
  }

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.status === "ok") {
      healthBadge.className = "badge bg-success";
      healthBadge.textContent = `Online • ${data.llm_model} • RAG (${data.knowledge_base_items})`;
    }
  } catch (err) {
    healthBadge.className = "badge bg-danger";
    healthBadge.textContent = "Offline";
  }
}

async function loadCustomers() {
  try {
    const res = await fetch("/v1/customers");
    const customers = await res.json();
    customersList.innerHTML = customers
      .map((c) => {
        const accBadges = c.credit_accounts
          .map(
            (a) =>
              `<span class="badge bg-light text-dark border me-1">${a.contract_id}: $${a.available_balance.toLocaleString()} (${a.credit_status})</span>`
          )
          .join("");
        const logsCount = c.recent_communications.length;
        return `
          <div class="border rounded p-2 mb-2 bg-light">
            <div class="d-flex justify-content-between">
              <strong>${c.full_name}</strong>
              <span class="badge ${c.account_status === "ACTIVO" ? "bg-success" : "bg-danger"}">${c.account_status}</span>
            </div>
            <div class="text-muted">Tel: ${c.whatsapp_phone} • RFC: ${c.tax_id_rfc} • Opt-in WA: ${c.opt_in_whatsapp ? "Sí" : "No"}</div>
            <div class="mt-1">${accBadges}</div>
            <div class="text-secondary mt-1">Bitácora omnicanal reciente: ${logsCount} evento(s)</div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    customersList.textContent = "Error al cargar clientes.";
  }
}

async function sendChatMessage(messageText, displayLabel = null) {
  const userId = customerSelect.value;
  appendBubble("user", displayLabel || messageText);
  messageInput.value = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: messageText,
        session_id: sessionId,
        user_id: userId,
        top_k: 3,
      }),
    });
    const data = await res.json();
    appendBubble("assistant", data.reply, data.safety_blocked, data.interactive_menu);

    let traceHtml = `<div class="mb-1"><strong>Caso de Uso:</strong> <span class="badge bg-primary">${data.active_use_case || "General"}</span> `;
    if (data.tool_executed) {
      traceHtml += `<strong>Tool:</strong> <code>${data.tool_executed}</code> `;
    }
    traceHtml += `<strong>Items en Memoria:</strong> ${data.conversation_items_count}</div>`;

    if (data.sources && data.sources.length > 0) {
      traceHtml += data.sources
        .map(
          (s) =>
            `<div class="border-start border-3 border-primary ps-2 mb-1"><strong>[${s.id}] ${s.category}</strong> (score: ${s.score})<br/>${s.question}</div>`
        )
        .join("");
    }
    sourcesList.innerHTML = traceHtml;
    await loadCustomers();
  } catch (err) {
    appendBubble("assistant", "Ocurrió un error al procesar tu solicitud.", true);
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (text) {
    sendChatMessage(text);
  }
});

document.querySelectorAll(".quick-prompt").forEach((btn) => {
  btn.addEventListener("click", () => {
    const prompt = btn.getAttribute("data-prompt");
    if (prompt) {
      sendChatMessage(prompt);
    }
  });
});

resetBtn.addEventListener("click", async () => {
  await fetch("/api/conversation/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  chatMessages.innerHTML = "";
  appendBubble(
    "assistant",
    "Conversación reiniciada. Toca 'Ver opciones' abajo o escribe tu consulta financiera (CU-01 a CU-04).",
    false,
    { action: { button: "Ver opciones", sections: [{ rows: DEFAULT_WA_MENU_ROWS }] } }
  );
});

refreshCustomersBtn.addEventListener("click", loadCustomers);

loanSimForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const productType = document.getElementById("simProduct").value;
  const amount = parseFloat(document.getElementById("simAmount").value || "10000");
  const userId = customerSelect.value;

  try {
    const res = await fetch("/v1/loans/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        product_type: productType,
        requested_amount: amount,
        term_months: productType === "PRESTAMO_PERSONAL" ? 6 : null,
        term_days: productType === "DINERO_EXPRESS" ? 14 : null,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      simResultBox.innerHTML = `<div class="text-danger fw-semibold">${data.detail || "Error en simulación"}</div>`;
      return;
    }
    simResultBox.innerHTML = `
      <div class="border rounded p-2 bg-light">
        <div><strong>${data.product_name}</strong> • Cuota Fija: <strong>$${data.periodic_payment.toLocaleString()} MXN</strong> (${data.periods} periodos)</div>
        <div>Total Interés + IVA: $${(data.total_interest + data.total_vat).toLocaleString()} MXN • Total a Pagar: <strong>$${data.total_to_pay.toLocaleString()} MXN</strong></div>
        <div>PDF: <code>${data.pdf_metadata.pdf_filename}</code> • Contraseña: <code>${data.pdf_metadata.derived_password_preview}</code></div>
      </div>
    `;
    await loadCustomers();
  } catch (err) {
    simResultBox.textContent = "Error al conectar con el simulador.";
  }
});

appendBubble(
  "assistant",
  "¡Hola! Soy tu Asistente Financiero 🏦.\nToca 'Ver opciones' para consultar tu saldo, abonar o simular tu préstamo.",
  false,
  { action: { button: "Ver opciones", sections: [{ rows: DEFAULT_WA_MENU_ROWS }] } }
);
checkHealth();
loadCustomers();
