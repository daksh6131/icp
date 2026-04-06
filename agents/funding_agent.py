"""
Funding News Agent — scrapes latest funding news and adds companies
directly to the CRM database with ICP scoring.

Usage:
    from agents import FundingAgent
    agent = FundingAgent()
    results = agent.run()
"""

import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scrapers import TechCrunchScraper, GoogleNewsScraper, CrunchbaseScraper, YCDirectoryScraper, ProductHuntScraper
from processors import ICPFilter
from crm.models import Lead, Activity, get_db
from utils import get_logger

logger = get_logger("funding_agent")

# Scrapers available for funding news
SCRAPER_REGISTRY = {
    "techcrunch": TechCrunchScraper,
    "google_news": GoogleNewsScraper,
    "crunchbase": CrunchbaseScraper,
    "yc_directory": YCDirectoryScraper,
    "producthunt": ProductHuntScraper,
}

# Default sources (most reliable for funding news)
DEFAULT_SOURCES = ["techcrunch", "google_news"]


class FundingAgent:
    """Agent that scrapes funding news and imports leads into the CRM."""

    def __init__(self, sources: list[str] = None, min_icp_score: int = 0):
        """
        Args:
            sources: List of scraper names to use. Defaults to techcrunch + google_news.
                     Use 'all' or None with all=True for all scrapers.
            min_icp_score: Minimum ICP score to import (0 = import all that pass filter).
        """
        self.sources = sources or DEFAULT_SOURCES
        self.min_icp_score = min_icp_score
        self.icp_filter = ICPFilter()

    def run(self) -> dict:
        """Run the full scraping → filtering → import pipeline.

        Returns:
            dict with keys: scraped, filtered, imported, skipped, errors, leads
        """
        results = {
            "scraped": 0,
            "filtered": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0,
            "leads": [],  # newly imported lead summaries
            "started_at": datetime.now().isoformat(),
        }

        logger.info("=" * 50)
        logger.info(f"Funding Agent started at {datetime.now()}")
        logger.info(f"Sources: {', '.join(self.sources)}")
        logger.info("=" * 50)

        # Step 1: Scrape leads from all selected sources
        all_leads = self._scrape_all_sources()
        results["scraped"] = len(all_leads)
        logger.info(f"Total raw leads scraped: {len(all_leads)}")

        if not all_leads:
            logger.info("No leads found. Agent complete.")
            results["finished_at"] = datetime.now().isoformat()
            return results

        # Step 2: Filter by ICP criteria
        logger.info("Applying ICP filter...")
        filtered_leads = self.icp_filter.filter_leads(all_leads)
        results["filtered"] = len(filtered_leads)
        logger.info(f"Leads matching ICP: {len(filtered_leads)}")

        # Step 3: Tag and score leads
        logger.info("Scoring leads...")
        tagged_leads = self.icp_filter.tag_and_filter_leads(
            filtered_leads, min_score=self.min_icp_score
        )

        # Step 4: Import into CRM
        logger.info("Importing into CRM...")
        for lead_data in tagged_leads:
            try:
                imported = self._import_lead(lead_data)
                if imported:
                    results["imported"] += 1
                    results["leads"].append({
                        "company_name": lead_data.get("company_name"),
                        "funding_amount": lead_data.get("funding_amount"),
                        "icp_score": lead_data.get("icp_score"),
                        "icp_tag": lead_data.get("icp_tag"),
                        "source": lead_data.get("source", ""),
                    })
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(f"Error importing {lead_data.get('company_name', '?')}: {e}")
                results["errors"] += 1

        results["finished_at"] = datetime.now().isoformat()

        # Summary
        logger.info("=" * 50)
        logger.info("FUNDING AGENT COMPLETE")
        logger.info(f"  Scraped: {results['scraped']}")
        logger.info(f"  Passed ICP filter: {results['filtered']}")
        logger.info(f"  Imported: {results['imported']}")
        logger.info(f"  Skipped (duplicates): {results['skipped']}")
        logger.info(f"  Errors: {results['errors']}")
        logger.info("=" * 50)

        return results

    def _scrape_all_sources(self) -> list[dict]:
        """Run all configured scrapers and collect leads."""
        all_leads = []
        seen_urls = set()

        for source_name in self.sources:
            scraper_cls = SCRAPER_REGISTRY.get(source_name)
            if not scraper_cls:
                logger.warning(f"Unknown source: {source_name}")
                continue

            logger.info(f"--- Scraping {source_name} ---")
            try:
                scraper = scraper_cls()
                leads = scraper.scrape()
                logger.info(f"{source_name}: found {len(leads)} leads")

                # Deduplicate by source URL within this run
                for lead in leads:
                    url = lead.get("source_url", "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)

                    # Tag with source name
                    lead["source"] = scraper.get_source_name()
                    all_leads.append(lead)

            except Exception as e:
                logger.error(f"{source_name} scraper failed: {e}")

        return all_leads

    def _import_lead(self, lead_data: dict) -> bool:
        """Import a single lead into the CRM. Returns True if imported, False if skipped."""
        company_name = lead_data.get("company_name", "").strip()
        website = lead_data.get("website", "").strip()

        if not company_name:
            return False

        # Check for existing lead (dedup by company name + website domain)
        existing = self._find_existing_lead(company_name, website)
        if existing:
            logger.debug(f"Skipping duplicate: {company_name}")
            return False

        # Prepare data for CRM
        crm_data = {
            "company_name": company_name,
            "website": website,
            "funding_amount": lead_data.get("funding_amount", ""),
            "funding_date": lead_data.get("funding_date", ""),
            "funding_stage": lead_data.get("funding_stage", ""),
            "location": lead_data.get("location", ""),
            "industry_tags": lead_data.get("industry_tags", ""),
            "founders": lead_data.get("founders", ""),
            "investors": lead_data.get("investors", ""),
            "source_url": lead_data.get("source_url", ""),
            "source": lead_data.get("source", "funding_agent"),
            "icp_tag": lead_data.get("icp_tag", ""),
            "icp_score": lead_data.get("icp_score", 0),
            "icp_signals": lead_data.get("icp_signals", ""),
            "stage_pre": "research",
            "priority": "medium",
        }

        # Create the lead
        lead_id = Lead.create(crm_data)

        # Log the activity
        source = lead_data.get("source", "unknown")
        funding = lead_data.get("funding_amount", "N/A")
        icp_tag = lead_data.get("icp_tag", "")
        Activity.create(
            lead_id,
            "note",
            f"Auto-imported by Funding Agent from {source} | "
            f"Funding: {funding} | ICP: {icp_tag}"
        )

        logger.info(
            f"Imported: {company_name} ({funding}) — {icp_tag}"
        )
        return True

    def _find_existing_lead(self, company_name: str, website: str) -> bool:
        """Check if a lead already exists in the CRM."""
        conn = get_db()

        # Check by company name (case-insensitive)
        cursor = conn.execute(
            "SELECT id FROM leads WHERE LOWER(company_name) = LOWER(?)",
            (company_name,)
        )
        if cursor.fetchone():
            return True

        # Check by website domain
        if website:
            domain = website.lower()
            for prefix in ["https://", "http://", "www."]:
                if domain.startswith(prefix):
                    domain = domain[len(prefix):]
            domain = domain.split("/")[0]

            if domain:
                cursor = conn.execute(
                    "SELECT id FROM leads WHERE LOWER(website) LIKE ?",
                    (f"%{domain}%",)
                )
                if cursor.fetchone():
                    return True

        return False
