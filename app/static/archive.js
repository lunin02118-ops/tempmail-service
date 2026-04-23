const state = {
  token: sessionStorage.getItem("tempmail.archiveToken") || "",
  messages: [],
  selectedMessageId: null,
  selectedMessage: null,
  selectedSourceTab: "text",
};

const el = {
  authForm: document.querySelector("#archive-auth"),
  token: document.querySelector("#archive-token"),
  searchForm: document.querySelector("#archive-search"),
  query: document.querySelector("#archive-query"),
  refresh: document.querySelector("#archive-refresh"),
  status: document.querySelector("#archive-status"),
  list: document.querySelector("#archive-list"),
  detail: document.querySelector("#archive-detail"),
};

function setStatus(message, tone = "neutral") {
  el.status.textContent = message;
  el.status.dataset.tone = tone;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) {
    return "unknown time";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function senderLabel(message) {
  return message.sender_brand || message.from_address || "unknown sender";
}

function formatRawPayload(rawValue) {
  const raw = String(rawValue || "").trim();
  if (!raw) {
    return "";
  }
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function getSourceTabs(message) {
  const tabs = [];
  if (String(message?.body_text || "").trim()) {
    tabs.push("text");
  }
  if (String(message?.body_html || "").trim()) {
    tabs.push("html");
  }
  if (String(message?.raw_payload_json || "").trim()) {
    tabs.push("raw");
  }
  return tabs.length ? tabs : ["text"];
}

function sourceTabLabel(tab) {
  if (tab === "html") {
    return "HTML";
  }
  if (tab === "raw") {
    return "Raw JSON";
  }
  return "Text";
}

function resolveSourceTab(message) {
  const tabs = getSourceTabs(message);
  return tabs.includes(state.selectedSourceTab) ? state.selectedSourceTab : tabs[0];
}

async function api(path) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "X-Archive-Admin-Token": state.token,
    },
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return response.json();
}

function renderList() {
  if (!state.messages.length) {
    el.list.className = "archive-list empty";
    el.list.innerHTML = "<p>No messages matched this archive query.</p>";
    return;
  }

  el.list.className = "archive-list";
  el.list.innerHTML = state.messages
    .map((message) => {
      const selected = Number(message.id) === Number(state.selectedMessageId) ? " is-selected" : "";
      const unread = message.is_unread ? '<span class="unread-dot" aria-label="Unread"></span>' : "";
      const code = message.otp_code ? `<span class="code-badge">${escapeHtml(message.otp_code)}</span>` : "";
      return `
        <button class="message-row${selected}" type="button" data-message-id="${message.id}">
          <span class="message-row-main">
            <span class="message-row-title">
              <strong>${escapeHtml(message.subject || "No subject")}</strong>
              ${unread}
            </span>
            <small>${escapeHtml(senderLabel(message))} / ${formatDate(message.received_at)}</small>
            <span>${escapeHtml(message.mailbox_address)}</span>
          </span>
          ${code}
        </button>
      `;
    })
    .join("");
}

function renderSource(message) {
  const activeTab = resolveSourceTab(message);
  state.selectedSourceTab = activeTab;
  const tabs = getSourceTabs(message)
    .map(
      (tab) => `
        <button
          class="source-tab${tab === activeTab ? " is-active" : ""}"
          type="button"
          data-source-tab="${tab}"
        >
          ${sourceTabLabel(tab)}
        </button>
      `,
    )
    .join("");

  let body = '<pre class="source-pre">Original content is missing for this message.</pre>';
  if (activeTab === "html" && String(message.body_html || "").trim()) {
    body = `
      <div class="source-preview">
        <div class="source-frame-wrap">
          <iframe class="source-frame" title="Archived HTML email preview" sandbox data-html-preview></iframe>
        </div>
        <pre class="source-pre">${escapeHtml(message.body_html)}</pre>
      </div>
    `;
  } else if (activeTab === "raw" && String(message.raw_payload_json || "").trim()) {
    body = `<pre class="source-pre">${escapeHtml(formatRawPayload(message.raw_payload_json))}</pre>`;
  } else if (String(message.body_text || "").trim()) {
    body = `<pre class="source-pre">${escapeHtml(message.body_text)}</pre>`;
  }

  return `
    <section class="source-card">
      <div class="source-head">
        <small>Original message</small>
        <div class="source-tabs">${tabs}</div>
      </div>
      ${body}
    </section>
  `;
}

function mountHtmlPreview(message) {
  const frame = el.detail.querySelector("[data-html-preview]");
  if (!frame) {
    return;
  }
  const html = String(message.body_html || "").trim();
  frame.srcdoc = `
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <style>
          body {
            margin: 0;
            padding: 16px;
            color: #172130;
            font: 15px/1.45 "Segoe UI", Arial, sans-serif;
            background: #fffdf7;
            overflow-wrap: anywhere;
          }
          img, table { max-width: 100%; }
          pre { white-space: pre-wrap; }
          a { color: #9d2b18; }
        </style>
      </head>
      <body>${html}</body>
    </html>
  `;
}

function renderDetail(message) {
  state.selectedMessage = message;
  const analysis = message.analysis || {};
  const code = analysis.otp_code || message.otp_code || "none";
  el.detail.className = "archive-detail";
  el.detail.innerHTML = `
    <section class="detail-heading">
      <small>Subject</small>
      <h2>${escapeHtml(message.subject || "No subject")}</h2>
    </section>
    <section class="detail-grid">
      <div class="detail-box">
        <small>Mailbox</small>
        <strong>${escapeHtml(message.mailbox_address)}</strong>
      </div>
      <div class="detail-box">
        <small>From</small>
        <strong>${escapeHtml(senderLabel(message))}</strong>
        ${message.from_address ? `<span>${escapeHtml(message.from_address)}</span>` : ""}
      </div>
      <div class="detail-box">
        <small>Received</small>
        <strong>${formatDate(message.received_at)}</strong>
      </div>
      <div class="detail-box">
        <small>Code</small>
        <strong>${escapeHtml(code)}</strong>
      </div>
    </section>
    <section class="detail-box">
      <small>Analyzer</small>
      <p>${escapeHtml(analysis.summary || message.ai_summary || "No AI summary stored.")}</p>
    </section>
    ${renderSource(message)}
  `;
  mountHtmlPreview(message);
}

async function loadArchive() {
  if (!state.token) {
    setStatus("Enter the admin password to load mail.");
    return;
  }
  const q = el.query.value.trim();
  const params = new URLSearchParams({ limit: "500" });
  if (q) {
    params.set("q", q);
  }
  setStatus("Loading archive...");
  state.messages = await api(`/admin/archive/messages?${params.toString()}`);
  renderList();
  setStatus(`${state.messages.length} archived message${state.messages.length === 1 ? "" : "s"} loaded.`, "success");
}

async function selectMessage(messageId) {
  state.selectedMessageId = messageId;
  renderList();
  setStatus("Opening archived email...");
  const message = await api(`/admin/archive/messages/${messageId}`);
  renderDetail(message);
  setStatus(`Opened ${message.subject || "message"}.`, "success");
}

el.token.value = state.token;
if (state.token) {
  loadArchive().catch((error) => setStatus(error.message, "error"));
}

el.authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.token = el.token.value.trim();
  if (state.token) {
    sessionStorage.setItem("tempmail.archiveToken", state.token);
  } else {
    sessionStorage.removeItem("tempmail.archiveToken");
  }
  loadArchive().catch((error) => setStatus(error.message, "error"));
});

el.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  loadArchive().catch((error) => setStatus(error.message, "error"));
});

el.refresh.addEventListener("click", () => {
  loadArchive().catch((error) => setStatus(error.message, "error"));
});

el.list.addEventListener("click", (event) => {
  const row = event.target.closest("[data-message-id]");
  if (!row) {
    return;
  }
  selectMessage(Number(row.dataset.messageId)).catch((error) => setStatus(error.message, "error"));
});

el.detail.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-source-tab]");
  if (!tab || !state.selectedMessage) {
    return;
  }
  state.selectedSourceTab = tab.dataset.sourceTab || "text";
  renderDetail(state.selectedMessage);
});
