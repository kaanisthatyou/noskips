"""Sending the two emails this product has.

Behind an interface on purpose. Launch is on Gmail SMTP — free, no domain
required, 500 messages a day, which is a long way past where this needs to
scale before it earns a real domain. The day noskips.app exists, swapping to
Resend is changing one environment variable, not rewriting call sites.

Configure with:
    EMAIL_BACKEND=console|smtp     (default: console)
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
"""

import os
import smtplib
from email.message import EmailMessage


class EmailSender:
    def send(self, to, subject, body):  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleSender(EmailSender):
    """Development default. Prints the mail — including the link — to the log,
    so nobody needs SMTP credentials to work on signup."""

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        print(f"\n--- email to {to} ---\n{subject}\n\n{body}\n---\n")
        return True


class SmtpSender(EmailSender):
    def __init__(self, host, port, user, password, sender):
        self.host, self.port = host, int(port)
        self.user, self.password, self.sender = user, password, sender

    def send(self, to, subject, body):
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(msg)
        return True


def from_env():
    # `or` throughout: .env.example ships these present and empty, so a copied
    # .env would otherwise give smtplib an empty host and int("") a port.
    # See server/db.py for why blank has to mean unset everywhere.
    if (os.environ.get("EMAIL_BACKEND") or "console") == "smtp":
        return SmtpSender(
            os.environ.get("SMTP_HOST") or "smtp.gmail.com",
            os.environ.get("SMTP_PORT") or 587,
            os.environ["SMTP_USER"],
            os.environ["SMTP_PASSWORD"],
            os.environ.get("EMAIL_FROM") or os.environ.get("SMTP_USER") or "",
        )
    return ConsoleSender()


# ------------------------------------------------------------------ bodies ----
# Plain text, in the app's voice. No HTML email, no tracking pixel, no
# "click here to unsubscribe from transactional mail you asked for".


def verification(base_url, token):
    return (
        "noskips — confirm your address",
        "you're one click from a shelf.\n\n"
        f"{base_url}/verify?token={token}\n\n"
        "this link works for 24 hours. if you didn't sign up, ignore this —\n"
        "nothing happens until someone clicks it.\n\n"
        "— noskips",
    )


def password_reset(base_url, token):
    return (
        "noskips — reset your password",
        "someone (hopefully you) asked to reset your password.\n\n"
        f"{base_url}/reset?token={token}\n\n"
        "this link works for one hour and once only. if it wasn't you,\n"
        "ignore this and nothing changes.\n\n"
        "— noskips",
    )
