"""Capture screenshots of the Quórum frontend for the INF memoir.

Runs Playwright (sync) against the running dev server (port 5173 by default)
and writes deterministic PNGs to ``memoria/ingenieria/img/``.

The script captures:

- ``capture_7_2_5_board_light.png``
- ``capture_7_2_5_board_dark.png``
- ``capture_7_2_5_detail_light.png``
- ``capture_7_2_5_detail_dark.png``
- ``capture_7_5_3_preguntar_light.png``
- ``capture_7_4_1_evaluation_light.png``

Each shot uses a 1440×900 viewport so cropping in Word is predictable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from playwright.sync_api import sync_playwright, Page, BrowserContext

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "memoria" / "ingenieria" / "img"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "http://localhost:5173/static/"
VIEWPORT = {"width": 1440, "height": 900}


def set_theme(page: Page, theme: str) -> None:
    """Force the theme without going through the toggle's three-state cycle."""
    page.evaluate(
        """
        ({theme}) => {
          const html = document.documentElement;
          if (theme === 'system') {
            html.removeAttribute('data-theme');
            localStorage.removeItem('tfg.theme');
          } else {
            html.setAttribute('data-theme', theme);
            localStorage.setItem('tfg.theme', theme);
          }
        }
        """,
        {"theme": theme},
    )
    page.wait_for_timeout(180)


def goto(page: Page, path: str) -> None:
    page.goto(BASE_URL.rstrip("/") + path, wait_until="networkidle")
    page.wait_for_timeout(450)


def snap(page: Page, name: str) -> None:
    out = OUT_DIR / name
    page.screenshot(path=str(out), full_page=False)
    print(f"  wrote {out.relative_to(ROOT)}")


def get_first_commitment_id(context: BrowserContext) -> str | None:
    api = context.request.get("http://localhost:8000/api/commitments")
    if not api.ok:
        return None
    body = api.json()
    if not body:
        return None
    return body[0].get("commitment_id")


def click_link_to_detail(page: Page) -> None:
    """Find the first link going to /compromisos/... on the board and click it.
    React Router will handle the SPA navigation in-place (without a hard reload),
    which avoids the Vite base-path issue when we navigate by URL."""
    link = page.locator('a[href*="/compromisos/"]').first
    link.wait_for(state="visible", timeout=5000)
    link.click()
    page.wait_for_timeout(700)


def click_navlink(page: Page, label: str) -> None:
    page.get_by_role("link", name=label, exact=True).first.click()
    page.wait_for_timeout(700)


def captures(themes: Iterable[str]) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = context.new_page()

        for theme in themes:
            print(f"theme={theme}")
            # Board
            goto(page, "/")
            set_theme(page, theme)
            page.wait_for_timeout(250)
            snap(page, f"capture_7_2_5_board_{theme}.png")

            # Detail — navigate by clicking a board row.
            click_link_to_detail(page)
            page.wait_for_timeout(400)
            snap(page, f"capture_7_2_5_detail_{theme}.png")

        # Ask + Evaluation — light only is enough for these single-shot ones.
        print("theme=light (singletons)")
        goto(page, "/")
        set_theme(page, "light")
        click_navlink(page, "Preguntar")
        snap(page, "capture_7_5_3_preguntar_light.png")

        # Evaluation page — try /evaluacion via the discrete board footer link.
        goto(page, "/")
        set_theme(page, "light")
        # No nav link for evaluation; use programmatic React Router push by
        # clicking the discrete footer anchor if present, otherwise fall back
        # to direct location set.
        anchor = page.locator('a[href*="/evaluacion"]').first
        try:
            anchor.wait_for(state="visible", timeout=2500)
            anchor.click()
            page.wait_for_timeout(600)
        except Exception:
            page.evaluate("history.pushState({}, '', '/evaluacion'); dispatchEvent(new PopStateEvent('popstate'))")
            page.wait_for_timeout(700)
        snap(page, "capture_7_4_1_evaluation_light.png")

        context.close()
        browser.close()


if __name__ == "__main__":
    captures(["light", "dark"])
