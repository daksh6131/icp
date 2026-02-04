"""
TechCrunch RSS feed scraper for funding announcements.
"""

import re
from datetime import datetime, timedelta
from typing import Optional
import feedparser
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import config
from utils import get_logger

logger = get_logger(__name__)


class TechCrunchScraper(BaseScraper):
    """Scraper for TechCrunch funding news via RSS."""

    def __init__(self):
        super().__init__()
        self.rss_urls = [
            config.TECHCRUNCH_RSS_URL,
            config.TECHCRUNCH_AI_RSS_URL,
        ]

    def get_source_name(self) -> str:
        return "TechCrunch"

    def scrape(self) -> list[dict]:
        """Scrape TechCrunch RSS feeds for AI funding news."""
        all_leads = []
        seen_urls = set()

        for rss_url in self.rss_urls:
            logger.info(f"Fetching RSS feed: {rss_url}")
            leads = self._parse_rss_feed(rss_url)

            for lead in leads:
                # Deduplicate by source URL
                if lead.get("source_url") not in seen_urls:
                    seen_urls.add(lead.get("source_url"))
                    all_leads.append(lead)

        logger.info(f"Found {len(all_leads)} potential leads from TechCrunch")
        return all_leads

    def _parse_rss_feed(self, rss_url: str) -> list[dict]:
        """Parse an RSS feed and extract funding-related articles."""
        leads = []

        try:
            feed = feedparser.parse(rss_url)

            if feed.bozo:
                logger.warning(f"RSS feed parsing had issues: {feed.bozo_exception}")

            for entry in feed.entries:
                lead = self._parse_entry(entry)
                if lead:
                    leads.append(lead)

        except Exception as e:
            logger.error(f"Failed to parse RSS feed {rss_url}: {e}")

        return leads

    def _parse_entry(self, entry) -> Optional[dict]:
        """Parse a single RSS entry into a lead dict."""
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        published = entry.get("published_parsed")

        # Check if it's a funding article
        if not self._is_funding_article(title, summary):
            return None

        # Check date - only recent articles
        if published:
            pub_date = datetime(*published[:6])
            cutoff = datetime.now() - timedelta(days=config.FUNDING_LOOKBACK_DAYS)
            if pub_date < cutoff:
                return None
            funding_date = pub_date.strftime("%Y-%m-%d")
        else:
            funding_date = ""

        # Extract company name from title
        company_name = self._extract_company_name(title)
        if not company_name:
            return None

        # Extract funding amount
        funding_amount = self._extract_funding_amount(title + " " + summary)

        # Try to get more details from the article page
        article_data = self._fetch_article_details(link)

        lead = {
            "company_name": company_name,
            "website": article_data.get("website", ""),
            "funding_amount": funding_amount or "",
            "funding_date": funding_date,
            "funding_stage": self._extract_funding_stage(title + " " + summary),
            "location": article_data.get("location", ""),
            "industry_tags": "AI" if self._mentions_ai(title + " " + summary) else "",
            "founders": article_data.get("founders", ""),
            "investors": self._extract_investors(summary),
            "source_url": link,
        }

        return lead

    def _is_funding_article(self, title: str, summary: str) -> bool:
        """Check if the article is about funding."""
        text = (title + " " + summary).lower()
        funding_keywords = [
            "raises", "raised", "funding", "series a", "series b", "series c",
            "series d", "seed", "round", "million", "investment", "venture",
            "backed", "secures", "closes", "announces"
        ]
        return any(kw in text for kw in funding_keywords)

    def _mentions_ai(self, text: str) -> bool:
        """Check if the text mentions AI-related topics."""
        text_lower = text.lower()
        return any(kw in text_lower for kw in config.AI_KEYWORDS)

    def _extract_company_name(self, title: str) -> Optional[str]:
        """Extract company name from article title."""
        # Common patterns:
        # "CompanyName raises $X"
        # "CompanyName secures $X"
        # "CompanyName, which does X, raises $X"

        # Try pattern: "Name raises/secures/closes"
        patterns = [
            r'^([A-Z][A-Za-z0-9\.\-]+(?:\s+[A-Z][A-Za-z0-9\.\-]+)?)\s+(?:raises|secures|closes|lands|gets|announces)',
            r'^([A-Z][A-Za-z0-9\.\-]+(?:\.ai|\.io)?)\s*,?\s*(?:a |an |the )?',
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                name = match.group(1).strip()
                # Filter out common false positives
                if name.lower() not in ["the", "a", "an", "this", "here", "how"]:
                    return name

        # Fallback: first capitalized word(s) before common keywords
        words = title.split()
        company_parts = []
        for word in words:
            if word[0].isupper() and word.lower() not in ["raises", "secures", "closes", "series", "the", "a", "an"]:
                company_parts.append(word)
            else:
                break

        if company_parts:
            return " ".join(company_parts).rstrip(",")

        return None

    def _extract_funding_amount(self, text: str) -> str:
        """Extract funding amount from text."""
        # Match patterns like "$25M", "$1.5 million", "$25 million"
        patterns = [
            r'\$(\d+(?:\.\d+)?)\s*(million|m|billion|b)',
            r'\$(\d+(?:\.\d+)?)\s*(?:mm|mn)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                amount = match.group(1)
                unit = match.group(2)
                if unit.startswith("b"):
                    return f"${amount}B"
                else:
                    return f"${amount}M"

        return ""

    def _extract_funding_stage(self, text: str) -> str:
        """Extract funding stage from text."""
        text_lower = text.lower()

        stages = [
            ("series d", "Series D"),
            ("series c", "Series C"),
            ("series b", "Series B"),
            ("series a", "Series A"),
            ("seed", "Seed"),
            ("pre-seed", "Pre-Seed"),
        ]

        for keyword, stage in stages:
            if keyword in text_lower:
                return stage

        return ""

    def _extract_investors(self, text: str) -> str:
        """Extract investor names from text."""
        # Look for patterns like "led by X" or "from X"
        patterns = [
            r'led by ([A-Z][A-Za-z\s&]+?)(?:,|\.|and|with)',
            r'from ([A-Z][A-Za-z\s&]+?)(?:,|\.|and|with)',
        ]

        investors = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            investors.extend([m.strip() for m in matches])

        return ", ".join(investors[:3]) if investors else ""

    def _fetch_article_details(self, url: str) -> dict:
        """Fetch additional details from the article page."""
        details = {
            "website": "",
            "location": "",
            "founders": "",
        }

        response = self.get(url)
        if not response:
            return details

        try:
            soup = BeautifulSoup(response.text, "lxml")

            # Look for company website links in the article
            article = soup.find("article") or soup.find("div", class_="article-content")
            if article:
                links = article.find_all("a", href=True)
                for link in links:
                    href = link.get("href", "")
                    text = link.get_text().lower()
                    # Skip social media and known non-company sites
                    if any(site in href for site in ["twitter", "linkedin", "facebook", "techcrunch", "crunchbase"]):
                        continue
                    if "http" in href and not href.startswith("https://techcrunch"):
                        # Likely a company website
                        details["website"] = href
                        break

        except Exception as e:
            logger.debug(f"Failed to parse article {url}: {e}")

        return details
