"""Mailer backends and the bilingual invitation (R11.AC11, R11.AC14, R11.AC15)."""

import logging
import smtplib
from datetime import date

import pytest

from app.config import get_settings
from app.platform.mail import api as mail

LINK = "https://books.example.sa/invitations/abc123/accept"
EXPIRES = date(2026, 9, 25)


@pytest.fixture
def invitation() -> mail.Email:
    return mail.render_invitation("ashraf@example.sa", "Ashraf", LINK, EXPIRES)


def test_invitation_is_addressed_and_has_both_languages_in_the_subject(
    invitation: mail.Email,
) -> None:
    assert invitation.to == "ashraf@example.sa"
    assert "تفعيل حسابك" in invitation.subject
    assert "Set up your FinanceBoard account" in invitation.subject


def test_invitation_text_carries_arabic_english_link_and_expiry(invitation: mail.Email) -> None:
    assert "مرحباً Ashraf" in invitation.text
    assert "Hello Ashraf" in invitation.text
    assert LINK in invitation.text
    assert EXPIRES.isoformat() in invitation.text


def test_invitation_html_marks_direction_for_each_language(invitation: mail.Email) -> None:
    assert 'dir="rtl" lang="ar"' in invitation.html
    assert 'dir="ltr" lang="en"' in invitation.html
    assert f'href="{LINK}"' in invitation.html


def test_message_has_a_text_part_and_an_html_alternative(invitation: mail.Email) -> None:
    message = invitation.as_message("FinanceBoard <no-reply@example.sa>")
    assert message["To"] == "ashraf@example.sa"
    assert message["From"] == "FinanceBoard <no-reply@example.sa>"
    types = {part.get_content_type() for part in message.walk()}
    assert {"text/plain", "text/html"} <= types


def test_links_come_from_the_configured_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "public_base_url", "https://books.example.sa/", raising=False)
    assert mail.invitation_link("tok").startswith("https://books.example.sa/invitations/tok")


def test_recording_backend_keeps_what_would_have_been_sent(invitation: mail.Email) -> None:
    mailer = mail.RecordingMailer()
    mailer.send(invitation)
    assert mailer.sent == [invitation]


def test_recording_backend_can_simulate_a_refusing_relay(invitation: mail.Email) -> None:
    mailer = mail.RecordingMailer(fail_with="mailbox full")
    with pytest.raises(mail.MailDeliveryError):
        mailer.send(invitation)
    assert mailer.sent == []


def test_log_backend_writes_the_email_when_no_relay_is_configured(
    invitation: mail.Email, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.mail"):
        mail.LogMailer().send(invitation)
    assert LINK in caplog.text
    assert "No SMTP relay configured" in caplog.text


def test_backend_choice_follows_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", None, raising=False)
    assert isinstance(mail.get_mailer(), mail.LogMailer)

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.sa", raising=False)
    assert isinstance(mail.get_mailer(), mail.SmtpMailer)


def test_smtp_failures_become_mail_delivery_errors(
    invitation: mail.Email, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11.AC10 relies on this: the invitation survives and can be resent."""

    def refuse(*args, **kwargs):
        raise smtplib.SMTPConnectError(421, "service not available")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.sa", raising=False)

    with pytest.raises(mail.MailDeliveryError):
        mail.SmtpMailer().send(invitation)
