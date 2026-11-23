import json
import urllib.request

import pytest

import access as a


SITE = {"SITE_NAME": "My Campaign", "SITE_URL": "https://wiki.example.com", "MAIL_FROM": "wiki@example.com"}


def test_welcome_email_greets_by_name_and_names_the_sign_in_address():
    result = a.welcome_email("Alex", "c@example.com", SITE)

    assert result == {
        "from": "My Campaign wiki <wiki@example.com>",
        "to": ["c@example.com"],
        "subject": "You're in: My Campaign wiki",
        "text": (
            "Hi Alex,\n\nYour access to the My Campaign wiki is approved. Open https://wiki.example.com "
            "and sign in with this address (c@example.com).\n\nSpot a mistake? Every page has a corrections box at the bottom.\n"
        ),
    }


@pytest.mark.parametrize("value", ["not-an-email", "x'@y.com", "a@b"])
def test_checked_email_rejects_values_unsafe_for_sql(value):
    with pytest.raises(SystemExit):
        a.checked_email(value)


def test_approve_saves_the_member_before_emailing_them(monkeypatch):
    calls = []
    monkeypatch.setattr(a, "run", lambda sql: calls.append(("sql", sql)) or ([] if sql.startswith("SELECT 1") else [{"name": "Alex"}]))
    monkeypatch.setattr(a, "resend_key", lambda: "re_test")
    monkeypatch.setattr(a, "site_settings", lambda: SITE)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: calls.append(("email", json.loads(req.data))))

    a.main(["approve", "c@example.com"])

    assert [kind for kind, _ in calls] == ["sql", "sql", "sql", "email"]
    assert calls[1][1].startswith("INSERT INTO members")
    assert calls[3][1]["to"] == ["c@example.com"]


def test_approving_an_existing_member_changes_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(a, "run", lambda sql: calls.append(sql) or [{"1": 1}])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *x, **k: calls.append("email"))

    a.main(["approve", "c@example.com"])

    assert calls == ["SELECT 1 FROM members WHERE email = 'c@example.com'"]


def test_approve_quiet_sends_no_email(monkeypatch):
    sent = []
    monkeypatch.setattr(a, "run", lambda sql: [] if sql.startswith("SELECT 1") else [{"name": "Alex"}])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *x, **k: sent.append(1))

    a.main(["approve", "c@example.com", "--quiet"])

    assert sent == []
