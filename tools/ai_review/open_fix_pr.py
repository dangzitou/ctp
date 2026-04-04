#!/usr/bin/env python3
"""Create or update an AI auto-fix pull request."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import main_cli_error
from .github_api import ensure_label, upsert_pull_request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")
    ensure_label("automation", "5319e7", "Automation-generated issue or pull request")
    ensure_label("triage", "d4c5f9", "Needs triage")
    pr = upsert_pull_request(args.title, body, args.head, args.base, ["automation", "triage"])
    print(pr.get("html_url", ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        main_cli_error(exc)
