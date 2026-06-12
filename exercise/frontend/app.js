/* ── Agentic BI Assistant — frontend ──────────────────────────────────── */

"use strict";

// ── State ──────────────────────────────────────────────────────────────────
let userId      = null;   // SHA-256 derived from fingerprint + localStorage UUID
let convId      = null;   // active conversation UUID
let chartCount  = 0;      // unique IDs for canvas elements
let isWaiting   = false;

// ── DOM refs ───────────────────────────────────────────────────────────────
const messagesEl    = document.getElementById("messages");
const emptyStateEl  = document.getElementById("empty-state");
const inputEl       = document.getElementById("msg-input");
const sendBtn       = document.getElementById("send-btn");
const convListEl    = document.getElementById("conv-list");
const tokenDisplay  = document.getElementById("token-display");
const modalOverlay  = document.getElementById("modal-overlay");
const prevConvList  = document.getElementById("prev-conv-list");
const resumeBanner  = document.getElementById("resume-banner");

// ── Fingerprint / user identity ────────────────────────────────────────────
async function deriveUserId() {
  let deviceId = localStorage.getItem("bi_device_id");
  if (!deviceId) {
    deviceId = crypto.randomUUID();
    localStorage.setItem("bi_device_id", deviceId);
  }
  const fp = [
    navigator.userAgent,
    navigator.language,
    `${screen.width}x${screen.height}`,
    Intl.DateTimeFormat().resolvedOptions().timeZone,
    navigator.platform,
  ].join("|");
  const combined = fp + "|" + deviceId;
  const buf      = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(combined));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

// ── Initialisation ─────────────────────────────────────────────────────────
async function init() {
  userId = await deriveUserId();
  const convs = await fetchConversations();

  if (convs.length === 0) {
    // First-time user — create a conversation and go straight to chat
    await startNewConversation();
  } else if (convs.length === 1) {
    // Single previous conversation — offer to continue or start new
    showModal(convs);
  } else {
    showModal(convs);
  }

  document.getElementById("new-btn").addEventListener("click", startNewConversation);
  document.getElementById("modal-new-btn").addEventListener("click", () => {
    closeModal();
    startNewConversation();
  });
  document.getElementById("input-form").addEventListener("submit", handleSubmit);

  inputEl.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("input-form").requestSubmit();
    }
  });

  // Auto-resize textarea
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + "px";
  });
}

// ── Conversation management ────────────────────────────────────────────────
async function fetchConversations() {
  const r = await fetch(`/api/conversations?user_id=${encodeURIComponent(userId)}`);
  return r.ok ? r.json() : [];
}

async function startNewConversation() {
  closeModal();
  const r = await fetch("/api/conversations", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ user_id: userId }),
  });
  const data = await r.json();
  convId = data.conversation_id;
  clearMessages();
  resumeBanner.className = "";
  resumeBanner.innerHTML = "";
  enableInput();
  refreshSidebar();
}

async function loadConversation(id) {
  convId = id;
  clearMessages();
  resumeBanner.className = "";
  resumeBanner.innerHTML = "";

  // Fetch display history (summary + last 6 messages)
  const r = await fetch(`/api/conversations/${id}/history`);
  const hist = await r.json();

  if (hist.summary || (hist.recent_messages && hist.recent_messages.length)) {
    showResumeBanner(hist.summary, hist.recent_messages);
  }

  enableInput();
  refreshSidebar(id);
}

async function refreshSidebar(activeId) {
  const convs = await fetchConversations();
  convListEl.innerHTML = "";
  convs.forEach(c => {
    const el = document.createElement("div");
    el.className = "conv-item" + (c.id === (activeId || convId) ? " active" : "");
    const date = new Date(c.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    el.innerHTML = `
      <div class="conv-title">${escHtml(c.title || "Untitled")}</div>
      <div class="conv-meta">${date} · ${c.message_count} messages</div>`;
    el.addEventListener("click", () => {
      closeModal();
      loadConversation(c.id);
    });
    convListEl.appendChild(el);
  });
}

// ── Modal ──────────────────────────────────────────────────────────────────
function showModal(convs) {
  prevConvList.innerHTML = "";
  convs.forEach(c => {
    const el = document.createElement("div");
    el.className = "prev-conv-item";
    const date = new Date(c.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    el.innerHTML = `
      <div class="pci-title">${escHtml(c.title || "Untitled")}</div>
      <div class="pci-meta">${date} · ${c.message_count} message${c.message_count !== 1 ? "s" : ""}</div>`;
    el.addEventListener("click", () => {
      closeModal();
      loadConversation(c.id);
    });
    prevConvList.appendChild(el);
  });
  modalOverlay.classList.add("open");
  refreshSidebar();
}

function closeModal() { modalOverlay.classList.remove("open"); }

// ── Resume banner ──────────────────────────────────────────────────────────
function showResumeBanner(summary, recentMessages) {
  let html = "";

  if (summary) {
    html += `
      <details>
        <summary>📋 AI-generated summary of previous session</summary>
        <div class="resume-summary-text">${escHtml(summary)}</div>
        <div class="resume-warning">⚠ This summary is AI-generated and may not capture every detail.</div>
      </details>`;
  }

  if (recentMessages && recentMessages.length) {
    html += `<div style="margin-top:.5rem;font-size:.78rem;opacity:.7;">
      Last ${recentMessages.length} message${recentMessages.length !== 1 ? "s" : ""} restored below ↓</div>`;
  }

  resumeBanner.innerHTML = html;
  resumeBanner.className = "visible";

  // Render the last few messages as read-only history
  if (recentMessages && recentMessages.length) {
    showMessages();
    recentMessages.forEach(m => {
      appendMessage(m.role, m.content, null, null, null, true);
    });
    const divider = document.createElement("div");
    divider.style.cssText = "text-align:center;color:#94a3b8;font-size:.75rem;padding:.5rem 0;";
    divider.textContent   = "── conversation continues ──";
    messagesEl.appendChild(divider);
  }
}

// ── Message rendering ──────────────────────────────────────────────────────
function clearMessages() {
  messagesEl.innerHTML = "";
  emptyStateEl.style.display = "";
  messagesEl.style.display   = "none";
}

function showMessages() {
  emptyStateEl.style.display = "none";
  messagesEl.style.display   = "flex";
}

function appendMessage(role, text, data, sql, usage, readOnly = false) {
  showMessages();
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  if (role === "assistant" && !data && !sql) wrap.classList.add("clarification");

  // Text bubble
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);

  // Data render (table or chart)
  if (data && data.columns && data.rows && data.rows.length > 0 && !readOnly) {
    const renderType = _guessRenderFromData(data);
    const renderEl   = buildDataRender(renderType, data);
    if (renderEl) wrap.appendChild(renderEl);
  }

  // SQL accordion
  if (sql && !readOnly) {
    wrap.appendChild(buildSqlBlock(sql));
  }

  // Token badge
  if (usage && !readOnly) {
    const badge = document.createElement("div");
    badge.className = "token-badge" + (usage.context_mode === "summarised" ? " summarised" : "");
    const icon = usage.context_mode === "summarised" ? "⚡ summarised ·" : "🔢";
    badge.textContent = `${icon} ${usage.prompt_tokens} in · ${usage.completion_tokens} out · ${usage.total_tokens} total`;
    badge.title = `Conversation total: ${usage.conversation_total_tokens} tokens`;
    wrap.appendChild(badge);
    updateTokenDisplay(usage);
  }

  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrap;
}

function appendTyping() {
  showMessages();
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  wrap.id = "typing-indicator";
  wrap.innerHTML = '<div class="typing"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

// ── Data renders ───────────────────────────────────────────────────────────
function _guessRenderFromData(data) {
  // Helper: if we have render info from the server response we use that,
  // otherwise guess from shape. Called with the render type already known
  // in the main flow — this is a fallback for read-only history renders.
  if (data.columns.length === 2) return "bar_chart";
  return "table";
}

function buildDataRender(renderType, data) {
  const wrap = document.createElement("div");
  wrap.className = "data-render";

  if (renderType === "table") {
    wrap.appendChild(buildTable(data));
  } else if (["bar_chart", "line_chart", "pie_chart"].includes(renderType)) {
    wrap.appendChild(buildChart(renderType, data));
  } else {
    // fallback
    if (data.rows.length > 0) wrap.appendChild(buildTable(data));
  }

  if (data.truncated) {
    const note = document.createElement("p");
    note.className = "truncated-note";
    note.textContent = "⚠ Results truncated — refine your query to see more.";
    wrap.appendChild(note);
  }

  return wrap;
}

function buildTable(data) {
  const outer = document.createElement("div");
  outer.className = "data-table-wrap";
  const table = document.createElement("table");
  table.className = "data-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  data.columns.forEach(col => {
    const th = document.createElement("th");
    th.textContent = col;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.rows.forEach(row => {
    const tr = document.createElement("tr");
    row.forEach(cell => {
      const td = document.createElement("td");
      td.textContent = cell === null ? "—" : String(cell);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  outer.appendChild(table);
  return outer;
}

function buildChart(renderType, data) {
  const wrap     = document.createElement("div");
  wrap.className = "chart-wrap";
  const canvas   = document.createElement("canvas");
  canvas.id      = `chart-${++chartCount}`;
  canvas.style.maxHeight = "320px";
  wrap.appendChild(canvas);

  // Defer rendering until after the element is in the DOM
  requestAnimationFrame(() => {
    const labels = data.rows.map(r => String(r[0] ?? "—"));
    const values = data.rows.map(r => parseFloat(r[1]) || 0);

    const palette = [
      "#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6",
      "#06b6d4","#84cc16","#f97316","#ec4899","#6366f1",
    ];

    const config = {
      bar_chart: {
        type: "bar",
        data: {
          labels,
          datasets: [{ label: data.columns[1] || "Value", data: values,
            backgroundColor: palette, borderRadius: 4 }],
        },
        options: { plugins: { legend: { display: false } }, responsive: true,
          scales: { y: { beginAtZero: true } } },
      },
      line_chart: {
        type: "line",
        data: {
          labels,
          datasets: [{ label: data.columns[1] || "Value", data: values,
            borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.1)",
            fill: true, tension: .3, pointRadius: 3 }],
        },
        options: { plugins: { legend: { display: false } }, responsive: true,
          scales: { y: { beginAtZero: true } } },
      },
      pie_chart: {
        type: "pie",
        data: {
          labels,
          datasets: [{ data: values, backgroundColor: palette }],
        },
        options: { responsive: true,
          plugins: { legend: { position: "right" } } },
      },
    };

    new Chart(canvas, config[renderType] || config.bar_chart);
  });

  return wrap;
}

function buildSqlBlock(sql) {
  const block = document.createElement("div");
  block.className = "sql-block";

  const toggle = document.createElement("button");
  toggle.className = "sql-toggle";
  toggle.type = "button";
  toggle.innerHTML = '<span class="arrow">▶</span> View SQL';

  const code = document.createElement("pre");
  code.className = "sql-code";
  code.textContent = sql;

  toggle.addEventListener("click", () => {
    const open = code.classList.toggle("visible");
    toggle.classList.toggle("open", open);
    toggle.innerHTML = `<span class="arrow">▶</span> ${open ? "Hide" : "View"} SQL`;
  });

  block.appendChild(toggle);
  block.appendChild(code);
  return block;
}

// ── Token display ──────────────────────────────────────────────────────────
function updateTokenDisplay(usage) {
  tokenDisplay.className = usage.context_mode === "summarised" ? "summarised" : "";
  const icon = usage.context_mode === "summarised" ? "⚡" : "🔢";
  tokenDisplay.textContent =
    `${icon} ${usage.total_tokens.toLocaleString()} tokens · conv: ${usage.conversation_total_tokens.toLocaleString()}`;
  tokenDisplay.title =
    `Last turn: ${usage.prompt_tokens} prompt + ${usage.completion_tokens} completion\n` +
    `Conversation total: ${usage.conversation_total_tokens}\n` +
    `Context mode: ${usage.context_mode}`;
}

// ── Submit handler ─────────────────────────────────────────────────────────
async function handleSubmit(e) {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || isWaiting || !convId) return;

  isWaiting = true;
  disableInput();
  appendMessage("user", text);
  inputEl.value = "";
  inputEl.style.height = "auto";
  appendTyping();

  try {
    const r = await fetch("/api/chat", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ conversation_id: convId, message: text, user_id: userId }),
    });

    removeTyping();

    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      appendMessage("assistant", `Error: ${err.detail || r.statusText}`);
    } else {
      const resp = await r.json();
      // Determine render type
      const render = resp.needs_clarification ? "text" : (resp.render || "text");
      appendMessage(
        "assistant",
        resp.answer,
        render !== "text" ? resp.data : null,
        resp.sql || null,
        resp.usage || null,
      );
      // If render is text but there's data, show a table anyway
      if (render === "text" && resp.data && resp.data.rows && resp.data.rows.length > 0) {
        appendMessage("assistant", "", resp.data, null, null);
      }
    }
  } catch (err) {
    removeTyping();
    appendMessage("assistant", `Network error: ${err.message}`);
  } finally {
    isWaiting = false;
    enableInput();
    refreshSidebar();
  }
}

// ── Input helpers ──────────────────────────────────────────────────────────
function enableInput()  { inputEl.disabled = false; sendBtn.disabled = false; inputEl.focus(); }
function disableInput() { inputEl.disabled = true;  sendBtn.disabled = true; }

// ── Utility ────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Boot ───────────────────────────────────────────────────────────────────
init().catch(err => console.error("Init failed:", err));
