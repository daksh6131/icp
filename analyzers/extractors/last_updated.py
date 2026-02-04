"""
Extract last updated date from websites.
"""

import re
from datetime import datetime
from typing import Optional, Tuple
from bs4 import BeautifulSoup

from utils import get_logger

logger = get_logger(__name__)


class LastUpdatedExtractor:
    """Extracts last updated date from website content and headers."""

    def extract(self, response, html: str) -> Tuple[Optional[str], str]:
        """
        Extract last updated date from response and HTML.

        Args:
            response: requests.Response object
            html: HTML content string

        Returns:
            Tuple of (date_string or None, confidence: "High"/"Medium"/"Low")
        """
        # Try methods in order of reliability

        # 1. HTTP Last-Modified header
        last_modified = response.headers.get("Last-Modified") if response else None
        if last_modified:
            date = self._parse_http_date(last_modified)
            if date:
                return date, "High"

        soup = BeautifulSoup(html, "lxml") if html else None
        if not soup:
            return None, "Low"

        # 2. Meta tags
        meta_date = self._extract_meta_date(soup)
        if meta_date:
            return meta_date, "High"

        # 3. JSON-LD structured data
        jsonld_date = self._extract_jsonld_date(soup)
        if jsonld_date:
            return jsonld_date, "High"

        # 4. Schema.org dateModified
        schema_date = self._extract_schema_date(soup)
        if schema_date:
            return schema_date, "Medium"

        # 5. Footer copyright year (low confidence)
        copyright_year = self._extract_copyright_year(soup)
        if copyright_year:
            return f"{copyright_year}-01-01", "Low"

        return None, "Low"

    def _parse_http_date(self, date_str: str) -> Optional[str]:
        """Parse HTTP date format."""
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S GMT",
            "%A, %d-%b-%y %H:%M:%S %Z",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def _extract_meta_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract date from meta tags."""
        meta_names = [
            "last-modified",
            "date",
            "article:modified_time",
            "og:updated_time",
            "article:published_time",
            "og:published_time",
            "dcterms.modified",
            "DC.date.modified",
        ]

        for name in meta_names:
            # Try name attribute
            meta = soup.find("meta", {"name": name})
            if meta and meta.get("content"):
                date = self._parse_date(meta["content"])
                if date:
                    return date

            # Try property attribute (for Open Graph)
            meta = soup.find("meta", {"property": name})
            if meta and meta.get("content"):
                date = self._parse_date(meta["content"])
                if date:
                    return date

        return None

    def _extract_jsonld_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract date from JSON-LD structured data."""
        import json

        scripts = soup.find_all("script", {"type": "application/ld+json"})
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0] if data else {}

                # Check for dateModified or datePublished
                for key in ["dateModified", "datePublished", "dateCreated"]:
                    if key in data:
                        date = self._parse_date(data[key])
                        if date:
                            return date
            except (json.JSONDecodeError, TypeError):
                continue

        return None

    def _extract_schema_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract date from schema.org attributes."""
        # Look for itemprop="dateModified" or similar
        for attr in ["dateModified", "datePublished", "dateCreated"]:
            elem = soup.find(attrs={"itemprop": attr})
            if elem:
                content = elem.get("content") or elem.get("datetime") or elem.text
                if content:
                    date = self._parse_date(content.strip())
                    if date:
                        return date

        return None

    def _extract_copyright_year(self, soup: BeautifulSoup) -> Optional[int]:
        """Extract year from copyright notice in footer."""
        # Look in footer
        footer = soup.find("footer")
        if footer:
            text = footer.get_text()
        else:
            # Fall back to full page
            text = soup.get_text()

        # Look for copyright patterns
        patterns = [
            r'©\s*(\d{4})',
            r'copyright\s*(?:©)?\s*(\d{4})',
            r'\(c\)\s*(\d{4})',
        ]

        current_year = datetime.now().year
        found_years = []

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                year = int(match)
                # Only consider reasonable years
                if 2015 <= year <= current_year:
                    found_years.append(year)

        if found_years:
            return max(found_years)  # Return most recent year

        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse various date formats to YYYY-MM-DD."""
        if not date_str:
            return None

        date_str = date_str.strip()

        # ISO format
        if re.match(r'^\d{4}-\d{2}-\d{2}', date_str):
            return date_str[:10]

        # Try various formats
        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y/%m/%d",
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B %Y",
            "%d %b %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:30], fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None
