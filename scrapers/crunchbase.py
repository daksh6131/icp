"""
Crunchbase scraper for funding data.
Uses web scraping approach - can be upgraded to API for better reliability.
"""

import re
import json
from datetime import datetime, timedelta
from typing import Optional
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import config
from utils import get_logger

logger = get_logger(__name__)


class CrunchbaseScraper(BaseScraper):
    """Scraper for Crunchbase funding data."""

    BASE_URL = "https://www.crunchbase.com"

    def __init__(self):
        super().__init__()
        # Update headers for Crunchbase
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.crunchbase.com/",
        })

    def get_source_name(self) -> str:
        return "Crunchbase"

    def scrape(self) -> list[dict]:
        """
        Scrape Crunchbase for recent AI funding rounds.

        Note: Crunchbase has strong anti-scraping measures.
        This implementation uses their public-facing pages.
        For production use, consider the Crunchbase API ($99/mo).
        """
        all_leads = []

        # Try to scrape from the funding rounds page
        leads = self._scrape_recent_funding()
        all_leads.extend(leads)

        # Also try AI-specific searches
        ai_leads = self._scrape_ai_companies()
        all_leads.extend(ai_leads)

        # Deduplicate by company name
        seen = set()
        unique_leads = []
        for lead in all_leads:
            name = lead.get("company_name", "").lower()
            if name and name not in seen:
                seen.add(name)
                unique_leads.append(lead)

        logger.info(f"Found {len(unique_leads)} unique leads from Crunchbase")
        return unique_leads

    def _scrape_recent_funding(self) -> list[dict]:
        """Scrape recent funding rounds from Crunchbase."""
        leads = []

        # Note: This URL may require authentication or may be blocked
        # Crunchbase actively blocks scraping - this is a best-effort approach
        url = f"{self.BASE_URL}/funding_rounds"

        logger.info(f"Attempting to scrape: {url}")
        response = self.get(url)

        if not response:
            logger.warning("Could not access Crunchbase funding rounds page")
            return self._try_alternative_source()

        # Try to parse the page
        try:
            soup = BeautifulSoup(response.text, "lxml")

            # Look for funding round cards/rows
            # Note: Crunchbase structure changes frequently
            funding_items = soup.find_all("div", class_=re.compile(r"funding|round", re.I))

            for item in funding_items[:20]:  # Limit to avoid over-scraping
                lead = self._parse_funding_item(item)
                if lead:
                    leads.append(lead)

        except Exception as e:
            logger.error(f"Failed to parse Crunchbase page: {e}")

        return leads

    def _scrape_ai_companies(self) -> list[dict]:
        """Scrape AI-tagged companies from Crunchbase."""
        leads = []

        # Try the discover/funding endpoint with AI filter
        url = f"{self.BASE_URL}/discover/funding_rounds/artificial-intelligence"

        logger.info(f"Attempting AI-specific scrape: {url}")
        response = self.get(url)

        if not response:
            return leads

        try:
            soup = BeautifulSoup(response.text, "lxml")

            # Parse any company/funding data found
            # This is fragile and depends on Crunchbase's HTML structure
            script_tags = soup.find_all("script", type="application/ld+json")
            for script in script_tags:
                try:
                    data = json.loads(script.string)
                    lead = self._parse_json_ld(data)
                    if lead:
                        leads.append(lead)
                except (json.JSONDecodeError, TypeError):
                    continue

        except Exception as e:
            logger.debug(f"Failed to parse AI companies page: {e}")

        return leads

    def _try_alternative_source(self) -> list[dict]:
        """
        Fallback to alternative data sources when Crunchbase is blocked.
        Uses Google News search for funding announcements as a proxy.
        """
        leads = []
        logger.info("Trying alternative sources for funding data...")

        # This is a placeholder - in production you might:
        # 1. Use Crunchbase API (recommended)
        # 2. Use Google News RSS for funding announcements
        # 3. Use other startup databases like AngelList, PitchBook

        # For now, we'll rely on TechCrunch as the primary source
        # and note that Crunchbase needs API access for reliability

        logger.warning(
            "Crunchbase web scraping blocked. For reliable data, "
            "consider using Crunchbase API ($99/month)."
        )

        return leads

    def _parse_funding_item(self, item) -> Optional[dict]:
        """Parse a funding item element from Crunchbase HTML."""
        try:
            # Extract company name
            company_link = item.find("a", href=re.compile(r"/organization/"))
            if not company_link:
                return None

            company_name = company_link.get_text(strip=True)
            company_url = f"{self.BASE_URL}{company_link.get('href', '')}"

            # Extract funding amount
            amount_elem = item.find(text=re.compile(r'\$\d'))
            funding_amount = amount_elem.strip() if amount_elem else ""

            # Extract date
            date_elem = item.find(class_=re.compile(r"date|time", re.I))
            funding_date = date_elem.get_text(strip=True) if date_elem else ""

            # Extract stage
            stage_elem = item.find(text=re.compile(r"Series|Seed|Pre-Seed", re.I))
            funding_stage = stage_elem.strip() if stage_elem else ""

            return {
                "company_name": company_name,
                "website": "",  # Would need to visit company page
                "funding_amount": funding_amount,
                "funding_date": funding_date,
                "funding_stage": funding_stage,
                "location": "",
                "industry_tags": "AI",
                "founders": "",
                "investors": "",
                "source_url": company_url,
            }

        except Exception as e:
            logger.debug(f"Failed to parse funding item: {e}")
            return None

    def _parse_json_ld(self, data: dict) -> Optional[dict]:
        """Parse JSON-LD structured data from Crunchbase."""
        if not isinstance(data, dict):
            return None

        # Look for Organization or FundingEvent type
        item_type = data.get("@type", "")

        if "Organization" in item_type:
            return {
                "company_name": data.get("name", ""),
                "website": data.get("url", ""),
                "funding_amount": "",
                "funding_date": "",
                "funding_stage": "",
                "location": data.get("address", {}).get("addressLocality", ""),
                "industry_tags": "AI",
                "founders": "",
                "investors": "",
                "source_url": data.get("sameAs", ""),
            }

        return None

    def get_company_details(self, company_slug: str) -> Optional[dict]:
        """
        Get detailed information about a specific company.
        Useful for enriching leads from other sources.
        """
        url = f"{self.BASE_URL}/organization/{company_slug}"

        response = self.get(url)
        if not response:
            return None

        try:
            soup = BeautifulSoup(response.text, "lxml")

            details = {
                "company_name": "",
                "website": "",
                "location": "",
                "founders": "",
                "funding_amount": "",
                "investors": "",
            }

            # Extract from structured data if available
            script = soup.find("script", type="application/ld+json")
            if script:
                try:
                    data = json.loads(script.string)
                    details.update({
                        "company_name": data.get("name", ""),
                        "website": data.get("url", ""),
                        "location": data.get("address", {}).get("addressLocality", ""),
                    })
                except (json.JSONDecodeError, TypeError):
                    pass

            return details

        except Exception as e:
            logger.error(f"Failed to get company details for {company_slug}: {e}")
            return None
