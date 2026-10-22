// Fintech AI Assistant — ChatGPT Web Interface & WhatsApp Orchestrator

const chatMessages = document.getElementById("chatMessages");
const welcomeState = document.getElementById("welcomeState");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const openMenuBtn = document.getElementById("openMenuBtn");
const customerSelect = document.getElementById("customerSelect");
const healthIndicator = document.getElementById("healthIndicator");
const healthLabel = document.getElementById("healthLabel");
const resetChatBtn = document.getElementById("resetChatBtn");

// Technical Drawer Elements
const sourcesList = document.getElementById("sourcesList");
const customersList = document.getElementById("customersList");
const refreshCustomersBtn = document.getElementById("refreshCustomersBtn");
const loanSimForm = document.getElementById("loanSimForm");
const simResultBox = document.getElementById("simResultBox");

// WhatsApp Bottom Sheet Modal Elements
const waOptionsOverlay = document.getElementById("waOptionsOverlay");
const waSheetRows = document.getElementById("waSheetRows");
const closeWaSheetBtn = document.getElementById("closeWaSheetBtn");
const whatsappFloatingBtn = document.getElementById("whatsappFloatingBtn");

let sessionId = "web-chatgpt-" + Math.random().toString(36).substring(2, 9);
let isGenerating = false;

// Default WhatsApp Catalog Menu Rows
const DEFAULT_WA_MENU_ROWS = [
  {
    id: "menu_solicitar_prestamo",
    title: "Solicitar préstamo 💰",
    description: "Personal o negocio con simulación inmediata",
  },
  {
    id: "menu_prestamo_negocio",
    title: "Préstamo para negocio 💼",
    description: "Impulso para tu comercio o inversión",
  },
  {
    id: "menu_dinero_express",
    title: "Dinero Express ⚡",
    description: "Microcrédito rápido de 7 a 28 días",
  },
  {
    id: "menu_estado_cuenta",
    title: "Estado de cuenta 🧾",
    description: "Consulta tu saldo, corte y cuotas vigentes",
  },
  {
    id: "menu_hacer_abono",
    title: "Hacer un abono 💳",
    description: "Referencia para pagar por SPEI u OXXO",
  },
  {
    id: "menu_validar_contrato",
    title: "Validar contrato 🔐",
    description: "Activa tu crédito con tu código OTP de voz",
  },
  {
    id: "menu_seguir_folio",
    title: "Seguir folio 📄",
    description: "Consulta reportes y cargos no reconocidos",
  },
  {
    id: "menu_banco_cat",
    title: "Tasas, CAT y beneficios 🔑",
    description: "Información general y $0 penalización",
  },
  {
    id: "menu_hablar_asesor",
    title: "Hablar con asesor 👤",
    description: "Atención especializada con un asesor humano",
  },
];

// Formatting helper: converts markdown-like asterisks and bullets into clean HTML
function formatMessageContent(text) {
  if (!text) return "";
  let safe = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Bold *text*
  safe = safe.replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>");

  // Italic _text_
  safe = safe.replace(/_([^_ \n][^_\n]*[^_ \n])_/g, "<em>$1</em>");

  // Bullet points
  safe = safe.replace(/^•\s+(.+)$/gm, "<li>$1</li>");
  safe = safe.replace(/(<li>.+<\/li>\n?)+/g, "<ul>$&</ul>");

  // Line breaks
  safe = safe.replace(/\n/g, "<br>");

  return safe;
}

// Auto-adjust textarea height
function adjustTextareaHeight() {
  messageInput.style.height = "auto";
  const newHeight = Math.min(messageInput.scrollHeight, 140);
  messageInput.style.height = `${newHeight}px`;
  sendBtn.disabled = messageInput.value.trim().length === 0 || isGenerating;
}

messageInput.addEventListener("input", adjustTextareaHeight);

// Submit on Enter (without Shift)
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!sendBtn.disabled) {
      chatForm.dispatchEvent(new Event("submit"));
    }
  }
});

// Render WhatsApp Interactive Bottom-Sheet Modal
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
openMenuBtn.addEventListener("click", () => openWaSheet());

// Append Chat Message Row
function appendMessageRow(role, text, blocked = false, interactiveMenu = null) {
  if (welcomeState && !welcomeState.classList.contains("d-none")) {
    welcomeState.classList.add("d-none");
  }

  const row = document.createElement("div");
  row.className = `chat-message-row ${role === "user" ? "user-row" : "assistant-row"}`;

  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/>
        <path d="M12 6v6l4 2"/>
      </svg>
    `;
    row.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${blocked ? "blocked" : role}`;
  bubble.innerHTML = formatMessageContent(text);

  // If interactive menu exists, render inline action chips right inside the chat bubble
  if (interactiveMenu && role === "assistant") {
    const sections = (interactiveMenu.action && interactiveMenu.action.sections) || [];
    const rows = (sections[0] && sections[0].rows) || [];

    if (rows.length > 0) {
      const optionsBox = document.createElement("div");
      optionsBox.className = "wa-options-box";

      const label = document.createElement("div");
      label.className = "wa-options-label";
      label.textContent = (interactiveMenu.action && interactiveMenu.action.button) || "Opciones:";
      optionsBox.appendChild(label);

      const grid = document.createElement("div");
      grid.className = "wa-options-grid";

      rows.forEach((r) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "wa-inline-chip";
        chip.innerHTML = `<span>${r.title}</span>`;
        chip.title = r.description || r.title;
        chip.addEventListener("click", () => {
          sendChatMessage(r.id, r.title);
        });
        grid.appendChild(chip);
      });

      optionsBox.appendChild(grid);

      // Add full menu trigger button
      const fullMenuBtn = document.createElement("button");
      fullMenuBtn.type = "button";
      fullMenuBtn.className = "wa-full-menu-btn";
      fullMenuBtn.innerHTML = `☰ Ver menú de opciones completo`;
      fullMenuBtn.addEventListener("click", () => openWaSheet(interactiveMenu));
      optionsBox.appendChild(fullMenuBtn);

      bubble.appendChild(optionsBox);
    }
  }

  row.appendChild(bubble);
  chatMessages.appendChild(row);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Typing indicator management
let typingRow = null;

function showTypingIndicator() {
  if (typingRow) return;
  if (welcomeState && !welcomeState.classList.contains("d-none")) {
    welcomeState.classList.add("d-none");
  }

  typingRow = document.createElement("div");
  typingRow.className = "chat-message-row assistant-row";

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/>
      <path d="M12 6v6l4 2"/>
    </svg>
  `;
  typingRow.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble assistant";
  bubble.innerHTML = `
    <div class="typing-indicator">
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    </div>
  `;
  typingRow.appendChild(bubble);

  chatMessages.appendChild(typingRow);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function hideTypingIndicator() {
  if (typingRow) {
    typingRow.remove();
    typingRow = null;
  }
}

// Send chat message to backend
async function sendChatMessage(messageText, displayLabel = null) {
  if (!messageText || isGenerating) return;
  const userId = customerSelect.value;

  appendMessageRow("user", displayLabel || messageText);
  messageInput.value = "";
  adjustTextareaHeight();
  isGenerating = true;
  sendBtn.disabled = true;

  showTypingIndicator();

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

    hideTypingIndicator();
    isGenerating = false;
    adjustTextareaHeight();

    if (!res.ok) {
      appendMessageRow("assistant", "Hubo un inconveniente al procesar tu solicitud. Por favor intenta de nuevo.", true);
      return;
    }

    const data = await res.json();
    appendMessageRow("assistant", data.reply, data.safety_blocked, data.interactive_menu);

    // Update Technical Drawer
    updateTechnicalTrace(data);
  } catch (err) {
    hideTypingIndicator();
    isGenerating = false;
    adjustTextareaHeight();
    appendMessageRow("assistant", "Error de conexión con el servidor. Verifica que el backend esté activo.", true);
  }
}

function updateTechnicalTrace(data) {
  let traceHtml = `
    <div class="mb-2">
      <strong>Caso de Uso:</strong> <span class="badge bg-primary">${data.active_use_case || "General"}</span><br>
  `;
  if (data.tool_executed) {
    traceHtml += `<strong>Herramienta:</strong> <code>${data.tool_executed}</code><br>`;
  }
  traceHtml += `<strong>Memoria Llama Stack:</strong> ${data.conversation_items_count} items</div>`;

  if (data.sources && data.sources.length > 0) {
    traceHtml += '<div class="mt-2 text-secondary fw-semibold">Fragmentos RAG relevantes:</div>';
    traceHtml += data.sources
      .map(
        (s) => `
        <div class="border-start border-2 border-primary ps-2 mb-2 bg-dark p-2 rounded">
          <strong>[${s.id}] ${s.category}</strong> (score: ${Number(s.score).toFixed(3)})<br/>
          <small class="text-secondary">${s.question}</small>
        </div>
      `
      )
      .join("");
  }
  sourcesList.innerHTML = traceHtml;
}

// Chat Form submit
chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = messageInput.value.trim();
  if (text) {
    sendChatMessage(text);
  }
});

// Quick starter cards
document.querySelectorAll(".quick-prompt").forEach((btn) => {
  btn.addEventListener("click", () => {
    const prompt = btn.getAttribute("data-prompt");
    if (prompt) {
      sendChatMessage(prompt);
    }
  });
});

// Reset conversation
resetChatBtn.addEventListener("click", async () => {
  try {
    await fetch("/api/conversation/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (e) {
    // Continue resetting local state
  }
  sessionId = "web-chatgpt-" + Math.random().toString(36).substring(2, 9);
  chatMessages.innerHTML = "";
  if (welcomeState) {
    welcomeState.classList.remove("d-none");
  }
  sourcesList.innerHTML = "Sin consultas recientes.";
  messageInput.value = "";
  adjustTextareaHeight();
});

// Health check
async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    if (data.status === "ok") {
      healthIndicator.className = "health-status online";
      healthLabel.textContent = `${data.llm_model} • RAG (${data.knowledge_base_items})`;
    }
  } catch (err) {
    healthIndicator.className = "health-status offline";
    healthLabel.textContent = "Desconectado";
  }
}

// Load customers for drawer
async function loadCustomers() {
  try {
    const res = await fetch("/v1/customers");
    const customers = await res.json();
    customersList.innerHTML = customers
      .map((c) => {
        const accBadges = c.credit_accounts
          .map(
            (a) =>
              `<span class="badge bg-secondary me-1 mb-1">${a.contract_id}: $${Number(a.available_balance).toLocaleString()} (${a.credit_status})</span>`
          )
          .join("");
        const logsCount = c.recent_communications.length;
        return `
          <div class="border border-secondary rounded p-2 mb-2 bg-dark">
            <div class="d-flex justify-content-between align-items-center">
              <strong class="text-light">${c.full_name}</strong>
              <span class="badge ${c.account_status === "ACTIVO" ? "bg-success" : "bg-danger"}">${c.account_status}</span>
            </div>
            <div class="small text-secondary mt-1">Tel: ${c.whatsapp_phone} • RFC: ${c.tax_id_rfc}</div>
            <div class="mt-2">${accBadges || "<span class='text-secondary small'>Sin contratos</span>"}</div>
            <div class="text-muted small mt-1">Bitácora omnicanal: ${logsCount} evento(s)</div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    customersList.textContent = "Error al cargar clientes.";
  }
}

refreshCustomersBtn.addEventListener("click", loadCustomers);

// Direct Loan Simulator in Drawer
loanSimForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const productType = document.getElementById("simProduct").value;
  const amount = parseFloat(document.getElementById("simAmount").value);
  const term = parseInt(document.getElementById("simTerm").value);
  const userId = customerSelect.value;

  simResultBox.innerHTML = "Calculando simulación...";

  try {
    const res = await fetch("/v1/loans/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        product_type: productType,
        requested_amount: amount,
        term_months: productType === "DINERO_EXPRESS" ? null : term,
        term_days: productType === "DINERO_EXPRESS" ? term : null,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      simResultBox.innerHTML = `<span class="text-danger">${data.detail || "Error en simulación"}</span>`;
      return;
    }

    simResultBox.innerHTML = `
      <div class="border border-success rounded p-2 bg-dark">
        <strong class="text-success">${data.product_name}</strong><br>
        • Monto: $${Number(data.requested_amount).toLocaleString()} MXN<br>
        • Cuota: <strong>$${Number(data.periodic_payment).toLocaleString()} MXN</strong> (${data.periods} pagos)<br>
        • Total a pagar: $${Number(data.total_to_pay).toLocaleString()} MXN<br>
        • CAT Promedio: ${data.average_cat}% (sin IVA)<br>
        • Contraseña PDF Cifrado: <code>${data.pdf_password}</code>
      </div>
    `;
  } catch (err) {
    simResultBox.innerHTML = `<span class="text-danger">Error de conexión: ${err.message}</span>`;
  }
});

// Update WhatsApp Floating Link based on selected customer
customerSelect.addEventListener("change", () => {
  const selected = customerSelect.value;
  let text = "Hola, me gustaría solicitar un préstamo";
  if (selected === "usr-carlos-001") {
    text = "Hola, soy Carlos Mendoza y quiero información de mi crédito";
  } else if (selected === "usr-ana-002") {
    text = "Hola, soy Ana Sofía Garza y quiero validar mi contrato";
  }
  whatsappFloatingBtn.href = `https://wa.me/15551566290?text=${encodeURIComponent(text)}`;
});

// Initial boot
checkHealth();
loadCustomers();
adjustTextareaHeight();
