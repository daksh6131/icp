"""
Base scraper class with rate limiting and common utilities.
"""

import time
import random
from abc import ABC, abstractmethod
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import config
from utils import get_logger

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self):
        self.session = self._create_session()
        self.last_request_time = 0

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()

        # Configure retries
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set default headers
        session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

        return session

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        delay = config.REQUEST_DELAY_SECONDS + random.uniform(0, 1)

        if elapsed < delay:
            sleep_time = delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a rate-limited GET request."""
        self._rate_limit()

        try:
            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            return None

    @abstractmethod
    def scrape(self) -> list[dict]:
        """
        Scrape data from the source.
        Returns a list of lead dictionaries.
        """
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the name of this data source."""
        pass

    def parse_funding_amount(self, text: str) -> Optional[int]:
        """Parse funding amount from text like '$25M' or '$1.5 million'."""
        if not text:
            return None

        text = text.lower().replace(",", "").replace(" ", "")

        # Extract number
        import re
        match = re.search(r'\$?([\d.]+)\s*(m|million|b|billion|k|thousand)?', text)
        if not match:
            return None

        try:
            amount = float(match.group(1))
            multiplier = match.group(2) or ""

            if multiplier.startswith("b"):
                amount *= 1_000_000_000
            elif multiplier.startswith("m"):
                amount *= 1_000_000
            elif multiplier.startswith("k") or multiplier.startswith("t"):
                amount *= 1_000

            return int(amount)
        except (ValueError, TypeError):
            return None

    def extract_domain(self, url: str) -> str:
        """Extract domain from a URL."""
        url = url.lower().strip()
        for prefix in ["https://", "http://", "www."]:
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url.split("/")[0]

    def validate_lead(self, lead: dict) -> bool:
        """
        Validate a lead before adding to results.
        Returns True if the lead is valid, False if it should be skipped.
        """
        import re

        company_name = lead.get("company_name", "").strip()

        # Must have a company name
        if not company_name:
            logger.debug("Skipping lead: empty company name")
            return False

        # Name must be at least 2 characters
        if len(company_name) < 2:
            logger.debug(f"Skipping lead: name too short '{company_name}'")
            return False

        # Check against known invalid patterns
        invalid_names = {
            "the", "a", "an", "ai", "startup", "company", "here", "there",
            "indian", "chinese", "american", "european", "us", "uk",
            "san", "new", "los", "francisco", "york", "angeles",
            "london", "berlin", "paris", "boston", "seattle", "austin",
            "vibe", "emergent", "funding", "report", "news",
        }

        name_lower = company_name.lower().rstrip("'s")
        if name_lower in invalid_names:
            logger.debug(f"Skipping lead: invalid name '{company_name}'")
            return False

        # Reject location-based patterns
        if re.search(r'^[A-Za-z]+-based$', company_name, re.IGNORECASE):
            logger.debug(f"Skipping lead: looks like location '{company_name}'")
            return False

        # Validate website if provided
        website = lead.get("website", "")
        if website:
            if not website.startswith(("http://", "https://")):
                # Try to fix common issues
                if "." in website:
                    lead["website"] = f"https://{website}"
                else:
                    lead["website"] = ""  # Clear invalid website

        return True
