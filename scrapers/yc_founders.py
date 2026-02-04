"""
Y Combinator Founders Directory scraper.
Uses Algolia search API to fetch founder data.
"""

import json
from typing import Optional
import requests

from .base_scraper import BaseScraper
from utils import get_logger

logger = get_logger(__name__)


class YCFoundersScraper(BaseScraper):
    """Scraper for YC Founders Directory using Algolia API."""

    # Algolia configuration (from YC website)
    ALGOLIA_APP_ID = "45BWZJ1SGC"
    # API key passed as URL parameter (base64 encoded with restrictions)
    ALGOLIA_API_KEY = "YzI1YTQ1MDg2YmVkOTI1N2I5YzQ3MTAwMjM5MzhiYTQ2Zjk0N2JkNTIwNWJhZTE1YTY5ZTI0ZjY0ODczY2U3NXJlc3RyaWN0SW5kaWNlcz1ZQ1VzZXJzX3Byb2R1Y3Rpb24mdGFnRmlsdGVycz0lNUIlMjJ5Y2RjX3B1YmxpYyUyMiU1RCZhbmFseXRpY3NUYWdzPSU1QiUyMnljZGMlMjIlNUQ="
    ALGOLIA_INDEX = "YCUsers_production"

    def __init__(self):
        super().__init__()

    def get_source_name(self) -> str:
        return "YC Founders"

    def scrape(self, industry_filter: str = None) -> list[dict]:
        """
        Scrape all founders from YC directory.

        Args:
            industry_filter: Optional filter like "AI" to only get AI company founders
        """
        logger.info("Starting YC Founders scrape via Algolia API...")

        # First, get all available batches
        batches = self._get_all_batches()
        logger.info(f"Found {len(batches)} YC batches to scrape")

        all_founders = []
        seen_ids = set()  # Dedupe by objectID

        for batch in batches:
            batch_founders = self._scrape_batch(batch, industry_filter)

            # Dedupe
            for f in batch_founders:
                obj_id = f.get("_object_id")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    all_founders.append(f)

            logger.info(f"  Batch {batch}: {len(batch_founders)} founders (total unique: {len(all_founders)})")

        logger.info(f"Total founders scraped: {len(all_founders)}")
        return all_founders

    def _get_all_batches(self) -> list[str]:
        """Get all YC batch names."""
        url = f"https://{self.ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"

        params = {
            "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser; JS Helper (3.16.1)",
            "x-algolia-application-id": self.ALGOLIA_APP_ID,
            "x-algolia-api-key": self.ALGOLIA_API_KEY,
        }

        payload = {
            "requests": [{
                "indexName": self.ALGOLIA_INDEX,
                "params": "query=&hitsPerPage=0&facets=%5B%22batches%22%5D"
            }]
        }

        headers = {
            "Content-Type": "application/json",
            "Origin": "https://www.ycombinator.com",
            "Referer": "https://www.ycombinator.com/",
        }

        try:
            response = requests.post(url, params=params, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [{}])[0]
            facets = results.get("facets", {})
            batches = list(facets.get("batches", {}).keys())
            return sorted(batches, reverse=True)  # Newest first
        except Exception as e:
            logger.error(f"Failed to get batches: {e}")
            return []

    def _scrape_batch(self, batch: str, industry_filter: str = None) -> list[dict]:
        """Scrape all founders from a specific YC batch."""
        all_founders = []
        page = 0
        hits_per_page = 1000

        while True:
            founders, total = self._fetch_page(page, hits_per_page, industry_filter, batch_filter=batch)

            if not founders:
                break

            all_founders.extend(founders)

            if len(founders) < hits_per_page:
                break

            page += 1
            if page > 10:  # Safety
                break

        return all_founders

    def _fetch_page(self, page: int, hits_per_page: int, industry_filter: str = None, batch_filter: str = None) -> tuple[list[dict], int]:
        """Fetch a single page of founders from Algolia."""
        url = f"https://{self.ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"

        params = {
            "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser; JS Helper (3.16.1)",
            "x-algolia-application-id": self.ALGOLIA_APP_ID,
            "x-algolia-api-key": self.ALGOLIA_API_KEY,
        }

        # Build query params
        query_params = f"query=&hitsPerPage={hits_per_page}&page={page}"

        # Build facet filters
        filters = []
        if industry_filter:
            filters.append(f"%22yc_industries%3A{industry_filter}%22")
        if batch_filter:
            filters.append(f"%22batches%3A{batch_filter}%22")

        if filters:
            query_params += f"&facetFilters=%5B{','.join(filters)}%5D"

        payload = {
            "requests": [
                {
                    "indexName": self.ALGOLIA_INDEX,
                    "params": query_params
                }
            ]
        }

        headers = {
            "Content-Type": "application/json",
            "Origin": "https://www.ycombinator.com",
            "Referer": "https://www.ycombinator.com/",
        }

        try:
            response = requests.post(url, params=params, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            results = data.get("results", [{}])[0]
            hits = results.get("hits", [])
            total = results.get("nbHits", 0)

            founders = [self._parse_founder(hit) for hit in hits]
            return founders, total

        except requests.RequestException as e:
            logger.error(f"Failed to fetch founders page {page}: {e}")
            return [], 0

    def _parse_founder(self, hit: dict) -> dict:
        """Parse an Algolia hit into a founder dict."""
        # Build full name
        first_name = hit.get("first_name", "")
        last_name = hit.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()

        # Current company info
        current_company = hit.get("current_company", "")
        current_title = hit.get("current_title", "")
        company_slug = hit.get("company_slug", "")
        top_company = hit.get("top_company", "")

        # Use top_company if current_company is empty
        company_name = current_company or top_company or ""

        # Location
        location = hit.get("current_region", "")

        # Industries (can be nested lists)
        industries = hit.get("yc_industries", [])
        if industries and isinstance(industries[0], list):
            industries = [item for sublist in industries for item in sublist]
        parent_industries = hit.get("yc_parent_industries", [])
        if parent_industries and isinstance(parent_industries[0], list):
            parent_industries = [item for sublist in parent_industries for item in sublist]

        # Batches
        batches = hit.get("batches", [])
        batch = batches[0] if batches else ""

        # URL slug for profile
        url_slug = hit.get("url_slug", "")
        profile_url = f"https://www.ycombinator.com/person/{url_slug}" if url_slug else ""

        # All companies text (shows previous companies)
        all_companies = hit.get("all_companies_text", "")

        return {
            "_object_id": hit.get("objectID", ""),
            "founder_name": full_name,
            "founder_title": current_title,
            "founder_profile_url": profile_url,
            "company_name": company_name,
            "company_slug": company_slug,
            "company_url": f"https://www.ycombinator.com/companies/{company_slug}" if company_slug else "",
            "batch": batch,
            "location": location,
            "industries": ", ".join(industries) if industries else "",
            "parent_industries": ", ".join(parent_industries) if parent_industries else "",
            "all_companies": all_companies,
            "source": "YC Founders Directory",
        }


def main():
    """Test the scraper."""
    scraper = YCFoundersScraper()

    # Test with AI filter
    print("Fetching AI company founders...")
    founders = scraper.scrape(industry_filter="Artificial Intelligence")

    print(f"\nTotal AI founders: {len(founders)}")

    # Show sample
    print("\nSample founders:")
    for founder in founders[:15]:
        print(f"  {founder['founder_name']} - {founder['founder_title']} at {founder['company_name']} ({founder['batch']})")
        print(f"    Industries: {founder['industries']}")
        if founder['founder_profile_url']:
            print(f"    Profile: {founder['founder_profile_url']}")
        print()


if __name__ == "__main__":
    main()
