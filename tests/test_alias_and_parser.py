from app.services.alias_service import generate_alias_local_part, normalize_alias_email
from app.services.parser_service import extract_delivered_alias


def test_generate_alias_local_part_has_requested_length_and_charset():
    alias = generate_alias_local_part(length=10)

    assert len(alias) == 10
    assert alias.islower()
    assert alias.isalnum()


def test_normalize_alias_email_combines_local_part_and_domain():
    assert normalize_alias_email("abc123", "example.com") == "abc123@example.com"


def test_extract_delivered_alias_prefers_delivered_to_header():
    headers = {
        "Delivered-To": "x7k2q@example.com",
        "To": "fallback@example.com",
    }

    assert extract_delivered_alias(headers) == "x7k2q@example.com"


def test_extract_delivered_alias_falls_back_to_to_header_with_display_name():
    headers = {
        "To": 'GitHub Notifications <repoalias@example.com>',
    }

    assert extract_delivered_alias(headers) == "repoalias@example.com"


def test_extract_delivered_alias_prefers_forwarded_alias_when_delivered_to_is_primary_mailbox():
    headers = {
        "Delivered-To": "17lunin021189@gmail.com",
        "To": "retyi-7466@a.samgpt.me",
        "X-Forwarded-For": "retyi-7466@a.samgpt.me 17lunin021189@gmail.com",
    }

    assert extract_delivered_alias(headers) == "retyi-7466@a.samgpt.me"


def test_extract_delivered_alias_returns_none_when_no_address_found():
    assert extract_delivered_alias({"Subject": "hello"}) is None
