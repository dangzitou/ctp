from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "apps" / "web" / "dist-test-artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    screenshot_path = ARTIFACT_DIR / "smoke-home.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        console_errors: list[str] = []
        page.on(
            "console",
            lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )

        try:
            page.goto("http://127.0.0.1:5173", wait_until="networkidle", timeout=60_000)
            page.wait_for_selector("text=CTP Agent Workstation", timeout=30_000)
            page.wait_for_selector("text=Agent Sessions", timeout=30_000)
            page.wait_for_selector("text=Conversation + Structured Action", timeout=30_000)
            page.click("text=给我一份 AL2605 的日内执行清单")
            page.wait_for_selector("text=当前判断", timeout=30_000)
            page.wait_for_selector("text=AL2605", timeout=30_000)
            page.screenshot(path=str(screenshot_path), full_page=True)
        except PlaywrightTimeoutError as exc:
            print(f"Smoke test timed out: {exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()

        if console_errors:
            print("Browser console errors detected:", file=sys.stderr)
            for item in console_errors:
                print(item, file=sys.stderr)
            return 1

    print(f"Smoke E2E passed. Screenshot: {screenshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
