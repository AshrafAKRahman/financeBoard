"""Outbound email, with the provider left as deployment configuration.

Three backends: SMTP for real relays (Resend, Amazon SES, Alibaba DirectMail, anything
speaking SMTP), a log backend when no relay is configured, and a recording backend for
tests. Nothing above this module knows which one is in use.
"""

import logging
import smtplib
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from typing import Protocol

from app.config import get_settings

logger = logging.getLogger("app.mail")


class MailDeliveryError(Exception):
    """The relay refused or could not be reached."""


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    text: str
    html: str

    def as_message(self, sender: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = self.to
        message["Subject"] = self.subject
        message.set_content(self.text)
        message.add_alternative(self.html, subtype="html")
        return message


class Mailer(Protocol):
    def send(self, email: Email) -> None: ...


class SmtpMailer:
    def __init__(self) -> None:
        self._settings = get_settings()

    def send(self, email: Email) -> None:
        settings = self._settings
        try:
            with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_starttls:
                    smtp.starttls()
                if settings.smtp_user and settings.smtp_password:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(email.as_message(settings.mail_from))
        except (OSError, smtplib.SMTPException) as exc:
            raise MailDeliveryError(str(exc)) from exc


class LogMailer:
    """Used when no relay is configured: the email, link included, goes to the log so a
    developer can follow the invitation (R11.AC15). Never for production use."""

    def send(self, email: Email) -> None:
        logger.warning(
            "No SMTP relay configured; invitation email not sent.\nTo: %s\nSubject: %s\n%s",
            email.to,
            email.subject,
            email.text,
        )


@dataclass
class RecordingMailer:
    """Test backend: keeps what would have been sent."""

    sent: list[Email] = field(default_factory=list)
    fail_with: str | None = None

    def send(self, email: Email) -> None:
        if self.fail_with is not None:
            raise MailDeliveryError(self.fail_with)
        self.sent.append(email)


def get_mailer() -> Mailer:
    return SmtpMailer() if get_settings().smtp_host else LogMailer()


def render_invitation(to: str, name: str, link: str, expires_on: date) -> Email:
    """Bilingual invitation: Arabic first, then English (R11.AC11)."""
    expiry = expires_on.isoformat()
    subject = "تفعيل حسابك في FinanceBoard · Set up your FinanceBoard account"
    text = f"""مرحباً {name}،

تمت دعوتك إلى FinanceBoard. لتفعيل حسابك واختيار كلمة المرور الخاصة بك، افتح الرابط التالي:

{link}

ينتهي هذا الرابط في {expiry} ويُستخدم مرة واحدة فقط. لا تشاركه مع أي شخص.

—

Hello {name},

You have been invited to FinanceBoard. To activate your account and choose your own
password, open this link:

{link}

The link expires on {expiry} and can be used once. Please do not share it with anyone.
"""
    html = f"""<!doctype html>
<html>
  <body style="font-family: system-ui, sans-serif; line-height: 1.5;">
    <div dir="rtl" lang="ar">
      <p>مرحباً {name}،</p>
      <p>تمت دعوتك إلى FinanceBoard. لتفعيل حسابك واختيار كلمة المرور الخاصة بك:</p>
      <p><a href="{link}">تفعيل الحساب</a></p>
      <p>ينتهي هذا الرابط في {expiry} ويُستخدم مرة واحدة فقط. لا تشاركه مع أي شخص.</p>
    </div>
    <hr />
    <div dir="ltr" lang="en">
      <p>Hello {name},</p>
      <p>You have been invited to FinanceBoard. To activate your account and choose your
         own password:</p>
      <p><a href="{link}">Set up your account</a></p>
      <p>The link expires on {expiry} and can be used once. Please do not share it.</p>
    </div>
  </body>
</html>
"""
    return Email(to=to, subject=subject, text=text, html=html)


def invitation_link(raw_token: str) -> str:
    """Built from the configured public URL so links work in dev and in production
    without code changes (R11.AC14)."""
    return f"{get_settings().public_base_url.rstrip('/')}/invitations/{raw_token}/accept"
