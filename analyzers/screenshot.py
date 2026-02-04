"""
Screenshot capture using Playwright.
"""

import asyncio
from pathlib import Path
from typing import Optional

from utils import get_logger

logger = get_logger(__name__)

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


class ScreenshotCapture:
    """Captures website screenshots using Playwright."""

    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        """Ensure browser is initialized."""
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--no-sandbox"]
                )
                logger.debug("Playwright browser initialized")
            except ImportError:
                logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize browser: {e}")
                raise

    async def capture(self, url: str, width: int = 1280, height: int = 800) -> Optional[Path]:
        """
        Capture a screenshot of a website.

        Args:
            url: Website URL to capture
            width: Viewport width
            height: Viewport height

        Returns:
            Path to saved screenshot, or None if failed
        """
        await self._ensure_browser()

        # Generate filename from URL
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in domain)
        screenshot_path = SCREENSHOTS_DIR / f"{safe_name}.png"

        try:
            page = await self._browser.new_page(
                viewport={"width": width, "height": height}
            )

            # Set timeout and navigate
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")

            # Wait a bit for dynamic content
            await asyncio.sleep(2)

            # Capture screenshot
            await page.screenshot(path=str(screenshot_path), full_page=False)

            await page.close()
            logger.debug(f"Screenshot saved: {screenshot_path}")
            return screenshot_path

        except Exception as e:
            logger.debug(f"Screenshot failed for {url}: {e}")
            return None

    async def close(self):
        """Close the browser."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def capture_sync(self, url: str, width: int = 1280, height: int = 800) -> Optional[Path]:
        """Synchronous wrapper for capture."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.capture(url, width, height))

    def close_sync(self):
        """Synchronous wrapper for close."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(self.close())


# Global instance for reuse
_screenshot_capture = None


def get_screenshot_capture() -> ScreenshotCapture:
    """Get or create a global ScreenshotCapture instance."""
    global _screenshot_capture
    if _screenshot_capture is None:
        _screenshot_capture = ScreenshotCapture()
    return _screenshot_capture


def capture_screenshot(url: str) -> Optional[Path]:
    """Convenience function to capture a screenshot."""
    return get_screenshot_capture().capture_sync(url)
