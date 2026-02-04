"""
Aesthetics and visual quality analysis.
Uses Claude Vision for primary analysis with heuristics as fallback.
"""

import re
from pathlib import Path
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from utils import get_logger

logger = get_logger(__name__)


class AestheticsExtractor:
    """Extracts aesthetics/visual quality signals from websites."""

    # Modern CSS frameworks to detect
    MODERN_FRAMEWORKS = {
        "tailwind": ["tailwindcss", "tailwind.css", "tw-"],
        "bootstrap5": ["bootstrap@5", "bootstrap.min.css"],
        "material": ["material-ui", "@mui", "material-design"],
        "chakra": ["chakra-ui", "@chakra-ui"],
        "antd": ["antd", "ant-design"],
    }

    def extract(
        self,
        html: str,
        screenshot_path: Optional[Path] = None,
        use_claude: bool = True
    ) -> Tuple[int, str]:
        """
        Extract aesthetics score from website.

        Args:
            html: HTML content
            screenshot_path: Path to screenshot (for Claude analysis)
            use_claude: Whether to use Claude Vision API

        Returns:
            Tuple of (score 1-10, notes string)
        """
        # Try Claude Vision first if available
        if use_claude and screenshot_path:
            claude_result = self._analyze_with_claude(screenshot_path)
            if claude_result:
                return claude_result

        # Fall back to heuristics
        return self._analyze_with_heuristics(html)

    def _analyze_with_claude(self, screenshot_path: Path) -> Optional[Tuple[int, str]]:
        """Analyze screenshot with Claude Vision."""
        try:
            from ..claude_vision import analyze_with_claude

            result = analyze_with_claude(screenshot_path)
            if not result:
                return None

            # Calculate average score
            scores = [
                result.get("design_modernity", 5),
                result.get("professionalism", 5),
                result.get("visual_hierarchy", 5),
                result.get("color_usage", 5),
                result.get("typography", 5),
                result.get("overall_polish", 5),
            ]
            avg_score = round(sum(scores) / len(scores))

            notes = result.get("notes", "")

            # Add score breakdown to notes
            breakdown = f"Modern:{result.get('design_modernity', '?')}, Pro:{result.get('professionalism', '?')}, Polish:{result.get('overall_polish', '?')}"
            if notes:
                notes = f"{notes} ({breakdown})"
            else:
                notes = breakdown

            return avg_score, notes

        except Exception as e:
            logger.debug(f"Claude analysis failed: {e}")
            return None

    def _analyze_with_heuristics(self, html: str) -> Tuple[int, str]:
        """Analyze website using heuristics (fallback)."""
        if not html:
            return 3, "Could not analyze (no HTML)"

        soup = BeautifulSoup(html, "lxml")
        signals = []
        score = 5  # Start with middle score

        # Check for modern CSS framework
        framework = self._detect_framework(html, soup)
        if framework:
            signals.append(f"Uses {framework}")
            score += 1

        # Check for responsive design
        viewport_meta = soup.find("meta", {"name": "viewport"})
        if viewport_meta:
            signals.append("Responsive")
            score += 1

        # Check for HTTPS (should be in URL, but check for relative/secure links)
        if 'https://' in html or not 'http://' in html:
            score += 0.5

        # Check for web fonts
        if self._has_web_fonts(html, soup):
            signals.append("Web fonts")
            score += 0.5

        # Check for modern image formats
        if self._has_modern_images(soup):
            signals.append("Optimized images")
            score += 0.5

        # Check for lazy loading
        if 'loading="lazy"' in html or "lazyload" in html.lower():
            signals.append("Lazy loading")
            score += 0.5

        # Check for semantic HTML5
        semantic_tags = ["header", "nav", "main", "article", "section", "footer"]
        semantic_count = sum(1 for tag in semantic_tags if soup.find(tag))
        if semantic_count >= 3:
            signals.append("Semantic HTML")
            score += 0.5

        # Check for dark mode support
        if "prefers-color-scheme" in html:
            signals.append("Dark mode")
            score += 0.5

        # Penalize for outdated patterns
        if "<table" in html.lower() and "layout" in html.lower():
            signals.append("Table layout (outdated)")
            score -= 1

        if "<marquee" in html.lower() or "<blink" in html.lower():
            signals.append("Outdated elements")
            score -= 2

        # Check for broken/missing images (basic check)
        imgs = soup.find_all("img")
        if imgs and not any(img.get("src") for img in imgs):
            signals.append("Missing images")
            score -= 1

        # Cap score
        score = max(1, min(10, round(score)))

        notes = ", ".join(signals) if signals else "Basic heuristics analysis"
        return score, notes

    def _detect_framework(self, html: str, soup: BeautifulSoup) -> Optional[str]:
        """Detect modern CSS framework."""
        html_lower = html.lower()

        for framework, patterns in self.MODERN_FRAMEWORKS.items():
            for pattern in patterns:
                if pattern.lower() in html_lower:
                    return framework.capitalize()

        # Check for Tailwind classes
        tailwind_classes = ["flex", "grid", "p-4", "m-4", "text-", "bg-", "rounded-"]
        all_classes = []
        for tag in soup.find_all(class_=True):
            classes = tag.get("class", [])
            if isinstance(classes, list):
                all_classes.extend(classes)
            elif classes:
                all_classes.append(str(classes))
        class_str = " ".join(all_classes)
        if any(tc in class_str for tc in tailwind_classes):
            tailwind_count = sum(1 for tc in tailwind_classes if tc in class_str)
            if tailwind_count >= 3:
                return "Tailwind"

        return None

    def _has_web_fonts(self, html: str, soup: BeautifulSoup) -> bool:
        """Check for web font usage."""
        font_services = [
            "fonts.googleapis.com",
            "use.typekit.net",
            "fonts.adobe.com",
            "cloud.typography.com",
        ]

        for service in font_services:
            if service in html:
                return True

        # Check for @font-face in inline styles
        styles = soup.find_all("style")
        for style in styles:
            if style.string and "@font-face" in style.string:
                return True

        return False

    def _has_modern_images(self, soup: BeautifulSoup) -> bool:
        """Check for modern image formats."""
        # Check for WebP or AVIF
        for img in soup.find_all("img"):
            src = img.get("src", "") + img.get("srcset", "")
            if ".webp" in src or ".avif" in src:
                return True

        # Check for picture elements with sources
        if soup.find("picture"):
            return True

        return False
