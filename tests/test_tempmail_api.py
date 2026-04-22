from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ai_service import MessageAnalysisService


def setup_tempmail_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("PUBLIC_MAIL_DOMAIN", "samgpt.me")
    monkeypatch.delenv("PUBLIC_MAIL_DOMAINS", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("INGEST_WEBHOOK_SECRET", "test-ingest-secret")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    for index in range(1, 10):
        monkeypatch.delenv(f"GROQ_API_KEY_{index}", raising=False)


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
    config_response = client.get("/client-config")
    script_response = client.get("/static/app.js")
    style_response = client.get("/static/app.css")
    manifest_response = client.get("/manifest.webmanifest")
    worker_response = client.get("/service-worker.js")

    assert index_response.status_code == 200
    assert "SamGPT Temp Mail" in index_response.text
    assert "private-secret-key" not in index_response.text
    assert script_response.status_code == 200
    assert style_response.status_code == 200
    assert manifest_response.status_code == 200
    assert worker_response.status_code == 200
    assert "private-secret-key" not in script_response.text
    assert "private-secret-key" not in style_response.text
    assert "data-copy-code" in script_response.text
    assert "OTP ${escapeHtml(message.otp_code)}" not in script_response.text
    assert "<small>Code</small>" in script_response.text

    assert config_response.status_code == 200
    payload = config_response.json()
    assert payload["mail_domain"] == "samgpt.me"
    assert payload["mail_domains"] == ["samgpt.me"]
    assert payload["turnstile_site_key"] == "public-site-key"
    assert payload["turnstile_enabled"] is True
    assert "private-secret-key" not in config_response.text


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

    assert len(inbox_payload) == 1
    assert len(mailbox_history_payload) == 1
    assert inbox_payload[0]["otp_code"] == "654321"
    assert inbox_payload[0]["mailbox_address"] == mailbox["address"]
    assert inbox_payload[0]["is_unread"] is True
    assert mailbox_history_payload[0]["id"] == inbox_payload[0]["id"]
    assert latest_notification_payload["otp_code"] == "654321"


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
    assert config_response.json()["mail_domains"] == ["samgpt.me", "alt.samgpt.me"]
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
