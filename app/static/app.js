const state = {
  config: null,
  sessionToken: localStorage.getItem("tempmail.sessionToken") || "",
  turnstileToken: "",
  turnstileWidgetId: null,
  mailboxes: [],
  messages: [],
  selectedMessageId: null,
  selectedMessage: null,
  selectedSourceTab: "text",
  sharedCodes: [],
};

const el = {
  form: document.querySelector("#mailbox-form"),
  localPart: document.querySelector("#local-part"),
  domainSelect: document.querySelector("#domain-select"),
  description: document.querySelector("#description"),
  ttl: document.querySelector("#ttl"),
  turnstileSlot: document.querySelector("#turnstile-slot"),
  status: document.querySelector("#status"),
  mailboxStrip: document.querySelector("#mailbox-strip"),
  messageList: document.querySelector("#message-list"),
  messageDetail: document.querySelector("#message-detail"),
  refresh: document.querySelector("#refresh"),
  analyze: document.querySelector("#analyze"),
  sharedCodesSection: document.querySelector("#shared-codes"),
  sharedCodesList: document.querySelector("#shared-codes-list"),
  sharedCodesRefresh: document.querySelector("#shared-codes-refresh"),
  sharedCodesTitle: document.querySelector("#shared-codes-title"),
};

function importSharedSessionFromUrl() {
  const searchParams = new URLSearchParams(window.location.search);
  const hashParams = new URLSearchParams(window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "");
  const sessionToken = hashParams.get("session_token") || searchParams.get("session_token") || "";
  const messageIdRaw = hashParams.get("message_id") || searchParams.get("message_id") || "";
  const messageId = Number.parseInt(messageIdRaw, 10);

  if (sessionToken) {
    state.sessionToken = sessionToken;
    localStorage.setItem("tempmail.sessionToken", sessionToken);
  }
  if (Number.isFinite(messageId) && messageId > 0) {
    state.selectedMessageId = messageId;
  }

  if (sessionToken || messageIdRaw) {
    history.replaceState(null, "", window.location.pathname);
  }
}

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

function normalizeLink(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.href;
    }
  } catch {
    return "";
  }
  return "";
}

function uniqueLinks(values) {
  const seen = new Set();
  return values
    .map(normalizeLink)
    .filter(Boolean)
    .filter((link) => {
      if (seen.has(link)) {
        return false;
      }
      seen.add(link);
      return true;
    });
}

function describeLink(link) {
  try {
    const url = new URL(link);
    const host = url.hostname.replace(/^www\./, "");
    const pathParts = url.pathname.split("/").filter(Boolean);
    const path = pathParts.length ? `/${pathParts.slice(0, 2).join("/")}` : "Open secure link";
    const suffix = url.search ? "..." : "";
    return {
      host,
      path: `${path}${suffix}`,
    };
  } catch {
    return {
      host: "Action link",
      path: "Open secure link",
    };
  }
}

function titleizeBrand(value) {
  const clean = String(value || "").trim();
  const known = {
    chatgpt: "ChatGPT",
    github: "GitHub",
    google: "Google",
    mandrillapp: "Mail relay",
    openai: "OpenAI",
    sendgrid: "Mail relay",
  };
  if (known[clean.toLowerCase()]) {
    return known[clean.toLowerCase()];
  }
  return clean.replace(/(^|[-_.\s])([a-z])/g, (_, separator, letter) => `${separator}${letter.toUpperCase()}`);
}

function parseEmailDomain(value) {
  const match = String(value || "").match(/[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})/i);
  return match ? match[1].toLowerCase() : "";
}

function describeSender(message, analysis) {
  const brand = analysis.sender_brand || message.sender_brand || "";
  const fromAddress = message.from_address || "";
  const domain = parseEmailDomain(fromAddress);
  if (brand) {
    return {
      name: titleizeBrand(brand),
      detail: domain ? `via ${domain}` : fromAddress,
    };
  }
  return {
    name: domain || fromAddress || "Unknown sender",
    detail: domain && fromAddress ? fromAddress : "",
  };
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

function renderSourceViewer(message) {
  const tabs = getSourceTabs(message);
  const activeTab = resolveSourceTab(message);
  state.selectedSourceTab = activeTab;

  const tabButtons = tabs
    .map(
      (tab) => `
        <button
          class="source-tab${tab === activeTab ? " is-active" : ""}"
          type="button"
          role="tab"
          aria-selected="${tab === activeTab ? "true" : "false"}"
          data-source-tab="${tab}"
        >
          ${sourceTabLabel(tab)}
        </button>
      `,
    )
    .join("");

  let panelHtml = '<div class="detail-empty">Original content is missing for this message.</div>';
  if (activeTab === "html" && String(message.body_html || "").trim()) {
    panelHtml = `
      <div class="source-preview">
        <div class="source-preview-frame">
          <iframe class="source-frame" title="HTML email preview" sandbox data-html-preview></iframe>
        </div>
        <pre class="detail-pre detail-pre--html">${escapeHtml(message.body_html)}</pre>
      </div>
    `;
  } else if (activeTab === "raw" && String(message.raw_payload_json || "").trim()) {
    panelHtml = `<pre class="detail-pre detail-pre--raw">${escapeHtml(formatRawPayload(message.raw_payload_json))}</pre>`;
  } else if (String(message.body_text || "").trim()) {
    panelHtml = `<pre class="detail-pre">${escapeHtml(message.body_text)}</pre>`;
  }

  return `
    <div class="detail-box detail-box--source">
      <div class="detail-source-header">
        <small>Original message</small>
        <div class="source-tabs" role="tablist" aria-label="Original message tabs">
          ${tabButtons}
        </div>
      </div>
      ${panelHtml}
    </div>
  `;
}

function mountHtmlPreview(root, message) {
  const frame = root.querySelector("[data-html-preview]");
  if (!frame) {
    return;
  }

  const html = String(message?.body_html || "").trim();
  if (!html) {
    frame.srcdoc = "<body></body>";
    return;
  }

  frame.srcdoc = `
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <style>
          :root { color-scheme: light; }
          body {
            margin: 0;
            padding: 16px;
            color: #192331;
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

async function writeClipboard(value) {
  const text = String(value ?? "");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  document.body.append(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function getAvailableDomains() {
  const domains = Array.isArray(state.config?.mail_domains) ? state.config.mail_domains : [];
  if (domains.length) {
    return domains;
  }
  return state.config?.mail_domain ? [state.config.mail_domain] : [];
}

function renderDomainOptions() {
  const domains = getAvailableDomains();
  el.domainSelect.innerHTML = domains
    .map((domain) => `<option value="${escapeHtml(domain)}">@${escapeHtml(domain)}</option>`)
    .join("");

  if (!domains.length) {
    el.domainSelect.innerHTML = '<option value="">@domain</option>';
    el.domainSelect.disabled = true;
    return;
  }

  el.domainSelect.disabled = domains.length <= 1;
  el.domainSelect.value = domains.includes(state.config?.mail_domain) ? state.config.mail_domain : domains[0];
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (state.sessionToken) {
    headers.set("X-Session-Token", state.sessionToken);
  }

  const fetchOptions = {
    credentials: "same-origin",
    ...options,
    headers,
  };
  if (!("cache" in fetchOptions) && path === "/client-config") {
    fetchOptions.cache = "no-store";
  }

  const response = await fetch(path, fetchOptions);

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

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function renderTurnstile() {
  if (!state.config?.turnstile_enabled) {
    hideTurnstile();
    return;
  }

  el.turnstileSlot.classList.remove("is-dev", "is-hidden");

  if (!state.config.turnstile_site_key) {
    el.turnstileSlot.innerHTML = "<span>Turnstile site key is not configured.</span>";
    return;
  }

  if (!window.turnstile) {
    loadTurnstileApi();
    setTimeout(renderTurnstile, 250);
    return;
  }

  el.turnstileSlot.innerHTML = "";
  state.turnstileWidgetId = window.turnstile.render(el.turnstileSlot, {
    sitekey: state.config.turnstile_site_key,
    callback(token) {
      state.turnstileToken = token;
    },
    "expired-callback"() {
      state.turnstileToken = "";
    },
    "error-callback"() {
      state.turnstileToken = "";
      setStatus("Turnstile had a wobble. Try the check again.", "error");
    },
  });
}

function loadTurnstileApi() {
  if (document.querySelector('script[data-turnstile-api="true"]')) {
    return;
  }
  const script = document.createElement("script");
  script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  script.async = true;
  script.defer = true;
  script.dataset.turnstileApi = "true";
  document.head.appendChild(script);
}

function hideTurnstile() {
  state.turnstileToken = "";
  el.turnstileSlot.classList.add("is-hidden");
}

function resetTurnstile() {
  state.turnstileToken = "";
  if (!state.config?.turnstile_enabled) {
    hideTurnstile();
    return;
  }
  if (window.turnstile && state.turnstileWidgetId !== null) {
    window.turnstile.reset(state.turnstileWidgetId);
  }
}

function renderMailboxes() {
  if (!state.mailboxes.length) {
    el.mailboxStrip.className = "mailbox-strip empty";
    el.mailboxStrip.innerHTML = "<span>No mailbox yet</span>";
    return;
  }

  el.mailboxStrip.className = "mailbox-strip";
  el.mailboxStrip.innerHTML = state.mailboxes
    .map(
      (mailbox) => `
        <button class="mailbox-pill" type="button" data-copy="${escapeHtml(mailbox.address)}" aria-label="Copy email ${escapeHtml(mailbox.address)}">
          <span>${escapeHtml(mailbox.address)}</span>
          <span class="copy-pill-action" aria-hidden="true">Copy</span>
        </button>
      `,
    )
    .join("");
}

function renderMessages({ updateStatus = true } = {}) {
  if (!state.messages.length) {
    state.selectedMessageId = null;
    state.selectedMessage = null;
    el.analyze.disabled = true;
    el.messageList.innerHTML = "";
    el.messageDetail.className = "message-detail empty";
    el.messageDetail.innerHTML = `
      <span class="empty-mark">No message selected</span>
      <p>Select a message to see the clean code, sender, summary, and the original email content.</p>
    `;
    if (updateStatus) {
      setStatus(state.sessionToken ? "No mail yet. Send a code to the address above." : "Create a mailbox to begin.");
    }
    return;
  }

  if (updateStatus) {
    setStatus(`${state.messages.length} archived message${state.messages.length === 1 ? "" : "s"} in this session.`);
  }
  el.messageList.innerHTML = state.messages
    .map((message) => {
      const selected = message.id === state.selectedMessageId ? " is-selected" : "";
      const unread = message.is_unread ? '<span class="unread-dot" aria-label="Unread"></span>' : "";
      const otp = message.otp_code
        ? `<button class="code-pill" type="button" data-copy-code="${escapeHtml(message.otp_code)}" aria-label="Copy code ${escapeHtml(message.otp_code)}">${escapeHtml(message.otp_code)}</button>`
        : "";
      const sender = message.sender_brand || message.from_address || "unknown sender";
      return `
        <article class="message-card${selected}" role="button" tabindex="0" data-message-id="${message.id}">
          <header>
            <div>
              <strong>${escapeHtml(message.subject || "No subject")}</strong>
              <small>${escapeHtml(sender)} / ${formatDate(message.received_at)}</small>
            </div>
            ${unread}
          </header>
          <div class="message-meta">
            ${otp}
            <span>${escapeHtml(message.ai_status || "pending")}</span>
            <button class="meta-pill" type="button" data-copy="${escapeHtml(message.mailbox_address)}" aria-label="Copy email ${escapeHtml(message.mailbox_address)}">${escapeHtml(message.mailbox_address)}</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderDetail(message) {
  state.selectedMessage = message;
  const analysis = message.analysis || {};
  const code = analysis.otp_code || message.otp_code || "";
  const links = uniqueLinks(analysis.action_links || []).slice(0, 4);
  const linkHtml = links.length
    ? `<div class="action-list">${links
        .map((link) => {
          const meta = describeLink(link);
          return `
            <a class="action-link" href="${escapeHtml(link)}" target="_blank" rel="noreferrer">
              <span>
                <strong>${escapeHtml(meta.host)}</strong>
                <small>${escapeHtml(meta.path)}</small>
              </span>
              <em>Open</em>
            </a>
          `;
        })
        .join("")}</div>`
    : '<div class="detail-empty">No clean action links found.</div>';
  const actionRequired = analysis.action_required || (code ? "Use the verification code" : "Review the message");
  const sender = describeSender(message, analysis);

  el.analyze.disabled = false;
  el.messageDetail.className = "message-detail";
  el.messageDetail.innerHTML = `
    <div class="detail-heading">
      <small>Subject</small>
      <h3>${escapeHtml(message.subject || "No subject")}</h3>
    </div>
    <div class="detail-callout">
      <span>${escapeHtml(actionRequired)}</span>
    </div>
    <div class="detail-grid">
      <div class="detail-box detail-box--code${code ? " is-copyable" : ""}" ${code ? `role="button" tabindex="0" data-copy-code="${escapeHtml(code)}" aria-label="Copy code ${escapeHtml(code)}"` : ""}>
        <small>Code</small>
        <div class="code-detail-row">
          <strong>${escapeHtml(code || "none")}</strong>
          ${code ? '<span class="mini-copy" aria-hidden="true">Copy</span>' : ""}
        </div>
      </div>
      <div class="detail-box">
        <small>Analyzer</small>
        <strong>${escapeHtml(analysis.provider || "pending")} / ${escapeHtml(analysis.status || "unknown")}</strong>
      </div>
      <div class="detail-box detail-box--wide">
        <small>From</small>
        <strong>${escapeHtml(sender.name)}</strong>
        ${sender.detail ? `<span class="detail-secondary">${escapeHtml(sender.detail)}</span>` : ""}
      </div>
      <div class="detail-box detail-box--wide">
        <small>Received</small>
        <strong>${formatDate(message.received_at)}</strong>
      </div>
    </div>
    <div class="detail-box detail-box--summary">
      <small>Summary</small>
      <p>${escapeHtml(analysis.summary || message.ai_summary || "No summary yet.")}</p>
    </div>
    <div class="detail-box detail-box--links">
      <small>Action links</small>
      ${linkHtml}
    </div>
    ${renderSourceViewer(message)}
  `;
  mountHtmlPreview(el.messageDetail, message);
}

function renderSharedCodes() {
  if (!el.sharedCodesSection || !el.sharedCodesList) {
    return;
  }
  if (!state.config?.shared_inbox_enabled) {
    el.sharedCodesSection.classList.add("is-hidden");
    return;
  }
  el.sharedCodesSection.classList.remove("is-hidden");
  if (el.sharedCodesTitle && state.config?.shared_inbox_address) {
    el.sharedCodesTitle.textContent = `Recent codes / ${state.config.shared_inbox_address}`;
  }

  if (!state.sharedCodes.length) {
    el.sharedCodesList.innerHTML = '<span class="shared-codes-empty">No codes captured yet. Send something to the shared inbox.</span>';
    return;
  }

  el.sharedCodesList.innerHTML = state.sharedCodes
    .map((message) => {
      const code = String(message.otp_code || "").trim();
      const sender = message.sender_brand || message.from_address || "unknown sender";
      return `
        <article class="shared-code-card" tabindex="0" data-shared-code-id="${message.id}" data-copy-code="${escapeHtml(code)}" aria-label="Copy code ${escapeHtml(code)}">
          <div class="shared-code-row">
            <strong>${escapeHtml(code || "?")}</strong>
            <span class="shared-code-pill">${escapeHtml(formatDate(message.received_at))}</span>
          </div>
          <small>${escapeHtml(sender)}</small>
          <div class="shared-code-meta">
            <span class="shared-code-pill">${escapeHtml(message.mailbox_address || "shared")}</span>
            ${message.subject ? `<small>${escapeHtml(message.subject)}</small>` : ""}
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadSharedCodes() {
  if (!state.config?.shared_inbox_enabled) {
    return;
  }
  try {
    const codes = await api("/public/codes?limit=12");
    state.sharedCodes = Array.isArray(codes) ? codes : [];
    renderSharedCodes();
  } catch {
    if (el.sharedCodesList) {
      el.sharedCodesList.innerHTML = '<span class="shared-codes-empty">Shared codes feed is offline right now.</span>';
    }
  }
}

async function loadMailboxes() {
  if (!state.sessionToken) {
    renderMailboxes();
    return;
  }
  state.mailboxes = await api("/mailboxes");
  renderMailboxes();
}

async function loadInbox(options = {}) {
  if (!state.sessionToken) {
    renderMessages(options);
    return;
  }
  state.messages = await api("/inbox");
  renderMessages(options);
}

async function selectMessage(messageId) {
  state.selectedMessageId = messageId;
  renderMessages();
  setStatus("Opening message...");
  const message = await api(`/messages/${messageId}`);
  renderDetail(message);
  await loadInbox();
}

async function refreshSelectedMessageDetail() {
  if (!state.selectedMessageId) {
    return;
  }
  const message = await api(`/messages/${state.selectedMessageId}`);
  renderDetail(message);
}

async function analyzeSelectedMessage() {
  if (!state.selectedMessageId) {
    return;
  }
  el.analyze.disabled = true;
  setStatus("Running analyzer...");
  try {
    const payload = await api(`/messages/${state.selectedMessageId}/analyze`, { method: "POST" });
    setStatus(`Analyzer finished: ${payload.analysis.provider || "deterministic"}.`, "success");
    const detail = await api(`/messages/${state.selectedMessageId}`);
    renderDetail(detail);
    await loadInbox({ updateStatus: false });
  } finally {
    el.analyze.disabled = false;
  }
}

async function createMailbox(event) {
  event.preventDefault();

  if (state.config?.turnstile_enabled && !state.turnstileToken) {
    setStatus("Complete the Turnstile check first.", "error");
    return;
  }

  const localPart = el.localPart.value.trim();
  const requestedDomain = el.domainSelect.value.trim();
  const description = el.description.value.trim();
  const expiresInMinutes = Number(el.ttl.value);
  const body = {
    expires_in_minutes: expiresInMinutes,
    local_part_length: 10,
  };

  if (localPart) {
    body.requested_local_part = localPart;
  }
  if (description) {
    body.description = description;
  }
  if (requestedDomain) {
    body.requested_domain = requestedDomain;
  }
  if (state.turnstileToken) {
    body.turnstile_token = state.turnstileToken;
  }

  setStatus("Creating mailbox...");
  try {
    const payload = await api("/mailboxes", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.sessionToken = payload.session_token;
    localStorage.setItem("tempmail.sessionToken", payload.session_token);
    el.localPart.value = "";
    el.description.value = "";
    setStatus(`Ready: ${payload.mailbox.address}`, "success");
    await loadMailboxes();
    await loadInbox();
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    resetTurnstile();
  }
}

async function copyAddress(address) {
  await writeClipboard(address);
  setStatus(`Copied ${address}`, "success");
}

async function copyCode(code) {
  await writeClipboard(code);
  setStatus(`Copied code ${code}`, "success");
}

async function boot() {
  importSharedSessionFromUrl();
  state.config = await api("/client-config");
  renderDomainOptions();
  if (state.config.mailbox_default_ttl_minutes) {
    el.ttl.value = String(state.config.mailbox_default_ttl_minutes);
  }
  renderTurnstile();
  renderSharedCodes();
  loadSharedCodes().catch(() => undefined);

  if (state.sessionToken) {
    try {
      await loadMailboxes();
      await loadInbox();
      if (state.selectedMessageId && state.messages.some((message) => Number(message.id) === Number(state.selectedMessageId))) {
        await selectMessage(state.selectedMessageId);
      }
    } catch {
      localStorage.removeItem("tempmail.sessionToken");
      state.sessionToken = "";
      renderMailboxes();
      renderMessages();
      setStatus("Previous session expired. Create a fresh mailbox.");
    }
  } else {
    renderMailboxes();
    renderMessages();
  }
}

el.form.addEventListener("submit", createMailbox);
el.refresh.addEventListener("click", async () => {
  try {
    setStatus("Refreshing inbox...");
    await loadInbox();
  } catch (error) {
    setStatus(error.message, "error");
  }
});
el.analyze.addEventListener("click", () => {
  analyzeSelectedMessage().catch((error) => setStatus(error.message, "error"));
});
el.messageList.addEventListener("click", (event) => {
  const copyButton = event.target.closest("[data-copy-code]");
  if (copyButton) {
    event.stopPropagation();
    copyCode(copyButton.dataset.copyCode).catch((error) => setStatus(error.message, "error"));
    return;
  }

  const addressButton = event.target.closest("[data-copy]");
  if (addressButton) {
    event.stopPropagation();
    copyAddress(addressButton.dataset.copy).catch((error) => setStatus(error.message, "error"));
    return;
  }

  const card = event.target.closest("[data-message-id]");
  if (!card) {
    return;
  }
  selectMessage(Number(card.dataset.messageId)).catch((error) => setStatus(error.message, "error"));
});
el.messageList.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const card = event.target.closest("[data-message-id]");
  if (!card || event.target.closest("[data-copy-code]")) {
    return;
  }
  event.preventDefault();
  selectMessage(Number(card.dataset.messageId)).catch((error) => setStatus(error.message, "error"));
});
el.messageDetail.addEventListener("click", (event) => {
  const sourceTab = event.target.closest("[data-source-tab]");
  if (sourceTab && state.selectedMessage) {
    state.selectedSourceTab = sourceTab.dataset.sourceTab || "text";
    renderDetail(state.selectedMessage);
    return;
  }

  const copyButton = event.target.closest("[data-copy-code]");
  if (!copyButton) {
    return;
  }
  copyCode(copyButton.dataset.copyCode).catch((error) => setStatus(error.message, "error"));
});
el.messageDetail.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const copyTarget = event.target.closest("[data-copy-code]");
  if (!copyTarget) {
    return;
  }
  event.preventDefault();
  copyCode(copyTarget.dataset.copyCode).catch((error) => setStatus(error.message, "error"));
});
el.mailboxStrip.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) {
    return;
  }
  copyAddress(button.dataset.copy).catch((error) => setStatus(error.message, "error"));
});

if (el.sharedCodesRefresh) {
  el.sharedCodesRefresh.addEventListener("click", () => {
    loadSharedCodes().catch(() => undefined);
  });
}

if (el.sharedCodesList) {
  el.sharedCodesList.addEventListener("click", (event) => {
    const card = event.target.closest("[data-copy-code]");
    if (!card) {
      return;
    }
    const code = card.dataset.copyCode || "";
    if (!code) {
      return;
    }
    copyCode(code).catch((error) => setStatus(error.message, "error"));
  });
  el.sharedCodesList.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    const card = event.target.closest("[data-copy-code]");
    if (!card) {
      return;
    }
    event.preventDefault();
    const code = card.dataset.copyCode || "";
    if (!code) {
      return;
    }
    copyCode(code).catch((error) => setStatus(error.message, "error"));
  });
}

setInterval(() => {
  if (state.sessionToken) {
    loadInbox({ updateStatus: false })
      .then(() => refreshSelectedMessageDetail())
      .catch(() => undefined);
  }
  if (state.config?.shared_inbox_enabled) {
    loadSharedCodes().catch(() => undefined);
  }
}, 12_000);

boot().catch((error) => setStatus(error.message, "error"));
