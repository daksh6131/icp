"""
Social presence analysis.
Detects and validates social media links on websites.
"""

import re
from typing import Dict, List, Tuple
from bs4 import BeautifulSoup
import requests

from utils import get_logger

logger = get_logger(__name__)


class SocialPresenceExtractor:
    """Extracts and validates social media presence from websites."""

    # Social media platform patterns
    SOCIAL_PATTERNS = {
        "linkedin": [
            r'linkedin\.com/company/([a-zA-Z0-9-]+)',
            r'linkedin\.com/in/([a-zA-Z0-9-]+)',
        ],
        "twitter": [
            r'twitter\.com/([a-zA-Z0-9_]+)',
            r'x\.com/([a-zA-Z0-9_]+)',
        ],
        "github": [
            r'github\.com/([a-zA-Z0-9-]+)',
        ],
        "facebook": [
            r'facebook\.com/([a-zA-Z0-9.]+)',
        ],
        "instagram": [
            r'instagram\.com/([a-zA-Z0-9._]+)',
        ],
        "youtube": [
            r'youtube\.com/(?:c/|channel/|@)([a-zA-Z0-9_-]+)',
        ],
        "discord": [
            r'discord\.(?:gg|com)/([a-zA-Z0-9]+)',
        ],
    }

    # Platforms that indicate strong tech/startup presence
    TECH_PLATFORMS = ["linkedin", "twitter", "github"]

    def __init__(self, validate_links: bool = True):
        """
        Initialize the extractor.

        Args:
            validate_links: Whether to validate links with HEAD requests
        """
        self.validate_links = validate_links

    def extract(self, html: str, session: requests.Session = None) -> Tuple[int, str]:
        """
        Extract social presence score from website.

        Args:
            html: HTML content
            session: Optional requests session for validation

        Returns:
            Tuple of (score 1-10, comma-separated list of platforms)
        """
        if not html:
            return 3, ""

        soup = BeautifulSoup(html, "lxml")

        # Find all social links
        found_socials = self._find_social_links(html, soup)

        # Validate links if enabled
        if self.validate_links and session and found_socials:
            found_socials = self._validate_links(found_socials, session)

        # Calculate score
        score = self._calculate_score(found_socials)

        # Format platform list
        platforms = ", ".join(sorted(found_socials.keys()))

        return score, platforms

    def _find_social_links(self, html: str, soup: BeautifulSoup) -> Dict[str, str]:
        """Find social media links in HTML."""
        found = {}

        # Search in full HTML text
        for platform, patterns in self.SOCIAL_PATTERNS.items():
            for pattern in patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    # Construct full URL
                    handle = matches[0]
                    if platform == "linkedin":
                        if "/in/" in pattern:
                            url = f"https://linkedin.com/in/{handle}"
                        else:
                            url = f"https://linkedin.com/company/{handle}"
                    elif platform == "twitter":
                        url = f"https://twitter.com/{handle}"
                    elif platform == "github":
                        url = f"https://github.com/{handle}"
                    elif platform == "facebook":
                        url = f"https://facebook.com/{handle}"
                    elif platform == "instagram":
                        url = f"https://instagram.com/{handle}"
                    elif platform == "youtube":
                        url = f"https://youtube.com/@{handle}"
                    elif platform == "discord":
                        url = f"https://discord.gg/{handle}"
                    else:
                        continue

                    found[platform] = url
                    break  # Found for this platform

        # Also check for links in footer (more reliable)
        footer = soup.find("footer")
        if footer:
            self._extract_from_links(footer, found)

        return found

    def _extract_from_links(self, element, found: Dict[str, str]):
        """Extract social links from anchor elements."""
        for link in element.find_all("a", href=True):
            href = link["href"].lower()

            for platform in self.SOCIAL_PATTERNS.keys():
                if platform not in found and platform in href:
                    found[platform] = link["href"]
                    break

            # Handle x.com (Twitter rebrand)
            if "twitter" not in found and "x.com/" in href:
                found["twitter"] = link["href"]

    def _validate_links(self, socials: Dict[str, str], session: requests.Session) -> Dict[str, str]:
        """Validate social links with HEAD requests."""
        validated = {}

        for platform, url in socials.items():
            try:
                response = session.head(
                    url,
                    timeout=10,
                    allow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                # Accept 2xx and some 3xx responses
                if response.status_code < 400:
                    validated[platform] = url
                    logger.debug(f"Validated {platform}: {url}")
                else:
                    logger.debug(f"Invalid {platform} link ({response.status_code}): {url}")
            except requests.RequestException as e:
                logger.debug(f"Could not validate {platform}: {e}")
                # Keep it if we can't validate (benefit of the doubt)
                validated[platform] = url

        return validated

    def _calculate_score(self, socials: Dict[str, str]) -> int:
        """Calculate social presence score."""
        if not socials:
            return 2

        score = 3  # Base score for having any social presence

        # Add points for each platform
        for platform in socials:
            if platform in self.TECH_PLATFORMS:
                score += 1.5  # Tech-relevant platforms worth more
            else:
                score += 0.5

        # Bonus for having all tech platforms
        tech_count = sum(1 for p in self.TECH_PLATFORMS if p in socials)
        if tech_count >= 3:
            score += 1

        # Cap score
        return max(1, min(10, round(score)))

    def get_linkedin_url(self, html: str) -> str:
        """Convenience method to get just the LinkedIn URL."""
        found = self._find_social_links(html, BeautifulSoup(html, "lxml"))
        return found.get("linkedin", "")
