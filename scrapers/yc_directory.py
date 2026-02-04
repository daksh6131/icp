"""
Y Combinator directory scraper for AI startups.
Uses YC's Algolia API to fetch company data directly.
"""

import json
from typing import Optional
import requests

from .base_scraper import BaseScraper
from config import config
from utils import get_logger

logger = get_logger(__name__)


class YCDirectoryScraper(BaseScraper):
    """Scraper for Y Combinator's company directory via Algolia API."""

    # YC's Algolia credentials (public, used by their website)
    ALGOLIA_APP_ID = "45BWZJ1SGC"
    ALGOLIA_API_KEY = "MjBjYjRiMzY0NzdhZWY0NjExY2NhZjYxMGIxYjc2MTAwNWFkNTkwNTc4NjgxYjU0YzFhYTY2ZGQ5OGY5NDMxZnJlc3RyaWN0SW5kaWNlcz0lNUIlMjJZQ0NvbXBhbnlfcHJvZHVjdGlvbiUyMiUyQyUyMllDQ29tcGFueV9CeV9MYXVuY2hfRGF0ZV9wcm9kdWN0aW9uJTIyJTVEJnRhZ0ZpbHRlcnM9JTVCJTIyeWNkY19wdWJsaWMlMjIlNUQmYW5hbHl0aWNzVGFncz0lNUIlMjJ5Y2RjJTIyJTVE"
    ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"

    # AI-related tags to search for
    AI_TAGS = [
        "Artificial Intelligence",
        "Machine Learning",
        "Generative AI",
        "AI",
        "Deep Learning",
        "Computer Vision",
        "NLP",
        "LLM",
    ]

    def __init__(self):
        super().__init__()
        # Set up Algolia headers (must include Origin/Referer for CORS)
        self.algolia_headers = {
            "x-algolia-api-key": self.ALGOLIA_API_KEY,
            "x-algolia-application-id": self.ALGOLIA_APP_ID,
            "Content-Type": "application/json",
            "Origin": "https://www.ycombinator.com",
            "Referer": "https://www.ycombinator.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

    def get_source_name(self) -> str:
        return "Y Combinator"

    def scrape(self) -> list[dict]:
        """Scrape YC directory for AI companies using Algolia API."""
        all_companies = []
        seen_slugs = set()

        # Search for each AI-related tag
        for tag in self.AI_TAGS:
            logger.info(f"Fetching YC companies with tag: {tag}")
            companies = self._search_by_tag(tag)

            for company in companies:
                slug = company.get("slug", "")
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    lead = self._convert_to_lead(company)
                    if lead:
                        all_companies.append(lead)

        # Also do a general AI search
        logger.info("Fetching YC companies with AI keyword search")
        ai_search = self._search_by_query("AI artificial intelligence machine learning")
        for company in ai_search:
            slug = company.get("slug", "")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                lead = self._convert_to_lead(company)
                if lead:
                    all_companies.append(lead)

        logger.info(f"Found {len(all_companies)} AI companies from Y Combinator")
        return all_companies

    def _search_by_tag(self, tag: str, hits_per_page: int = 1000) -> list[dict]:
        """Search YC companies by tag using Algolia."""
        try:
            payload = {
                "requests": [
                    {
                        "indexName": "YCCompany_production",
                        "params": f"facetFilters=%5B%5B%22tags%3A{tag.replace(' ', '%20')}%22%5D%5D&hitsPerPage={hits_per_page}&page=0"
                    }
                ]
            }

            response = requests.post(
                self.ALGOLIA_URL,
                headers=self.algolia_headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])
            if results:
                hits = results[0].get("hits", [])
                logger.info(f"  Tag '{tag}': {len(hits)} companies")
                return hits
            return []

        except Exception as e:
            logger.error(f"Failed to search YC for tag '{tag}': {e}")
            return []

    def _search_by_query(self, query: str, hits_per_page: int = 500) -> list[dict]:
        """Search YC companies by text query using Algolia."""
        try:
            payload = {
                "requests": [
                    {
                        "indexName": "YCCompany_production",
                        "params": f"query={query.replace(' ', '%20')}&hitsPerPage={hits_per_page}&page=0"
                    }
                ]
            }

            response = requests.post(
                self.ALGOLIA_URL,
                headers=self.algolia_headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [])
            if results:
                hits = results[0].get("hits", [])
                logger.info(f"  Query '{query}': {len(hits)} companies")
                return hits
            return []

        except Exception as e:
            logger.error(f"Failed to search YC for query '{query}': {e}")
            return []

    def _convert_to_lead(self, company: dict) -> Optional[dict]:
        """Convert Algolia company data to lead format."""
        try:
            name = company.get("name", "")
            if not name:
                return None

            # Get website
            website = company.get("website", "") or company.get("url", "")

            # Get location
            locations = company.get("regions", []) or []
            location = ", ".join(locations[:2]) if locations else ""

            # If no region, try city/country
            if not location:
                city = company.get("city", "")
                country = company.get("country", "")
                if city or country:
                    location = f"{city}, {country}".strip(", ")

            # Get batch info (e.g., "W24", "S23")
            batch = company.get("batch", "")

            # Get tags
            tags = company.get("tags", []) or []
            industry_tags = ", ".join(tags[:5]) if tags else "AI"

            # Get team size for funding estimate
            team_size = company.get("team_size", 0) or 0

            # Get one-liner description
            one_liner = company.get("one_liner", "") or company.get("long_description", "")

            # Get founders
            founders_list = company.get("founders", []) or []
            founders = ", ".join([f.get("full_name", "") for f in founders_list[:3] if f.get("full_name")])

            # Construct YC profile URL
            slug = company.get("slug", "")
            source_url = f"https://www.ycombinator.com/companies/{slug}" if slug else ""

            return {
                "company_name": name,
                "website": website,
                "funding_amount": "",  # YC doesn't expose this directly
                "funding_date": batch,  # Use batch as proxy for funding date
                "funding_stage": f"YC {batch}" if batch else "YC",
                "location": location,
                "industry_tags": industry_tags,
                "founders": founders,
                "investors": "Y Combinator",
                "source_url": source_url,
            }

        except Exception as e:
            logger.debug(f"Failed to convert company: {e}")
            return None

    def get_all_companies(self, hits_per_page: int = 1000, max_pages: int = 10) -> list[dict]:
        """Get ALL YC companies (not just AI). Use with caution - returns thousands."""
        all_companies = []

        for page in range(max_pages):
            logger.info(f"Fetching YC companies page {page + 1}")
            try:
                payload = {
                    "requests": [
                        {
                            "indexName": "YCCompany_production",
                            "params": f"hitsPerPage={hits_per_page}&page={page}"
                        }
                    ]
                }

                response = requests.post(
                    self.ALGOLIA_URL,
                    headers=self.algolia_headers,
                    json=payload,
                    timeout=30
                )
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])
                if results:
                    hits = results[0].get("hits", [])
                    if not hits:
                        break  # No more results
                    all_companies.extend(hits)
                    logger.info(f"  Page {page + 1}: {len(hits)} companies (total: {len(all_companies)})")
                else:
                    break

            except Exception as e:
                logger.error(f"Failed to fetch page {page}: {e}")
                break

        return all_companies
