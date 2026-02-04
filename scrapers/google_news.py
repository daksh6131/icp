"""
Google News RSS scraper for AI startup funding announcements.
Uses Google News RSS feeds to find recent funding news.
"""

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus
import feedparser

from .base_scraper import BaseScraper
from config import config
from utils import get_logger

logger = get_logger(__name__)


class GoogleNewsScraper(BaseScraper):
    """Scraper for Google News funding announcements via RSS."""

    # Google News RSS feed URL template
    RSS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    # Comprehensive list of words that are NOT company names
    INVALID_COMPANY_NAMES = {
        # Common words
        "the", "a", "an", "this", "that", "these", "those", "here", "there",
        "how", "why", "what", "when", "where", "who", "which",

        # Generic business terms
        "ai", "startup", "startups", "company", "companies", "firm", "firms",
        "business", "venture", "ventures", "enterprise", "corp", "inc",
        "funding", "investment", "investors", "capital", "fund", "funds",

        # Nationalities and regions (common false positives)
        "indian", "chinese", "american", "european", "asian", "african",
        "british", "german", "french", "japanese", "korean", "israeli",
        "us", "uk", "eu",

        # Cities and locations (major false positive source)
        "san", "new", "los", "silicon", "valley", "bay", "area",
        "francisco", "york", "angeles", "boston", "seattle", "austin",
        "london", "berlin", "paris", "tokyo", "beijing", "mumbai",
        "amsterdam", "stockholm", "singapore", "toronto", "chicago",
        "denver", "miami", "atlanta", "dallas", "phoenix", "portland",
        "tel", "aviv",

        # Location-based patterns
        "sf-based", "ny-based", "uk-based", "us-based", "la-based",
        "london-based", "berlin-based", "hamburg-based", "boston-based",

        # People names / common prefixes
        "musk", "musk's", "bezos", "bezos's", "zuckerberg", "altman",
        "andreessen", "horowitz", "thiel", "pichai", "nadella", "cook",

        # News/article words
        "report", "reports", "news", "update", "updates", "latest",
        "breaking", "exclusive", "analysis", "opinion", "review",
        "watch", "alert", "today", "now", "just",

        # Action/descriptive words that appear before amounts
        "makes", "says", "claims", "shows", "reveals", "announces",
        "hits", "reaches", "targets", "sees", "gets", "lands",

        # Common headline starters
        "why", "how", "top", "best", "biggest", "largest", "major",
        "another", "more", "most", "some", "many", "few", "several",

        # Industry terms
        "tech", "technology", "fintech", "biotech", "healthtech",
        "edtech", "proptech", "insurtech", "regtech", "agtech",
        "deeptech", "cleantech", "medtech", "martech", "adtech",

        # Specific false positives from data
        "vibe", "emergent", "humans&", "human-centric", "s&p",
        "converge", "bio", "superorganism", "ivo",

        # Generic descriptors
        "global", "local", "regional", "national", "international",
        "leading", "emerging", "growing", "booming", "surging",

        # Time-related
        "year", "month", "week", "day", "quarter", "annual",
        "2024", "2025", "2026",
    }

    def __init__(self):
        super().__init__()

    def get_source_name(self) -> str:
        return "Google News"

    def scrape(self) -> list[dict]:
        """Scrape Google News for AI funding announcements."""
        all_leads = []
        seen_urls = set()

        # Search queries for funding news
        queries = [
            "AI startup raises funding",
            "artificial intelligence series A",
            "machine learning startup funding",
            "AI company raises million",
            "generative AI funding round",
            "LLM startup funding",
            "AI startup seed round",
        ]

        for query in queries:
            logger.info(f"Searching Google News: {query}")
            leads = self._search_news(query)

            for lead in leads:
                url = lead.get("source_url", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_leads.append(lead)

        logger.info(f"Found {len(all_leads)} leads from Google News")
        return all_leads

    def _search_news(self, query: str) -> list[dict]:
        """Search Google News RSS for a specific query."""
        leads = []

        url = self.RSS_TEMPLATE.format(query=quote_plus(query))

        try:
            # feedparser handles the request itself
            feed = feedparser.parse(url)

            if feed.bozo:
                logger.debug(f"RSS feed parsing issue: {feed.bozo_exception}")

            for entry in feed.entries[:15]:  # Limit per query
                lead = self._parse_news_entry(entry)
                if lead:
                    leads.append(lead)

        except Exception as e:
            logger.error(f"Failed to fetch Google News for '{query}': {e}")

        return leads

    def _parse_news_entry(self, entry) -> Optional[dict]:
        """Parse a Google News RSS entry."""
        try:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            published = entry.get("published_parsed")

            # Check if it's actually about funding
            if not self._is_funding_news(title, summary):
                return None

            # Check date
            if published:
                pub_date = datetime(*published[:6])
                cutoff = datetime.now() - timedelta(days=config.FUNDING_LOOKBACK_DAYS)
                if pub_date < cutoff:
                    return None
                funding_date = pub_date.strftime("%Y-%m-%d")
            else:
                funding_date = ""

            # Extract company name
            company_name = self._extract_company_name(title)
            if not company_name:
                return None

            # Extract funding amount
            funding_amount = self._extract_funding_amount(title + " " + summary)

            # Extract funding stage
            funding_stage = self._extract_funding_stage(title + " " + summary)

            # Check if it's AI-related
            text = f"{title} {summary}".lower()
            is_ai = any(kw in text for kw in config.AI_KEYWORDS)

            if not is_ai:
                return None

            return {
                "company_name": company_name,
                "website": "",
                "funding_amount": funding_amount,
                "funding_date": funding_date,
                "funding_stage": funding_stage,
                "location": self._extract_location(title + " " + summary),
                "industry_tags": "AI",
                "founders": "",
                "investors": self._extract_investors(summary),
                "source_url": link,
            }

        except Exception as e:
            logger.debug(f"Failed to parse news entry: {e}")
            return None

    def _is_funding_news(self, title: str, summary: str) -> bool:
        """Check if the news is about funding."""
        text = f"{title} {summary}".lower()

        funding_keywords = [
            "raises", "raised", "funding", "series a", "series b", "series c",
            "seed", "round", "million", "billion", "investment", "venture",
            "backed", "secures", "closes", "announces funding", "led by"
        ]

        # Must have funding-related keyword
        has_funding = any(kw in text for kw in funding_keywords)

        # Filter out noise
        noise_keywords = ["layoff", "lawsuit", "down round", "bankruptcy", "shuts down"]
        has_noise = any(kw in text for kw in noise_keywords)

        return has_funding and not has_noise

    def _extract_company_name(self, title: str) -> Optional[str]:
        """Extract company name from news title with strict validation."""

        # Best pattern: Look for quoted company names first
        # e.g., "Anthropic" raises $100M
        quoted_match = re.search(r'"([A-Z][a-zA-Z0-9]+)"', title)
        if quoted_match:
            name = quoted_match.group(1).strip()
            if self._is_valid_company_name(name):
                return name

        # Pattern: "CompanyName, a/the startup, raises $X"
        # This is highly reliable because the company name comes first
        comma_match = re.search(
            r'^([A-Z][a-zA-Z0-9]+(?:\.[Aa][Ii]|\.[Ii][Oo])?)\s*,\s*(?:a|the|an|which)\s+',
            title
        )
        if comma_match:
            name = comma_match.group(1).strip()
            if self._is_valid_company_name(name):
                return name

        # Pattern: "AI startup CompanyName raises"
        # Look for company name after descriptor
        descriptor_match = re.search(
            r'(?:AI startup|AI company|startup|fintech|healthtech|biotech)\s+([A-Z][a-zA-Z0-9]+(?:\.[Aa][Ii]|\.[Ii][Oo])?)\s+(?:raises|secures|closes|lands|gets|announces)',
            title
        )
        if descriptor_match:
            name = descriptor_match.group(1).strip()
            if self._is_valid_company_name(name):
                return name

        # Pattern: Look for domain-style names (e.g., "Anthropic.ai", "Scale.ai")
        domain_match = re.search(
            r'([A-Z][a-z]+(?:\.[Aa][Ii]|\.[Ii][Oo]))\s+(?:raises|secures|closes|lands)',
            title
        )
        if domain_match:
            name = domain_match.group(1).strip()
            if self._is_valid_company_name(name):
                return name

        # Pattern: CamelCase names (e.g., "OpenAI", "DeepMind")
        camel_match = re.search(
            r'\b([A-Z][a-z]+[A-Z][a-zA-Z0-9]*)\s+(?:raises|secures|closes)',
            title
        )
        if camel_match:
            name = camel_match.group(1).strip()
            if self._is_valid_company_name(name):
                return name

        # Last resort: Simple pattern but with strict validation
        # Only if the name is 4+ characters and clearly a single proper noun
        simple_match = re.search(
            r'^([A-Z][a-z]{3,})\s+(?:raises|secures|closes|lands)\s+\$\d+',
            title
        )
        if simple_match:
            name = simple_match.group(1).strip()
            # Extra strict validation for simple matches
            if self._is_valid_company_name(name) and len(name) >= 5:
                return name

        return None

    def _is_valid_company_name(self, name: str) -> bool:
        """Check if a name looks like a valid company name."""
        if not name or len(name) < 3:
            return False

        name_lower = name.lower().rstrip("'s").rstrip("'")

        # Check against comprehensive invalid names list
        if name_lower in self.INVALID_COMPANY_NAMES:
            return False

        # Check if any word in the name is invalid (for multi-word extractions)
        words = name_lower.split()
        if any(word in self.INVALID_COMPANY_NAMES for word in words):
            return False

        # Must start with capital letter
        if not name[0].isupper():
            return False

        # Should be reasonable length (3-25 chars for company names)
        if len(name) > 25 or len(name) < 3:
            return False

        # Should not be all caps unless very short (like "AI" which is filtered anyway)
        if name.isupper() and len(name) > 2:
            return False

        # Reject if it looks like a location pattern
        if re.search(r'-based$', name, re.IGNORECASE):
            return False

        # Reject common name patterns that aren't companies
        if name.endswith("'s"):
            return False

        return True

    def _extract_funding_amount(self, text: str) -> str:
        """Extract funding amount from text."""
        patterns = [
            r'\$(\d+(?:\.\d+)?)\s*(billion|b)',
            r'\$(\d+(?:\.\d+)?)\s*(million|m)',
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
            ("series e", "Series E"),
            ("series d", "Series D"),
            ("series c", "Series C"),
            ("series b", "Series B"),
            ("series a", "Series A"),
            ("seed round", "Seed"),
            ("seed funding", "Seed"),
            ("pre-seed", "Pre-Seed"),
        ]

        for keyword, stage in stages:
            if keyword in text_lower:
                return stage

        return ""

    def _extract_location(self, text: str) -> str:
        """Extract location from text."""
        locations = {
            "san francisco": "San Francisco",
            "sf-based": "San Francisco",
            "new york": "New York",
            "nyc": "New York",
            "london": "London",
            "uk-based": "London",
            "berlin": "Berlin",
            "paris": "Paris",
            "tel aviv": "Tel Aviv",
            "boston": "Boston",
            "seattle": "Seattle",
            "austin": "Austin",
        }

        text_lower = text.lower()
        for keyword, location in locations.items():
            if keyword in text_lower:
                return location

        return ""

    def _extract_investors(self, text: str) -> str:
        """Extract investor names from text."""
        patterns = [
            r'led by ([A-Z][A-Za-z\s&]+?)(?:,|\.|and|with|$)',
            r'from ([A-Z][A-Za-z\s&]+?)(?:,|\.|and|with|$)',
            r'backed by ([A-Z][A-Za-z\s&]+?)(?:,|\.|and|with|$)',
        ]

        investors = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                investor = match.strip()
                if investor and len(investor) > 2 and len(investor) < 50:
                    investors.append(investor)

        return ", ".join(investors[:3]) if investors else ""
