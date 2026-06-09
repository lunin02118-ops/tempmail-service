const widgetParams = new URLSearchParams(window.location.search);
const isNativeShell = widgetParams.get("native") === "1" || navigator.userAgent.includes("SamGPTDesktopWidget");
const showAllMail = widgetParams.get("all") !== "0";
const widgetHashParams = new URLSearchParams(window.location.hash.startsWith("#") ? window.location.hash.slice(1) : "");
const widgetSessionToken = widgetHashParams.get("session_token") || widgetParams.get("session_token") || "";

if (widgetSessionToken) {
  localStorage.setItem("tempmail.sessionToken", widgetSessionToken);
  history.replaceState(null, "", window.location.pathname + (isNativeShell ? "?native=1" : ""));
}

if (isNativeShell) {
  document.documentElement.classList.add("is-native-shell");
  document.body.classList.add("is-native-shell");
}

const widgetState = {
  config: null,
  sessionToken: widgetSessionToken || localStorage.getItem("tempmail.sessionToken") || "",
  selectedDomain: "",
  mailboxes: [],
  latestNotification: null,
  lastSeenMessageId: Number(localStorage.getItem("tempmail.widget.lastSeenMessageId") || "0"),
  pollTimer: null,
};
const EDU_MAIL_SUBDOMAIN_PREFIX = "edu";
const LEGACY_INBOX_DOMAIN_RE = /^inbox\d{3}\./;

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
  addressCard: document.querySelector("#address-card"),
  latestCodeCard: document.querySelector("#latest-code-card"),
  latestCodeValue: document.querySelector("#latest-code-value"),
  latestCodeMeta: document.querySelector("#latest-code-meta"),
  status: document.querySelector("#status"),
  nativeMinimize: document.querySelector("#native-minimize"),
  nativeClose: document.querySelector("#native-close"),
};

function setWidgetStatus(message, tone = "neutral") {
  widgetEl.status.textContent = message;
  widgetEl.status.dataset.tone = tone;
}

function syncNativeControls() {
  const ready = Boolean(window.pywebview?.api);
  document.documentElement.classList.toggle("native-api-ready", ready);

  for (const button of [widgetEl.nativeMinimize, widgetEl.nativeClose]) {
    if (!button) {
      continue;
    }
    button.disabled = isNativeShell ? !ready : true;
  }
}

async function invokeNativeShell(method, ...args) {
  syncNativeControls();

  const api = window.pywebview?.api;
  if (!isNativeShell || !api || typeof api[method] !== "function") {
    throw new Error("Native desktop controls are not ready yet.");
  }

  return api[method](...args);
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

function normalizeDomainList(values) {
  const seen = new Set();
  return values
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean)
    .filter((domain) => {
      if (seen.has(domain)) {
        return false;
      }
      seen.add(domain);
      return true;
    });
}

function isBaseMailDomain(domain) {
  return domain.split(".").filter(Boolean).length === 2;
}

function resolveSelectableMailDomains(rawDomains) {
  const domains = normalizeDomainList(rawDomains);
  const baseDomains = domains.filter(isBaseMailDomain);
  if (baseDomains.length) {
    return baseDomains.map((domain) => `${EDU_MAIL_SUBDOMAIN_PREFIX}.${domain}`);
  }

  const eduDomains = domains.filter((domain) => domain.startsWith(`${EDU_MAIL_SUBDOMAIN_PREFIX}.`));
  if (eduDomains.length) {
    return eduDomains;
  }

  return domains.filter((domain) => !LEGACY_INBOX_DOMAIN_RE.test(domain));
}

function getAvailableDomains() {
  const domains = Array.isArray(widgetState.config?.mail_domains) ? widgetState.config.mail_domains : [];
  if (domains.length) {
    return resolveSelectableMailDomains(domains);
  }
  return widgetState.config?.mail_domain ? resolveSelectableMailDomains([widgetState.config.mail_domain]) : [];
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
      const isDefault = index === 0;
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

function latestMailbox() {
  return widgetState.mailboxes[0] || null;
}

function renderAddress() {
  const mailbox = latestMailbox();
  if (!mailbox) {
    widgetEl.addressCard.className = "address-card is-empty";
    widgetEl.addressCard.disabled = showAllMail ? false : true;
    widgetEl.addressCard.removeAttribute("data-copy-address");
    widgetEl.addressCard.innerHTML = `
      <small>${showAllMail ? "All mailboxes" : "Generated mail"}</small>
      <strong>No address yet</strong>
      <span>${showAllMail ? "Waiting for any mailbox" : "Choose domain and generate"}</span>
    `;
    return;
  }

  widgetEl.addressCard.className = "address-card";
  widgetEl.addressCard.disabled = false;
  widgetEl.addressCard.dataset.copyAddress = mailbox.address;
  widgetEl.addressCard.innerHTML = `
    <small>${showAllMail ? `${widgetState.mailboxes.length} active mailboxes` : "Generated mail"}</small>
    <strong>${escapeHtml(mailbox.address)}</strong>
    <span>${showAllMail ? "Latest active mailbox · click to copy" : "Click to copy"}</span>
  `;
}

function renderLatestCode() {
  const latestCode = widgetState.latestNotification;
  if (!latestCode?.otp_code) {
    widgetEl.latestCodeCard.className = "signal-card is-empty";
    widgetEl.latestCodeCard.disabled = true;
    widgetEl.latestCodeCard.removeAttribute("data-copy-latest-code");
    widgetEl.latestCodeValue.textContent = "Waiting";
    widgetEl.latestCodeMeta.textContent = widgetState.sessionToken ? "No OTP yet" : "Generate mail first";
    return;
  }

  widgetEl.latestCodeCard.className = "signal-card";
  widgetEl.latestCodeCard.disabled = false;
  widgetEl.latestCodeCard.dataset.copyLatestCode = latestCode.otp_code;
  widgetEl.latestCodeValue.textContent = latestCode.otp_code;
  widgetEl.latestCodeMeta.textContent = senderLabel(latestCode);
}

function rememberSeenMessages() {
  const latestId = Math.max(widgetState.lastSeenMessageId, Number(widgetState.latestNotification?.message_id) || 0);
  widgetState.lastSeenMessageId = latestId;
  localStorage.setItem("tempmail.widget.lastSeenMessageId", String(latestId));
}

async function loadMailboxes() {
  if (showAllMail) {
    widgetState.mailboxes = await api("/widget/mailboxes");
    renderAddress();
    return;
  }
  if (!widgetState.sessionToken) {
    widgetState.mailboxes = [];
    renderAddress();
    return;
  }
  widgetState.mailboxes = await api("/mailboxes");
  renderAddress();
}

async function loadLatestCode({ quiet = false } = {}) {
  if (showAllMail) {
    const previousSeen = widgetState.lastSeenMessageId;
    widgetState.latestNotification = await api("/widget/notifications/latest");
    renderLatestCode();
    const newestCode =
      widgetState.latestNotification?.otp_code && Number(widgetState.latestNotification.message_id) > previousSeen
        ? widgetState.latestNotification
        : null;
    if (newestCode) {
      document.title = `${newestCode.otp_code} · DeskMail Widget`;
      setWidgetStatus(`New code: ${newestCode.otp_code}`, "success");
      await loadMailboxes();
    } else if (!quiet) {
      setWidgetStatus(widgetState.latestNotification ? "Synced all mail." : "Waiting for any code.");
    }
    rememberSeenMessages();
    return;
  }

  if (!widgetState.sessionToken) {
    widgetState.latestNotification = null;
    renderLatestCode();
    return;
  }

  const previousSeen = widgetState.lastSeenMessageId;
  widgetState.latestNotification = await api("/notifications/latest");
  renderLatestCode();
  const newestCode =
    widgetState.latestNotification?.otp_code && Number(widgetState.latestNotification.message_id) > previousSeen
      ? widgetState.latestNotification
      : null;
  if (newestCode) {
    document.title = `${newestCode.otp_code} · DeskMail Widget`;
    setWidgetStatus(`New code: ${newestCode.otp_code}`, "success");
  } else if (!quiet) {
    setWidgetStatus(widgetState.latestNotification ? "Synced." : "Waiting for code.");
  }
  rememberSeenMessages();
}

async function createMailbox(event) {
  event.preventDefault();

  const body = {
    expires_in_minutes: widgetState.config?.mailbox_default_ttl_minutes || 60,
    local_part_length: 10,
  };
  const requestedDomain = widgetState.selectedDomain.trim();
  if (requestedDomain) {
    body.requested_domain = requestedDomain;
  }

  widgetEl.generate.disabled = true;
  setWidgetStatus("Generating...");
  try {
    const payload = await api("/mailboxes", {
      method: "POST",
      body: JSON.stringify(body),
    });
    widgetState.sessionToken = payload.session_token;
    localStorage.setItem("tempmail.sessionToken", payload.session_token);
    setWidgetStatus("Generated.", "success");
    await loadMailboxes();
    await loadLatestCode({ quiet: true });
  } catch (error) {
    setWidgetStatus(error.message, "error");
  } finally {
    widgetEl.generate.disabled = false;
  }
}

async function copyAddress(address) {
  await writeClipboard(address);
  setWidgetStatus("Copied mail.", "success");
}

async function copyCode(code) {
  await writeClipboard(code);
  setWidgetStatus("Copied code.", "success");
}

function startPolling() {
  if (widgetState.pollTimer) {
    clearInterval(widgetState.pollTimer);
  }
  widgetState.pollTimer = setInterval(() => {
    loadLatestCode({ quiet: true }).catch(() => setWidgetStatus("Offline.", "error"));
  }, 12_000);
}

async function bootWidget() {
  widgetState.config = await api("/client-config");
  renderDomainOptions();
  await loadMailboxes();
  await loadLatestCode({ quiet: true });
  setWidgetStatus(showAllMail ? "Listening to all mailboxes." : widgetState.sessionToken ? "Listening." : "Ready.");
  startPolling();
}

if (isNativeShell) {
  syncNativeControls();
  window.addEventListener("pywebviewready", syncNativeControls);
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
widgetEl.addressCard.addEventListener("click", () => {
  const address = widgetEl.addressCard.dataset.copyAddress;
  if (address) {
    copyAddress(address).catch((error) => setWidgetStatus(error.message, "error"));
  }
});
widgetEl.latestCodeCard.addEventListener("click", () => {
  const code = widgetEl.latestCodeCard.dataset.copyLatestCode;
  if (code) {
    copyCode(code).catch((error) => setWidgetStatus(error.message, "error"));
  }
});
widgetEl.nativeMinimize?.addEventListener("click", () => {
  invokeNativeShell("minimize_to_tray").catch((error) => setWidgetStatus(error.message, "error"));
});
widgetEl.nativeClose?.addEventListener("click", () => {
  invokeNativeShell("close_window").catch((error) => setWidgetStatus(error.message, "error"));
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
