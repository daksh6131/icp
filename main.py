#!/usr/bin/env python3
"""
ICP Scraper - Find AI startups with recent funding.

This tool scrapes various sources for AI startups that have recently
raised $5M+ in funding and adds them to a Google Sheet for outreach.

Usage:
    python main.py           # Run once
    python main.py --daemon  # Run daily at 8am
"""

import argparse
import sys
import time
from datetime import datetime

import schedule

from config import config
from utils import get_logger
from scrapers import (
    TechCrunchScraper,
    CrunchbaseScraper,
    YCDirectoryScraper,
    ProductHuntScraper,
    GoogleNewsScraper,
)
from processors import ICPFilter
from integrations import GoogleSheetsClient

logger = get_logger("main")


def run_scraper():
    """Main scraping workflow."""
    logger.info("=" * 50)
    logger.info(f"Starting ICP scraper run at {datetime.now()}")
    logger.info("=" * 50)

    # Initialize components
    sheets_client = GoogleSheetsClient()
    icp_filter = ICPFilter()

    # Initialize sheet and load existing data for deduplication
    if not config.GOOGLE_SHEET_ID:
        logger.error(
            "GOOGLE_SHEET_ID not configured. "
            "Please set it in .env file or environment variables."
        )
        return

    try:
        sheets_client.initialize_sheet()
        sheets_client.load_existing_domains()
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets: {e}")
        logger.info("Continuing with scraping - will save results locally if needed")

    # Collect leads from all sources
    all_leads = []

    # 1. TechCrunch (most reliable for recent funding news)
    logger.info("\n--- Scraping TechCrunch ---")
    try:
        tc_scraper = TechCrunchScraper()
        tc_leads = tc_scraper.scrape()
        logger.info(f"TechCrunch: Found {len(tc_leads)} potential leads")
        all_leads.extend(tc_leads)
    except Exception as e:
        logger.error(f"TechCrunch scraper failed: {e}")

    # 2. Google News (funding announcements)
    logger.info("\n--- Scraping Google News ---")
    try:
        gn_scraper = GoogleNewsScraper()
        gn_leads = gn_scraper.scrape()
        logger.info(f"Google News: Found {len(gn_leads)} potential leads")
        all_leads.extend(gn_leads)
    except Exception as e:
        logger.error(f"Google News scraper failed: {e}")

    # 3. Y Combinator Directory (AI startups)
    logger.info("\n--- Scraping Y Combinator ---")
    try:
        yc_scraper = YCDirectoryScraper()
        yc_leads = yc_scraper.scrape()
        logger.info(f"Y Combinator: Found {len(yc_leads)} potential leads")
        all_leads.extend(yc_leads)
    except Exception as e:
        logger.error(f"Y Combinator scraper failed: {e}")

    # 4. Product Hunt (AI product launches)
    logger.info("\n--- Scraping Product Hunt ---")
    try:
        ph_scraper = ProductHuntScraper()
        ph_leads = ph_scraper.scrape()
        logger.info(f"Product Hunt: Found {len(ph_leads)} potential leads")
        all_leads.extend(ph_leads)
    except Exception as e:
        logger.error(f"Product Hunt scraper failed: {e}")

    # 5. Crunchbase (may be limited due to anti-scraping measures)
    logger.info("\n--- Scraping Crunchbase ---")
    try:
        cb_scraper = CrunchbaseScraper()
        cb_leads = cb_scraper.scrape()
        logger.info(f"Crunchbase: Found {len(cb_leads)} potential leads")
        all_leads.extend(cb_leads)
    except Exception as e:
        logger.error(f"Crunchbase scraper failed: {e}")

    logger.info(f"\nTotal raw leads collected: {len(all_leads)}")

    # 6. Filter by ICP criteria
    logger.info("\n--- Applying ICP Filter ---")
    filtered_leads = icp_filter.filter_leads(all_leads)
    logger.info(f"Leads matching ICP: {len(filtered_leads)}")

    # 7. Tag and score leads by ICP fit
    logger.info("\n--- Tagging Leads by ICP Fit ---")
    tagged_leads = icp_filter.tag_and_filter_leads(filtered_leads, min_score=0)

    # 8. Add to Google Sheets (in batches to avoid rate limits)
    logger.info("\n--- Adding to Google Sheets ---")
    added_count = sheets_client.add_leads_batch(tagged_leads, batch_size=50)

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("SCRAPER RUN COMPLETE")
    logger.info(f"  Total leads scraped: {len(all_leads)}")
    logger.info(f"  Leads matching ICP: {len(filtered_leads)}")
    logger.info(f"  Tagged leads: {len(tagged_leads)}")
    logger.info(f"  New leads added: {added_count}")

    # Show ICP fit distribution
    perfect = sum(1 for l in tagged_leads if l.get("icp_score", 0) >= 80)
    strong = sum(1 for l in tagged_leads if 65 <= l.get("icp_score", 0) < 80)
    good = sum(1 for l in tagged_leads if 50 <= l.get("icp_score", 0) < 65)
    if perfect or strong or good:
        logger.info(f"  High-quality leads: {perfect} perfect, {strong} strong, {good} good fit")
    logger.info("=" * 50)

    # Optionally send notification
    if added_count > 0 and config.SLACK_WEBHOOK_URL:
        send_slack_notification(added_count, filtered_leads[:5])

    return added_count


def send_slack_notification(count: int, top_leads: list):
    """Send a Slack notification about new leads."""
    try:
        import requests

        leads_text = "\n".join([
            f"• {lead.get('company_name', 'Unknown')} - {lead.get('funding_amount', 'N/A')}"
            for lead in top_leads
        ])

        payload = {
            "text": f"*ICP Scraper* found {count} new leads!\n\nTop leads:\n{leads_text}"
        }

        requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=10)
        logger.info("Slack notification sent")
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {e}")


def run_daemon():
    """Run the scraper on a schedule."""
    logger.info("Starting ICP scraper daemon...")
    logger.info("Will run daily at 8:00 AM")

    # Schedule daily run
    schedule.every().day.at("08:00").do(run_scraper)

    # Also run immediately on startup
    logger.info("Running initial scrape...")
    run_scraper()

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(
        description="ICP Scraper - Find AI startups with recent funding"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon, scraping daily at 8am"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't add to Google Sheets"
    )

    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        run_scraper()


if __name__ == "__main__":
    main()
