"""
Brand coherency analysis.
Analyzes logo presence, color consistency, Open Graph tags, etc.
"""

import re
from typing import Tuple
from bs4 import BeautifulSoup

from utils import get_logger

logger = get_logger(__name__)


class BrandExtractor:
    """Extracts brand coherency signals from websites."""

    def extract(self, html: str, url: str, company_name: str = "") -> Tuple[int, str]:
        """
        Extract brand coherency score from website.

        Args:
            html: HTML content
            url: Website URL
            company_name: Company name for matching

        Returns:
            Tuple of (score 1-10, notes string)
        """
        if not html:
            return 3, "Could not analyze (no HTML)"

        soup = BeautifulSoup(html, "lxml")
        signals = []
        score = 5  # Start with middle score

        # 1. Check for logo
        if self._has_logo(soup):
            signals.append("Logo present")
            score += 1
        else:
            signals.append("No logo found")
            score -= 1

        # 2. Check Open Graph tags
        og_score, og_notes = self._check_open_graph(soup)
        if og_score > 0:
            signals.append(og_notes)
            score += og_score

        # 3. Check Twitter Card
        if self._has_twitter_card(soup):
            signals.append("Twitter Card")
            score += 0.5

        # 4. Check favicon and touch icons
        favicon_score = self._check_favicons(soup)
        if favicon_score > 0:
            signals.append("Favicon/icons")
            score += favicon_score

        # 5. Check domain vs company name alignment
        if company_name:
            alignment = self._check_name_alignment(url, company_name, soup)
            if alignment > 0:
                signals.append("Name matches domain")
                score += alignment
            elif alignment < 0:
                signals.append("Name/domain mismatch")
                score += alignment

        # 6. Check for consistent meta description
        if self._has_meta_description(soup):
            signals.append("Meta description")
            score += 0.5

        # 7. Check for professional title tag
        title = soup.find("title")
        if title and title.string:
            title_text = title.string.strip()
            if len(title_text) > 10 and len(title_text) < 70:
                signals.append("Good title")
                score += 0.5
            elif not title_text or title_text.lower() in ["home", "untitled", "index"]:
                signals.append("Poor title")
                score -= 1

        # Cap score
        score = max(1, min(10, round(score)))

        notes = ", ".join(signals) if signals else "Basic brand analysis"
        return score, notes

    def _has_logo(self, soup: BeautifulSoup) -> bool:
        """Check for logo presence."""
        # Check for images with logo in class, id, or alt
        for img in soup.find_all("img"):
            # Check class attribute
            classes = img.get("class", [])
            if isinstance(classes, list):
                class_str = " ".join(classes)
            else:
                class_str = str(classes)
            if "logo" in class_str.lower():
                return True

            # Check id attribute
            img_id = img.get("id", "")
            if "logo" in img_id.lower():
                return True

            # Check alt attribute
            alt = img.get("alt", "")
            if "logo" in alt.lower():
                return True

        # Check for SVGs with logo class
        for svg in soup.find_all("svg"):
            classes = svg.get("class", [])
            if isinstance(classes, list):
                class_str = " ".join(classes)
            else:
                class_str = str(classes)
            if "logo" in class_str.lower():
                return True

        # Check for anchor tags with logo class (often used for logo links)
        for a in soup.find_all("a"):
            classes = a.get("class", [])
            if isinstance(classes, list):
                class_str = " ".join(classes)
            else:
                class_str = str(classes)
            if re.match(r'^logo$|logo-|logo\s', class_str.lower()):
                return True

        return False

    def _check_open_graph(self, soup: BeautifulSoup) -> Tuple[float, str]:
        """Check Open Graph tag completeness."""
        og_tags = {
            "og:title": soup.find("meta", property="og:title"),
            "og:description": soup.find("meta", property="og:description"),
            "og:image": soup.find("meta", property="og:image"),
            "og:url": soup.find("meta", property="og:url"),
        }

        present = sum(1 for v in og_tags.values() if v and v.get("content"))

        if present >= 4:
            return 1.5, "Complete OG tags"
        elif present >= 2:
            return 0.5, "Partial OG tags"
        elif present == 1:
            return 0, "Minimal OG tags"
        else:
            return -0.5, "Missing OG tags"

    def _has_twitter_card(self, soup: BeautifulSoup) -> bool:
        """Check for Twitter Card meta tags."""
        twitter_tags = [
            soup.find("meta", {"name": "twitter:card"}),
            soup.find("meta", {"name": "twitter:title"}),
            soup.find("meta", {"name": "twitter:image"}),
        ]
        return sum(1 for t in twitter_tags if t) >= 2

    def _check_favicons(self, soup: BeautifulSoup) -> float:
        """Check for favicon and app icons."""
        score = 0

        # Standard favicon
        if soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon"):
            score += 0.5

        # Apple touch icon
        if soup.find("link", rel="apple-touch-icon"):
            score += 0.5

        # Manifest (PWA)
        if soup.find("link", rel="manifest"):
            score += 0.5

        return min(score, 1)

    def _check_name_alignment(self, url: str, company_name: str, soup: BeautifulSoup) -> float:
        """Check if domain aligns with company name."""
        # Extract domain
        domain = url.lower()
        for prefix in ["https://", "http://", "www."]:
            domain = domain.replace(prefix, "")
        domain = domain.split("/")[0].split(".")[0]  # Get base domain

        # Normalize company name
        name_lower = company_name.lower()
        name_normalized = re.sub(r'[^a-z0-9]', '', name_lower)

        # Check for match
        domain_normalized = re.sub(r'[^a-z0-9]', '', domain)

        if domain_normalized == name_normalized:
            return 1  # Perfect match
        elif domain_normalized in name_normalized or name_normalized in domain_normalized:
            return 0.5  # Partial match
        elif any(word in domain for word in name_lower.split() if len(word) > 3):
            return 0.25  # Word match

        # Check title for company name
        title = soup.find("title")
        if title and company_name.lower() in title.string.lower():
            return 0.25

        return -0.5  # No match

    def _has_meta_description(self, soup: BeautifulSoup) -> bool:
        """Check for meta description."""
        meta = soup.find("meta", {"name": "description"})
        if meta:
            content = meta.get("content", "")
            return len(content) > 50
        return False
