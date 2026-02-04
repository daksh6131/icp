"""
Product Hunt scraper for new AI product launches.
Finds recently launched AI products that may have funding.
"""

import re
from datetime import datetime, timedelta
from typing import Optional
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper
from config import config
from utils import get_logger

logger = get_logger(__name__)


class ProductHuntScraper(BaseScraper):
    """Scraper for Product Hunt AI product launches."""

    BASE_URL = "https://www.producthunt.com"

    def __init__(self):
        super().__init__()
        # Update headers for Product Hunt
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get_source_name(self) -> str:
        return "Product Hunt"

    def scrape(self) -> list[dict]:
        """Scrape Product Hunt for AI product launches."""
        all_leads = []

        # Scrape AI-tagged products
        leads = self._scrape_topic("artificial-intelligence")
        all_leads.extend(leads)

        # Also try machine learning topic
        ml_leads = self._scrape_topic("machine-learning")
        all_leads.extend(ml_leads)

        # Try the main AI tools page
        ai_tools = self._scrape_ai_tools()
        all_leads.extend(ai_tools)

        # Deduplicate by company name
        seen = set()
        unique_leads = []
        for lead in all_leads:
            name = lead.get("company_name", "").lower()
            if name and name not in seen:
                seen.add(name)
                unique_leads.append(lead)

        logger.info(f"Found {len(unique_leads)} leads from Product Hunt")
        return unique_leads

    def _scrape_topic(self, topic: str) -> list[dict]:
        """Scrape products from a specific topic."""
        leads = []
        url = f"{self.BASE_URL}/topics/{topic}"

        logger.info(f"Fetching Product Hunt topic: {topic}")
        response = self.get(url)

        if not response:
            return leads

        try:
            soup = BeautifulSoup(response.text, "lxml")

            # Find product cards
            # Product Hunt uses various class patterns
            product_cards = soup.find_all("div", {"data-test": re.compile(r"post", re.I)})

            if not product_cards:
                # Try alternative selectors
                product_cards = soup.find_all("article") or \
                               soup.find_all("div", class_=re.compile(r"product|post|item", re.I))

            for card in product_cards[:30]:
                lead = self._parse_product_card(card)
                if lead:
                    leads.append(lead)

        except Exception as e:
            logger.debug(f"Failed to parse Product Hunt topic {topic}: {e}")

        return leads

    def _scrape_ai_tools(self) -> list[dict]:
        """Scrape the AI tools collection."""
        leads = []

        # Try different AI-related pages
        urls = [
            f"{self.BASE_URL}/topics/artificial-intelligence",
            f"{self.BASE_URL}/topics/ai",
            f"{self.BASE_URL}/search?q=AI",
        ]

        for url in urls:
            logger.info(f"Fetching: {url}")
            response = self.get(url)

            if not response:
                continue

            try:
                soup = BeautifulSoup(response.text, "lxml")

                # Find all links that look like product pages
                product_links = soup.find_all("a", href=re.compile(r"/posts/[a-z0-9\-]+", re.I))

                for link in product_links[:20]:
                    lead = self._parse_product_link(link)
                    if lead:
                        leads.append(lead)

            except Exception as e:
                logger.debug(f"Failed to parse {url}: {e}")

        return leads

    def _parse_product_card(self, card) -> Optional[dict]:
        """Parse a product card element."""
        try:
            # Get product name
            name_elem = card.find("h3") or card.find("h2") or card.find(class_=re.compile(r"name|title", re.I))
            if not name_elem:
                # Try link text
                link = card.find("a")
                name = link.get_text(strip=True) if link else None
            else:
                name = name_elem.get_text(strip=True)

            if not name or len(name) > 100:
                return None

            # Get tagline/description
            tagline_elem = card.find(class_=re.compile(r"tagline|desc|subtitle", re.I))
            tagline = tagline_elem.get_text(strip=True) if tagline_elem else ""

            # Get product link
            link = card.find("a", href=re.compile(r"/posts/", re.I))
            href = link.get("href", "") if link else ""
            if href and not href.startswith("http"):
                href = f"{self.BASE_URL}{href}"

            # Check if AI-related
            text_to_check = f"{name} {tagline}".lower()
            is_ai = any(kw in text_to_check for kw in config.AI_KEYWORDS)

            if not is_ai:
                return None

            # Try to get website
            website = ""
            website_link = card.find("a", href=re.compile(r"^https?://(?!producthunt)", re.I))
            if website_link:
                website = website_link.get("href", "")

            return {
                "company_name": name,
                "website": website,
                "funding_amount": "",
                "funding_date": datetime.now().strftime("%Y-%m-%d"),
                "funding_stage": "",
                "location": "",
                "industry_tags": "AI",
                "founders": "",
                "investors": "",
                "source_url": href,
            }

        except Exception as e:
            logger.debug(f"Failed to parse product card: {e}")
            return None

    def _parse_product_link(self, link) -> Optional[dict]:
        """Parse a product link element."""
        try:
            name = link.get_text(strip=True)
            if not name or len(name) > 100 or len(name) < 2:
                return None

            href = link.get("href", "")
            if href and not href.startswith("http"):
                href = f"{self.BASE_URL}{href}"

            # Check if the name or link suggests AI
            text_to_check = f"{name} {href}".lower()
            is_ai = any(kw in text_to_check for kw in config.AI_KEYWORDS)

            # Be more lenient since we're on AI topic pages
            if not is_ai and "ai" not in href.lower():
                return None

            return {
                "company_name": name,
                "website": "",
                "funding_amount": "",
                "funding_date": "",
                "funding_stage": "",
                "location": "",
                "industry_tags": "AI",
                "founders": "",
                "investors": "",
                "source_url": href,
            }

        except Exception as e:
            logger.debug(f"Failed to parse product link: {e}")
            return None

    def get_product_details(self, product_url: str) -> Optional[dict]:
        """Get detailed information about a specific product."""
        response = self.get(product_url)
        if not response:
            return None

        try:
            soup = BeautifulSoup(response.text, "lxml")

            details = {
                "website": "",
                "makers": "",
            }

            # Find the "Visit" or website link
            visit_link = soup.find("a", text=re.compile(r"visit|website|get", re.I))
            if visit_link:
                details["website"] = visit_link.get("href", "")

            # Find makers/founders
            makers_section = soup.find(class_=re.compile(r"maker|hunter|founder", re.I))
            if makers_section:
                maker_names = makers_section.find_all("a")
                details["makers"] = ", ".join([m.get_text(strip=True) for m in maker_names[:3]])

            return details

        except Exception as e:
            logger.debug(f"Failed to get product details: {e}")
            return None
