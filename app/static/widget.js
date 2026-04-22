const widgetParams = new URLSearchParams(window.location.search);
const isNativeShell = widgetParams.get("native") === "1" || navigator.userAgent.includes("SamGPTDesktopWidget");

if (isNativeShell) {
  document.documentElement.classList.add("is-native-shell");
  document.body.classList.add("is-native-shell");
}

const widgetState = {
  config: null,
  sessionToken: localStorage.getItem("tempmail.sessionToken") || "",
  turnstileToken: "",
  turnstileWidgetId: null,
  selectedDomain: "",
  mailboxes: [],
  messages: [],
  lastSeenMessageId: Number(localStorage.getItem("tempmail.widget.lastSeenMessageId") || "0"),
  pollTimer: null,
};

const widgetEl = {
  form: document.querySelector("#widget-form"),
  domainPicker: document.querySelector("#domain-picker"),
  domainValue: document.querySelector("#domain-value"),
  domainTrigger: document.querySelector("#domain-trigger"),
  domainCurrent: document.querySelector("#domain-current"),
  domainPanel: document.querySelector("#domain-panel"),
  domainCount: document.querySelector("#domain-count"),
  domainOptionList: document.querySelector("#domain-option-list"),
  generate: document.querySelector("#generate"),
  turnstileSlot: document.querySelector("#turnstile-slot"),
  addressCard: document.querySelector("#address-card"),
  status: document.querySelector("#status"),
  refresh: document.querySelector("#refresh"),
  codeList: document.querySelector("#code-list"),
  pollIndicator: document.querySelector("#poll-indicator"),
};

function setWidgetStatus(message, tone = "neutral") {
  widgetEl.status.textContent = message;
  widgetEl.status.dataset.tone = tone;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTime(value) {
  if (!value) {
    return "unknown time";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function senderLabel(message) {
  return message.sender_brand || message.from_address || "unknown sender";
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
  const domains = Array.isArray(widgetState.config?.mail_domains) ? widgetState.config.mail_domains : [];
  if (domains.length) {
    return domains;
  }
  return widgetState.config?.mail_domain ? [widgetState.config.mail_domain] : [];
}

function closeDomainPicker() {
  widgetEl.domainPicker.dataset.open = "false";
  widgetEl.domainPanel.classList.add("is-hidden");
  widgetEl.domainTrigger.setAttribute("aria-expanded", "false");
}

function openDomainPicker() {
  if (widgetEl.domainTrigger.disabled) {
    return;
  }
  widgetEl.domainPicker.dataset.open = "true";
  widgetEl.domainPanel.classList.remove("is-hidden");
  widgetEl.domainTrigger.setAttribute("aria-expanded", "true");
}

function setSelectedDomain(domain) {
  widgetState.selectedDomain = domain;
  widgetEl.domainValue.value = domain;
  widgetEl.domainCurrent.textContent = domain ? `@${domain}` : "@domain";

  for (const option of widgetEl.domainOptionList.querySelectorAll("[data-domain-value]")) {
    const isActive = option.dataset.domainValue === domain;
    option.classList.toggle("is-active", isActive);
    option.setAttribute("aria-selected", String(isActive));
  }
}

function renderDomainOptions() {
  const domains = getAvailableDomains();
  widgetEl.domainCount.textContent = `${domains.length} domain${domains.length === 1 ? "" : "s"}`;
  widgetEl.domainOptionList.innerHTML = domains
    .map((domain, index) => {
      const isDefault = domain === widgetState.config?.mail_domain || (!widgetState.config?.mail_domain && index === 0);
      return `
        <button
          class="domain-option"
          type="button"
          role="option"
          aria-selected="false"
          data-domain-value="${escapeHtml(domain)}"
        >
          <span class="domain-option-label">@${escapeHtml(domain)}</span>
          ${isDefault ? '<small class="domain-option-badge">default</small>' : ""}
        </button>
      `;
    })
    .join("");

  if (!domains.length) {
    widgetEl.domainCurrent.textContent = "@domain";
    widgetEl.domainValue.value = "";
    widgetEl.domainTrigger.disabled = true;
    widgetEl.generate.disabled = true;
    closeDomainPicker();
    return;
  }

  widgetEl.domainTrigger.disabled = domains.length <= 1;
  const preferredDomain = domains.includes(widgetState.selectedDomain)
    ? widgetState.selectedDomain
    : domains.includes(widgetState.config?.mail_domain)
      ? widgetState.config.mail_domain
      : domains[0];
  setSelectedDomain(preferredDomain);
  closeDomainPicker();
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (widgetState.sessionToken) {
    headers.set("X-Session-Token", widgetState.sessionToken);
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
  if (!widgetState.config?.turnstile_enabled) {
    widgetEl.turnstileSlot.classList.add("is-hidden");
    return;
  }

  widgetEl.turnstileSlot.classList.remove("is-hidden");
  widgetEl.turnstileSlot.dataset.state = "loading";
  if (!widgetState.config.turnstile_site_key) {
    widgetEl.turnstileSlot.innerHTML = "<span>Turnstile site key is not configured.</span>";
    widgetEl.turnstileSlot.dataset.state = "error";
    return;
  }

  if (!window.turnstile) {
    setTimeout(renderTurnstile, 250);
    return;
  }

  widgetEl.turnstileSlot.innerHTML = "";
  widgetState.turnstileWidgetId = window.turnstile.render(widgetEl.turnstileSlot, {
    sitekey: widgetState.config.turnstile_site_key,
    theme: isNativeShell ? "dark" : "auto",
    size: isNativeShell ? "flexible" : "normal",
    callback(token) {
      widgetState.turnstileToken = token;
      widgetEl.turnstileSlot.dataset.state = "verified";
    },
    "expired-callback"() {
      widgetState.turnstileToken = "";
      widgetEl.turnstileSlot.dataset.state = "expired";
    },
    "error-callback"(errorCode) {
      widgetState.turnstileToken = "";
      widgetEl.turnstileSlot.dataset.state = "error";
      const suffix = errorCode ? ` (${errorCode})` : "";
      setWidgetStatus(`Human gate needs another try${suffix}.`, "error");
    },
    "unsupported-callback"() {
      widgetState.turnstileToken = "";
      widgetEl.turnstileSlot.dataset.state = "unsupported";
      setWidgetStatus("Human gate is blocked by the embedded browser. Relaunch after the widget update.", "error");
    },
  });
}

function resetTurnstile() {
  widgetState.turnstileToken = "";
  widgetEl.turnstileSlot.dataset.state = "idle";
  if (window.turnstile && widgetState.turnstileWidgetId !== null) {
    window.turnstile.reset(widgetState.turnstileWidgetId);
  }
}

function latestMailbox() {
  return widgetState.mailboxes[0] || null;
}

function renderAddress() {
  const mailbox = latestMailbox();
  if (!mailbox) {
    widgetEl.addressCard.className = "address-card is-empty";
    widgetEl.addressCard.disabled = true;
    widgetEl.addressCard.removeAttribute("data-copy-address");
    widgetEl.addressCard.innerHTML = `
      <small>Current address</small>
      <strong>No address yet</strong>
      <span>Generate one to start listening</span>
    `;
    return;
  }

  widgetEl.addressCard.className = "address-card";
  widgetEl.addressCard.disabled = false;
  widgetEl.addressCard.dataset.copyAddress = mailbox.address;
  widgetEl.addressCard.innerHTML = `
    <small>Current address</small>
    <strong>${escapeHtml(mailbox.address)}</strong>
    <span>Click to copy email</span>
  `;
}

function renderCodes() {
  const messagesWithCodes = widgetState.messages.filter((message) => message.otp_code).slice(0, 5);
  if (!messagesWithCodes.length) {
    widgetEl.codeList.className = "code-list empty";
    widgetEl.codeList.innerHTML = "<p>Waiting for verification codes. New OTPs appear automatically.</p>";
    return;
  }

  widgetEl.codeList.className = "code-list";
  widgetEl.codeList.innerHTML = messagesWithCodes
    .map((message) => {
      const isNew = Number(message.id) > widgetState.lastSeenMessageId ? " is-new" : "";
      return `
        <button class="code-card${isNew}" type="button" data-copy-code="${escapeHtml(message.otp_code)}" aria-label="Copy code ${escapeHtml(message.otp_code)}">
          <span class="code-meta">
            <strong>${escapeHtml(message.subject || "Verification code")}</strong>
            <small>${escapeHtml(senderLabel(message))} / ${formatTime(message.received_at)}</small>
          </span>
          <span class="code-value">${escapeHtml(message.otp_code)}</span>
        </button>
      `;
    })
    .join("");
}

function rememberSeenMessages() {
  const latestId = widgetState.messages.reduce((maxId, message) => Math.max(maxId, Number(message.id) || 0), widgetState.lastSeenMessageId);
  widgetState.lastSeenMessageId = latestId;
  localStorage.setItem("tempmail.widget.lastSeenMessageId", String(latestId));
}

async function loadMailboxes() {
  if (!widgetState.sessionToken) {
    widgetState.mailboxes = [];
    renderAddress();
    return;
  }
  widgetState.mailboxes = await api("/mailboxes");
  renderAddress();
}

async function loadInbox({ quiet = false } = {}) {
  if (!widgetState.sessionToken) {
    widgetState.messages = [];
    renderCodes();
    widgetEl.pollIndicator.textContent = "idle";
    return;
  }

  widgetEl.pollIndicator.textContent = "syncing";
  const previousSeen = widgetState.lastSeenMessageId;
  widgetState.messages = await api("/inbox");
  renderCodes();
  const newestCode = widgetState.messages.find((message) => message.otp_code && Number(message.id) > previousSeen);
  if (newestCode) {
    document.title = `${newestCode.otp_code} · SamGPT Desk Widget`;
    setWidgetStatus(`New code: ${newestCode.otp_code}`, "success");
  } else if (!quiet) {
    setWidgetStatus(widgetState.messages.length ? "Inbox synced." : "Listening for incoming mail.");
  }
  rememberSeenMessages();
  widgetEl.pollIndicator.textContent = "live";
}

async function createMailbox(event) {
  event.preventDefault();
  if (widgetState.config?.turnstile_enabled && !widgetState.turnstileToken) {
    setWidgetStatus("Complete the human gate first.", "error");
    return;
  }

  const body = {
    expires_in_minutes: widgetState.config?.mailbox_default_ttl_minutes || 60,
    local_part_length: 10,
  };
  const requestedDomain = widgetState.selectedDomain.trim();
  if (requestedDomain) {
    body.requested_domain = requestedDomain;
  }
  if (widgetState.turnstileToken) {
    body.turnstile_token = widgetState.turnstileToken;
  }

  widgetEl.generate.disabled = true;
  setWidgetStatus("Generating mailbox...");
  try {
    const payload = await api("/mailboxes", {
      method: "POST",
      body: JSON.stringify(body),
    });
    widgetState.sessionToken = payload.session_token;
    localStorage.setItem("tempmail.sessionToken", payload.session_token);
    setWidgetStatus(`Generated ${payload.mailbox.address}`, "success");
    await loadMailboxes();
    await loadInbox({ quiet: true });
  } catch (error) {
    setWidgetStatus(error.message, "error");
  } finally {
    widgetEl.generate.disabled = false;
    resetTurnstile();
  }
}

async function copyAddress(address) {
  await writeClipboard(address);
  setWidgetStatus(`Copied ${address}`, "success");
}

async function copyCode(code) {
  await writeClipboard(code);
  setWidgetStatus(`Copied code ${code}`, "success");
}

function startPolling() {
  if (widgetState.pollTimer) {
    clearInterval(widgetState.pollTimer);
  }
  widgetState.pollTimer = setInterval(() => {
    loadInbox({ quiet: true }).catch(() => {
      widgetEl.pollIndicator.textContent = "offline";
    });
  }, 5_000);
}

async function bootWidget() {
  widgetState.config = await api("/client-config");
  renderDomainOptions();
  renderTurnstile();
  await loadMailboxes();
  await loadInbox({ quiet: true });
  setWidgetStatus(widgetState.sessionToken ? "Live. Waiting for codes." : "Generate a mailbox to start.");
  startPolling();
}

widgetEl.form.addEventListener("submit", createMailbox);
widgetEl.domainTrigger.addEventListener("click", () => {
  if (widgetEl.domainPanel.classList.contains("is-hidden")) {
    openDomainPicker();
  } else {
    closeDomainPicker();
  }
});
widgetEl.domainOptionList.addEventListener("click", (event) => {
  const option = event.target.closest("[data-domain-value]");
  if (!option) {
    return;
  }
  setSelectedDomain(option.dataset.domainValue || "");
  closeDomainPicker();
});
widgetEl.refresh.addEventListener("click", () => {
  loadInbox().catch((error) => setWidgetStatus(error.message, "error"));
});
widgetEl.addressCard.addEventListener("click", () => {
  const address = widgetEl.addressCard.dataset.copyAddress;
  if (address) {
    copyAddress(address).catch((error) => setWidgetStatus(error.message, "error"));
  }
});
widgetEl.codeList.addEventListener("click", (event) => {
  const codeButton = event.target.closest("[data-copy-code]");
  if (!codeButton) {
    return;
  }
  copyCode(codeButton.dataset.copyCode).catch((error) => setWidgetStatus(error.message, "error"));
});
document.addEventListener("click", (event) => {
  if (!widgetEl.domainPicker.contains(event.target)) {
    closeDomainPicker();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeDomainPicker();
  }
});

bootWidget().catch((error) => setWidgetStatus(error.message, "error"));
