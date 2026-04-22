const state = {
  config: null,
  sessionToken: localStorage.getItem("tempmail.sessionToken") || "",
  turnstileToken: "",
  turnstileWidgetId: null,
  mailboxes: [],
  messages: [],
  selectedMessageId: null,
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

  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
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

  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function renderTurnstile() {
  if (!state.config?.turnstile_enabled) {
    el.turnstileSlot.classList.add("is-dev");
    el.turnstileSlot.innerHTML = "<span>Human gate disabled in this environment.</span>";
    return;
  }

  if (!state.config.turnstile_site_key) {
    el.turnstileSlot.innerHTML = "<span>Turnstile site key is not configured.</span>";
    return;
  }

  if (!window.turnstile) {
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

function resetTurnstile() {
  state.turnstileToken = "";
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
        <span class="mailbox-pill">
          <span>${escapeHtml(mailbox.address)}</span>
          <button type="button" data-copy="${escapeHtml(mailbox.address)}">Copy</button>
        </span>
      `,
    )
    .join("");
}

function renderMessages({ updateStatus = true } = {}) {
  if (!state.messages.length) {
    el.messageList.innerHTML = "";
    if (updateStatus) {
      setStatus(state.sessionToken ? "No mail yet. Send a code to the address above." : "Create a mailbox to begin.");
    }
    return;
  }

  if (updateStatus) {
    setStatus(`${state.messages.length} message${state.messages.length === 1 ? "" : "s"} in this session.`);
  }
  el.messageList.innerHTML = state.messages
    .map((message) => {
      const selected = message.id === state.selectedMessageId ? " is-selected" : "";
      const unread = message.is_unread ? '<span class="unread-dot" aria-label="Unread"></span>' : "";
      const otp = message.otp_code ? `<span class="code-pill">OTP ${escapeHtml(message.otp_code)}</span>` : "";
      const sender = message.sender_brand || message.from_address || "unknown sender";
      return `
        <button class="message-card${selected}" type="button" data-message-id="${message.id}">
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
            <span>${escapeHtml(message.mailbox_address)}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderDetail(message) {
  const analysis = message.analysis || {};
  const links = (analysis.action_links || []).map(normalizeLink).filter(Boolean);
  const linkHtml = links.length
    ? `<div class="link-list">${links
        .map((link) => `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(link)}</a>`)
        .join("")}</div>`
    : "<p>No action links found.</p>";

  el.analyze.disabled = false;
  el.messageDetail.className = "message-detail";
  el.messageDetail.innerHTML = `
    <div class="detail-subject">${escapeHtml(message.subject || "No subject")}</div>
    <div class="detail-grid">
      <div class="detail-box">
        <small>OTP</small>
        <strong>${escapeHtml(analysis.otp_code || message.otp_code || "none")}</strong>
      </div>
      <div class="detail-box">
        <small>Analyzer</small>
        <strong>${escapeHtml(analysis.provider || "pending")} / ${escapeHtml(analysis.status || "unknown")}</strong>
      </div>
      <div class="detail-box">
        <small>From</small>
        <strong>${escapeHtml(message.from_address || "unknown")}</strong>
      </div>
      <div class="detail-box">
        <small>Received</small>
        <strong>${formatDate(message.received_at)}</strong>
      </div>
    </div>
    <div class="detail-box">
      <small>Summary</small>
      <strong>${escapeHtml(analysis.summary || message.ai_summary || "No summary yet.")}</strong>
    </div>
    <div class="detail-box">
      <small>Action links</small>
      ${linkHtml}
    </div>
    <pre class="body-preview">${escapeHtml(message.body_text || "No plain-text body captured.")}</pre>
  `;
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
  await navigator.clipboard.writeText(address);
  setStatus(`Copied ${address}`, "success");
}

async function boot() {
  state.config = await api("/client-config");
  renderDomainOptions();
  if (state.config.mailbox_default_ttl_minutes) {
    el.ttl.value = String(state.config.mailbox_default_ttl_minutes);
  }
  renderTurnstile();

  if (state.sessionToken) {
    try {
      await loadMailboxes();
      await loadInbox();
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
  const card = event.target.closest("[data-message-id]");
  if (!card) {
    return;
  }
  selectMessage(Number(card.dataset.messageId)).catch((error) => setStatus(error.message, "error"));
});
el.mailboxStrip.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) {
    return;
  }
  copyAddress(button.dataset.copy).catch((error) => setStatus(error.message, "error"));
});

setInterval(() => {
  if (state.sessionToken) {
    loadInbox({ updateStatus: false })
      .then(() => refreshSelectedMessageDetail())
      .catch(() => undefined);
  }
}, 12_000);

boot().catch((error) => setStatus(error.message, "error"));
