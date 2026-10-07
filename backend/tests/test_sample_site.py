import asyncio
from pathlib import Path

from axe_core_python.async_playwright import Axe
from playwright.async_api import async_playwright


DEMO_SITE = Path(__file__).resolve().parents[2] / "sample-sites" / "broken-site" / "index.html"


def test_broken_site_has_only_the_intended_image_alt_violation() -> None:
    async def scan_fixture() -> list[dict[str, object]]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(DEMO_SITE.read_text(encoding="utf-8"))
                result = await Axe().run(page)
                violations = result.get("violations")
                assert isinstance(violations, list)
                return violations
            finally:
                await browser.close()

    violations = asyncio.run(scan_fixture())

    assert [violation["id"] for violation in violations] == ["image-alt"]
