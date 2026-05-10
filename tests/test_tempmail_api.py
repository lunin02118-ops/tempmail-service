import json
import quopri

from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import create_app
from app.repositories.messages import MessageRepository
from app.services.ai_service import MessageAnalysisService
from app.services.session_service import hash_session_token
from app.services.text_encoding import EMAIL_BODY_MAX_CHARS, EMAIL_RAW_PAYLOAD_MAX_CHARS


def setup_tempmail_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PUBLIC_MAIL_DOMAIN", "samgpt.me")
    monkeypatch.delenv("PUBLIC_MAIL_DOMAINS", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("INGEST_WEBHOOK_SECRET", "test-ingest-secret")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_ENABLED", raising=False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    monkeypatch.delenv("ARCHIVE_ADMIN_TOKEN", raising=False)
    for index in range(1, 10):
        monkeypatch.delenv(f"GROQ_API_KEY_{index}", raising=False)


def _as_latin1_mojibake(value: str) -> str:
    return value.encode("utf-8").decode("latin1")


def _as_quoted_printable(value: str) -> str:
    return quopri.encodestring(value.encode("utf-8")).decode("ascii")


def test_create_mailbox_sets_session_and_lists_mailboxes(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/mailboxes", json={"description": "main temp inbox"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["session_token"]
    assert payload["mailbox"]["address"].endswith("@samgpt.me")
    assert payload["mailbox"]["description"] == "main temp inbox"

    list_response = client.get("/mailboxes")

    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["address"] == payload["mailbox"]["address"]


def test_web_app_and_client_config_do_not_expose_private_turnstile_secret(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "public-site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "private-secret-key")
    client = TestClient(create_app())

    index_response = client.get("/")
    widget_response = client.get("/widget")
    archive_response = client.get("/admin/archive")
    config_response = client.get("/client-config")
    script_response = client.get("/static/app.js")
    style_response = client.get("/static/app.css")
    widget_script_response = client.get("/static/widget.js")
    widget_style_response = client.get("/static/widget.css")
    archive_script_response = client.get("/static/archive.js")
    archive_style_response = client.get("/static/archive.css")
    manifest_response = client.get("/manifest.webmanifest")
    worker_response = client.get("/service-worker.js")

    assert index_response.status_code == 200
    assert widget_response.status_code == 200
    assert archive_response.status_code == 200
    assert "SamGPT Temp Mail" in index_response.text
    assert "DeskMail Widget" in widget_response.text
    assert "SamGPT Mail Archive" in archive_response.text
    assert "private-secret-key" not in index_response.text
    assert "private-secret-key" not in widget_response.text
    assert "private-secret-key" not in archive_response.text
    assert script_response.status_code == 200
    assert style_response.status_code == 200
    assert widget_script_response.status_code == 200
    assert widget_style_response.status_code == 200
    assert archive_script_response.status_code == 200
    assert archive_style_response.status_code == 200
    assert manifest_response.status_code == 200
    assert worker_response.status_code == 200
    assert "challenges.cloudflare.com/turnstile" not in index_response.text
    assert "challenges.cloudflare.com/turnstile" not in widget_response.text
    assert "turnstile-slot" not in widget_response.text
    assert "private-secret-key" not in script_response.text
    assert "private-secret-key" not in style_response.text
    assert "private-secret-key" not in widget_script_response.text
    assert "private-secret-key" not in widget_style_response.text
    assert "turnstile" not in widget_script_response.text.lower()
    assert "turnstile" not in widget_style_response.text.lower()
    assert "human gate" not in widget_script_response.text.lower()
    assert "private-secret-key" not in archive_script_response.text
    assert "private-secret-key" not in archive_style_response.text
    assert "X-Archive-Admin-Token" in archive_script_response.text
    assert "All received mail" in archive_response.text
    assert "data-copy-code" in script_response.text
    assert "OTP ${escapeHtml(message.otp_code)}" not in script_response.text
    assert "<small>Code</small>" in script_response.text
    assert "body-preview" not in script_response.text
    assert "No plain-text body captured" not in script_response.text
    assert "action-link" in script_response.text
    assert "Signal brief" in index_response.text
    assert 'class="mailbox-pill" type="button" data-copy=' in script_response.text
    assert 'class="meta-pill" type="button" data-copy=' in script_response.text
    assert 'role="button" tabindex="0" data-copy-code=' in script_response.text
    assert ".meta-pill" in style_response.text
    assert ".detail-box--code.is-copyable" in style_response.text
    assert "/widget" in manifest_response.text
    assert "Desktop widget" in manifest_response.text
    assert "tempmail.sessionToken" in widget_script_response.text
    assert 'api("/mailboxes")' in widget_script_response.text
    assert 'api("/widget/mailboxes")' in widget_script_response.text
    assert 'api("/widget/notifications/latest")' in widget_script_response.text
    assert 'api("/notifications/latest")' in widget_script_response.text
    assert 'api("/inbox")' not in widget_script_response.text
    assert "data-copy-latest-code" in widget_script_response.text
    assert "renderArchive" not in widget_script_response.text
    assert "renderCodes" not in widget_script_response.text
    assert "DeskMail" in widget_response.text
    assert "Last OTP" in widget_response.text
    assert "Latest codes" not in widget_response.text
    assert "Original source" not in widget_response.text
    assert "Archive" not in widget_response.text
    assert 'class="full-link"' not in widget_response.text
    assert ".desk-widget" in widget_style_response.text
    assert ".widget-core" in widget_style_response.text
    assert ".signal-card" in widget_style_response.text
    assert ".code-card" not in widget_style_response.text
    assert ".generator > button" in widget_style_response.text
    assert ".generator button {" not in widget_style_response.text

    assert config_response.status_code == 200
    payload = config_response.json()
    assert payload["mail_domain"] == "samgpt.me"
    assert payload["mail_domains"][0] == "samgpt.me"
    assert "inbox001.samgpt.me" in payload["mail_domains"]
    assert "inbox100.samgpt.me" in payload["mail_domains"]
    assert payload["turnstile_site_key"] is None
    assert payload["turnstile_enabled"] is False
    assert "private-secret-key" not in config_response.text


def test_create_mailbox_does_not_require_turnstile_when_disabled(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "public-site-key")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "private-secret-key")
    monkeypatch.delenv("TURNSTILE_ENABLED", raising=False)
    client = TestClient(create_app())

    response = client.post("/mailboxes", json={"description": "no captcha"})

    assert response.status_code == 201
    assert response.json()["mailbox"]["description"] == "no captcha"


def test_create_mailbox_accepts_generated_requested_domain(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.post("/mailboxes", json={"requested_domain": "inbox001.samgpt.me"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["mailbox"]["domain"] == "inbox001.samgpt.me"
    assert payload["mailbox"]["address"].endswith("@inbox001.samgpt.me")


def test_ingested_message_appears_in_unified_and_mailbox_inbox(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox_payload = client.post("/mailboxes", json={}).json()
    mailbox = mailbox_payload["mailbox"]

    ingest_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "GitHub <noreply@github.com>",
            "subject": "Your login code",
            "provider_message_id": "provider-1",
            "body_text": "Your verification code is 654321. Use it to sign in.",
        },
    )

    assert ingest_response.status_code == 200
    ingest_payload = ingest_response.json()
    assert ingest_payload["mailbox_address"] == mailbox["address"]
    assert ingest_payload["notification"]["otp_code"] == "654321"

    inbox_response = client.get("/inbox")
    mailbox_history_response = client.get(f"/mailboxes/{mailbox['id']}/messages")
    latest_notification_response = client.get("/notifications/latest")

    assert inbox_response.status_code == 200
    assert mailbox_history_response.status_code == 200
    assert latest_notification_response.status_code == 200

    inbox_payload = inbox_response.json()
    mailbox_history_payload = mailbox_history_response.json()
    latest_notification_payload = latest_notification_response.json()
    session_token_hash = hash_session_token(mailbox_payload["session_token"], "test-session-secret")
    summary_rows = MessageRepository(AppSettings.from_env()).list_for_session(session_token_hash)

    assert len(inbox_payload) == 1
    assert len(mailbox_history_payload) == 1
    assert inbox_payload[0]["otp_code"] == "654321"
    assert inbox_payload[0]["mailbox_address"] == mailbox["address"]
    assert inbox_payload[0]["is_unread"] is True
    assert mailbox_history_payload[0]["id"] == inbox_payload[0]["id"]
    assert latest_notification_payload["otp_code"] == "654321"
    assert "body_text" not in summary_rows[0]
    assert "body_html" not in summary_rows[0]
    assert "raw_payload_json" not in summary_rows[0]


def test_latest_notification_returns_latest_otp_without_requiring_full_inbox(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    code_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "Your login code",
            "provider_message_id": "provider-latest-code",
            "body_text": "Use code 654321 to continue.",
        },
    )
    non_code_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "Newsletter <news@example.com>",
            "subject": "Welcome",
            "provider_message_id": "provider-latest-non-code",
            "body_text": "No verification code in this message.",
        },
    )

    latest_notification_response = client.get("/notifications/latest")

    assert code_response.status_code == 200
    assert non_code_response.status_code == 200
    assert latest_notification_response.status_code == 200
    latest_notification = latest_notification_response.json()
    assert latest_notification["message_id"] == code_response.json()["message_id"]
    assert latest_notification["otp_code"] == "654321"


def test_latest_notification_uses_ingest_order_when_received_at_is_older(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    first_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "First login code",
            "provider_message_id": "provider-order-first",
            "received_at": "2026-05-01T20:00:00Z",
            "body_text": "Use code 111111 to continue.",
        },
    )
    second_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "Second login code",
            "provider_message_id": "provider-order-second",
            "received_at": "2026-05-01T19:00:00Z",
            "body_text": "Use code 222222 to continue.",
        },
    )

    latest_notification_response = client.get("/notifications/latest")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert latest_notification_response.status_code == 200
    latest_notification = latest_notification_response.json()
    assert latest_notification["message_id"] == second_response.json()["message_id"]
    assert latest_notification["otp_code"] == "222222"


def test_widget_latest_notification_returns_latest_otp_across_sessions(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    first_client = TestClient(create_app())
    second_client = TestClient(create_app())
    ingest_client = TestClient(create_app())

    first_mailbox = first_client.post("/mailboxes", json={"requested_local_part": "widgetone"}).json()["mailbox"]
    second_mailbox = second_client.post("/mailboxes", json={"requested_local_part": "widgettwo"}).json()["mailbox"]
    first_response = ingest_client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": first_mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "First widget code",
            "provider_message_id": "provider-widget-first",
            "body_text": "Use code 111111 to continue.",
        },
    )
    second_response = ingest_client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": second_mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "Second widget code",
            "provider_message_id": "provider-widget-second",
            "body_text": "Use code 222222 to continue.",
        },
    )

    mailboxes_response = ingest_client.get("/widget/mailboxes")
    latest_response = ingest_client.get("/widget/notifications/latest")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert mailboxes_response.status_code == 200
    assert latest_response.status_code == 200
    assert {mailbox["address"] for mailbox in mailboxes_response.json()} >= {
        first_mailbox["address"],
        second_mailbox["address"],
    }
    latest_payload = latest_response.json()
    assert latest_payload["message_id"] == second_response.json()["message_id"]
    assert latest_payload["mailbox_address"] == second_mailbox["address"]
    assert latest_payload["otp_code"] == "222222"


def test_admin_archive_is_token_protected_and_lists_all_sessions(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("ARCHIVE_ADMIN_TOKEN", "archive-secret")
    first_client = TestClient(create_app())
    second_client = TestClient(create_app())
    admin_client = TestClient(create_app())

    first_mailbox = first_client.post(
        "/mailboxes",
        json={"requested_local_part": "firstbox"},
    ).json()["mailbox"]
    second_mailbox = second_client.post(
        "/mailboxes",
        json={"requested_local_part": "secondbox"},
    ).json()["mailbox"]

    first_ingest = admin_client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": first_mailbox["address"],
            "from_address": "GitHub <noreply@github.com>",
            "subject": "GitHub code",
            "provider_message_id": "admin-archive-1",
            "body_text": "Your GitHub verification code is 111222.",
        },
    )
    second_ingest = admin_client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": second_mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "OpenAI code",
            "provider_message_id": "admin-archive-2",
            "body_text": "Your OpenAI verification code is 333444.",
            "raw_payload": {"source": "test"},
        },
    )

    assert first_ingest.status_code == 200
    assert second_ingest.status_code == 200

    missing_token_response = admin_client.get("/admin/archive/messages")
    wrong_token_response = admin_client.get(
        "/admin/archive/messages",
        headers={"X-Archive-Admin-Token": "wrong"},
    )
    archive_response = admin_client.get(
        "/admin/archive/messages",
        headers={"X-Archive-Admin-Token": "archive-secret"},
    )
    search_response = admin_client.get(
        "/admin/archive/messages?q=github",
        headers={"Authorization": "Bearer archive-secret"},
    )

    assert missing_token_response.status_code == 401
    assert wrong_token_response.status_code == 401
    assert archive_response.status_code == 200
    archive_payload = archive_response.json()
    assert len(archive_payload) == 2
    assert {message["mailbox_address"] for message in archive_payload} == {
        first_mailbox["address"],
        second_mailbox["address"],
    }
    assert search_response.status_code == 200
    assert [message["mailbox_address"] for message in search_response.json()] == [first_mailbox["address"]]

    detail_response = admin_client.get(
        f"/admin/archive/messages/{second_ingest.json()['message_id']}",
        headers={"X-Archive-Admin-Token": "archive-secret"},
    )

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["mailbox_address"] == second_mailbox["address"]
    assert detail_payload["body_text"] == "Your OpenAI verification code is 333444."
    assert detail_payload["raw_payload_json"] == '{"source": "test"}'


def test_message_detail_repairs_stored_utf8_latin1_mojibake(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("ARCHIVE_ADMIN_TOKEN", "archive-secret")
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={"requested_local_part": "mojibake"}).json()["mailbox"]
    settings = AppSettings.from_env()
    message_repo = MessageRepository(settings)
    body_text = "Ваш временный код подтверждения 123456"
    body_html = "<div>Инвойс дата: 22 апр., 20:19</div>"
    message_id = message_repo.create_ingested_message(
        mailbox_id=mailbox["id"],
        source_provider="legacy",
        provider_message_id="legacy-mojibake",
        internet_message_id=None,
        from_address="billing@example.com",
        to_address=mailbox["address"],
        subject="ChatGPT — ваш новый план",
        received_at=None,
        body_text=_as_latin1_mojibake(body_text),
        body_html=_as_latin1_mojibake(body_html),
        raw_payload_json=None,
    )

    detail_response = client.get(f"/messages/{message_id}")
    admin_detail_response = client.get(
        f"/admin/archive/messages/{message_id}",
        headers={"X-Archive-Admin-Token": "archive-secret"},
    )

    assert detail_response.status_code == 200
    assert admin_detail_response.status_code == 200
    assert detail_response.json()["body_text"] == body_text
    assert detail_response.json()["body_html"] == body_html
    assert admin_detail_response.json()["body_html"] == body_html


def test_ingest_normalizes_utf8_latin1_mojibake_before_analysis(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    body_text = "Ваш временный код подтверждения 123456"
    body_html = "<p>Инвойс дата: Apr 22, 2026</p>"

    ingest_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "ChatGPT <billing@example.com>",
            "subject": _as_latin1_mojibake("Ваш временный код"),
            "provider_message_id": "provider-mojibake",
            "body_text": _as_latin1_mojibake(body_text),
            "body_html": _as_latin1_mojibake(body_html),
        },
    )

    assert ingest_response.status_code == 200
    assert ingest_response.json()["notification"]["otp_code"] == "123456"

    message_id = ingest_response.json()["message_id"]
    detail_response = client.get(f"/messages/{message_id}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["body_text"] == body_text
    assert detail_payload["body_html"] == body_html


def test_ingest_sanitizes_nul_bytes_and_caps_stored_email_fields(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    body_text = "Use code 123456 now.\x00" + ("A" * (EMAIL_BODY_MAX_CHARS + 100))
    body_html = '<img src="https://mandrillapp.com/track/open.php?id\x001228aa">'
    raw_payload = {"html": body_html, "blob": "B" * (EMAIL_RAW_PAYLOAD_MAX_CHARS + 100)}

    ingest_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "Mailer\x00 <noreply@example.com>",
            "subject": "Code\x00 inside",
            "provider_message_id": "provider-nul",
            "body_text": body_text,
            "body_html": body_html,
            "raw_payload": raw_payload,
        },
    )

    assert ingest_response.status_code == 200
    assert ingest_response.json()["notification"]["otp_code"] == "123456"

    detail_response = client.get(f"/messages/{ingest_response.json()['message_id']}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert "\x00" not in detail_payload["from_address"]
    assert "\x00" not in detail_payload["subject"]
    assert "\x00" not in detail_payload["body_text"]
    assert "\x00" not in detail_payload["body_html"]
    assert "\\u0000" not in detail_payload["raw_payload_json"]
    assert len(detail_payload["body_text"]) == EMAIL_BODY_MAX_CHARS
    assert len(detail_payload["raw_payload_json"]) == EMAIL_RAW_PAYLOAD_MAX_CHARS


def test_message_detail_decodes_stored_quoted_printable_html(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("ARCHIVE_ADMIN_TOKEN", "archive-secret")
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={"requested_local_part": "quotedhtml"}).json()["mailbox"]
    settings = AppSettings.from_env()
    message_repo = MessageRepository(settings)
    body_html = (
        "<html><head><title>Ваш код ChatGPT 379338</title>"
        '<meta name="viewport" content="width=device-width"></head>'
        "<body><p>Код: 379338</p></body></html>"
    )
    message_id = message_repo.create_ingested_message(
        mailbox_id=mailbox["id"],
        source_provider="legacy",
        provider_message_id="legacy-quoted-printable",
        internet_message_id=None,
        from_address="billing@example.com",
        to_address=mailbox["address"],
        subject="Ваш код ChatGPT 379338",
        received_at=None,
        body_text=None,
        body_html=_as_quoted_printable(body_html),
        raw_payload_json=None,
    )

    detail_response = client.get(f"/messages/{message_id}")
    admin_detail_response = client.get(
        f"/admin/archive/messages/{message_id}",
        headers={"X-Archive-Admin-Token": "archive-secret"},
    )

    assert detail_response.status_code == 200
    assert admin_detail_response.status_code == 200
    assert detail_response.json()["body_html"] == body_html
    assert admin_detail_response.json()["body_html"] == body_html


def test_ingest_normalizes_quoted_printable_html_before_analysis(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    body_text = "Ваш код ChatGPT 379338"
    body_html = (
        "<html><head><title>Ваш код ChatGPT 379338</title></head>"
        "<body><p>Код: 379338</p></body></html>"
    )

    ingest_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "OpenAI <billing@example.com>",
            "subject": "Ваш код ChatGPT 379338",
            "provider_message_id": "provider-quoted-printable",
            "body_text": _as_quoted_printable(body_text),
            "body_html": _as_quoted_printable(body_html),
        },
    )

    assert ingest_response.status_code == 200
    assert ingest_response.json()["notification"]["otp_code"] == "379338"

    message_id = ingest_response.json()["message_id"]
    detail_response = client.get(f"/messages/{message_id}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["body_text"] == body_text
    assert detail_payload["body_html"] == body_html


def test_admin_archive_is_not_available_without_configured_token(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    response = client.get("/admin/archive/messages", headers={"X-Archive-Admin-Token": "anything"})

    assert response.status_code == 404


def test_message_detail_marks_message_as_read_and_analysis_returns_result(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={"requested_local_part": "alerts01"}).json()["mailbox"]
    client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "Example Security <security@example.com>",
            "subject": "Reset your password",
            "provider_message_id": "provider-2",
            "body_text": "Reset your password using code 778899 or open https://example.com/reset now.",
        },
    )

    inbox_before = client.get("/inbox").json()
    message_id = inbox_before[0]["id"]
    assert inbox_before[0]["is_unread"] is True

    detail_response = client.get(f"/messages/{message_id}")

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["analysis"]["otp_code"] == "778899"

    inbox_after = client.get("/inbox").json()
    assert inbox_after[0]["is_unread"] is False

    analyze_response = client.post(f"/messages/{message_id}/analyze")

    assert analyze_response.status_code == 200
    analyze_payload = analyze_response.json()
    assert analyze_payload["analysis"]["provider"] == "deterministic"
    assert analyze_payload["analysis"]["otp_code"] == "778899"
    assert "reset" in (analyze_payload["analysis"]["action_required"] or "").lower()


def test_requested_local_part_conflict_returns_409(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    client = TestClient(create_app())

    first_response = client.post("/mailboxes", json={"requested_local_part": "sharedbox"})
    second_response = client.post("/mailboxes", json={"requested_local_part": "sharedbox"})

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_create_mailbox_can_choose_requested_domain_from_allowed_list(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("PUBLIC_MAIL_DOMAINS", "samgpt.me,alt.samgpt.me")
    client = TestClient(create_app())

    config_response = client.get("/client-config")
    create_response = client.post(
        "/mailboxes",
        json={
            "requested_local_part": "altbox01",
            "requested_domain": "alt.samgpt.me",
        },
    )

    assert config_response.status_code == 200
    mail_domains = config_response.json()["mail_domains"]
    assert mail_domains[:2] == ["samgpt.me", "alt.samgpt.me"]
    assert "inbox001.samgpt.me" in mail_domains
    assert create_response.status_code == 201
    mailbox = create_response.json()["mailbox"]
    assert mailbox["domain"] == "alt.samgpt.me"
    assert mailbox["address"] == "altbox01@alt.samgpt.me"


def test_create_mailbox_rejects_domain_outside_allowed_list(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("PUBLIC_MAIL_DOMAINS", "samgpt.me,alt.samgpt.me")
    client = TestClient(create_app())

    response = client.post("/mailboxes", json={"requested_domain": "evil.example"})

    assert response.status_code == 422
    assert response.json()["detail"] == "requested_domain is not available"


def test_analysis_filters_tracking_and_asset_links(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    service = MessageAnalysisService(AppSettings.from_env())

    result = service.analyze_deterministically(
        {
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "Your ChatGPT code",
            "body_text": (
                "Use code 123456. Manage it at https://chatgpt.com/account/manage?account_id=abc "
                "Track https://mandrillapp.com/track/click/123/openai.com?p=token "
                "Pixel https://u20216706.ct.sendgrid.net/wf/open?upn=abc "
                "Logo https://cdn.openai.com/API/logo-assets/openai-logo.svg"
            ),
            "body_html": '<a href="https://help.openai.com/en/">Help center</a>',
        }
    )

    links = json.loads(str(result["action_links_json"]))

    assert "https://chatgpt.com/account/manage?account_id=abc" in links
    assert "https://help.openai.com/en/" in links
    assert all("mandrillapp.com" not in link for link in links)
    assert all("sendgrid.net" not in link for link in links)
    assert all("cdn.openai.com" not in link for link in links)


def test_ingest_triggers_auto_remote_analysis_when_groq_is_configured(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEYS", "groq-test-key")
    calls: list[bool] = []

    async def fake_analyze_message(self, message, *, allow_remote=True):
        calls.append(allow_remote)
        provider = "groq" if allow_remote else "deterministic"
        return {
            "provider": provider,
            "model": "fake-model" if allow_remote else None,
            "status": "completed",
            "summary": "Remote summary" if allow_remote else "Deterministic summary",
            "message_type": "verification",
            "otp_code": "654321",
            "action_required": "Use the verification code",
            "action_links_json": "[]",
            "sender_brand": "openai",
            "confidence": "high",
            "error_text": None,
        }

    monkeypatch.setattr(MessageAnalysisService, "analyze_message", fake_analyze_message)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    ingest_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json={
            "to_address": mailbox["address"],
            "from_address": "OpenAI <noreply@openai.com>",
            "subject": "Your login code",
            "provider_message_id": "provider-auto-1",
            "body_text": "Use code 654321 to continue.",
        },
    )

    assert ingest_response.status_code == 200
    assert calls == [False, True]

    message_id = ingest_response.json()["message_id"]
    detail_response = client.get(f"/messages/{message_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["analysis"]["provider"] == "groq"
    assert detail_response.json()["analysis"]["summary"] == "Remote summary"


def test_duplicate_ingest_does_not_overwrite_completed_groq_analysis(tmp_path, monkeypatch):
    setup_tempmail_env(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEYS", "groq-test-key")
    calls: list[bool] = []

    async def fake_analyze_message(self, message, *, allow_remote=True):
        calls.append(allow_remote)
        provider = "groq" if allow_remote else "deterministic"
        return {
            "provider": provider,
            "model": "fake-model" if allow_remote else None,
            "status": "completed",
            "summary": "Remote summary" if allow_remote else "Deterministic summary",
            "message_type": "verification",
            "otp_code": "999111",
            "action_required": "Use the verification code",
            "action_links_json": "[]",
            "sender_brand": "openai",
            "confidence": "high",
            "error_text": None,
        }

    monkeypatch.setattr(MessageAnalysisService, "analyze_message", fake_analyze_message)
    client = TestClient(create_app())

    mailbox = client.post("/mailboxes", json={}).json()["mailbox"]
    payload = {
        "to_address": mailbox["address"],
        "from_address": "OpenAI <noreply@openai.com>",
        "subject": "Your login code",
        "provider_message_id": "provider-auto-duplicate",
        "body_text": "Use code 999111 to continue.",
    }

    first_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json=payload,
    )
    second_response = client.post(
        "/ingest/messages",
        headers={"X-Ingest-Webhook-Secret": "test-ingest-secret"},
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert calls == [False, True]

    detail_response = client.get(f"/messages/{first_response.json()['message_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["analysis"]["provider"] == "groq"
