#!/usr/bin/env python3
"""Send review result email through SMTP."""

from __future__ import annotations

import argparse
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"missing required env: {name}")
    return value


def build_message(subject: str, to_addr: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.getenv("MAIL_FROM", "").strip() or env_required("SMTP_USERNAME")
    message["To"] = to_addr
    message.set_content(body, subtype="plain", charset="utf-8")
    return message


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--to", required=True)
    args = parser.parse_args()

    body_path = Path(args.body_file)
    body = body_path.read_text(encoding="utf-8")

    smtp_host = env_required("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip() or "587")
    smtp_username = env_required("SMTP_USERNAME")
    smtp_password = env_required("SMTP_PASSWORD")
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no", "off"}

    message = build_message(args.subject, args.to, body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        if smtp_use_tls:
            server.starttls()
            server.ehlo()
        server.login(smtp_username, smtp_password)
        server.send_message(message)

    print(f"sent email to {args.to}")


if __name__ == "__main__":
    main()
