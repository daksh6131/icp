#!/usr/bin/env python3
"""
Run the Funding News Agent.

Scrapes latest funding news and imports matching companies
directly into the CRM database with ICP scoring.

Usage:
    python run_agent.py                    # Run once (TechCrunch + Google News)
    python run_agent.py --sources all      # Run with all scrapers
    python run_agent.py --daemon           # Run every 6 hours
    python run_agent.py --min-score 50     # Only import leads with ICP score >= 50
"""

import argparse
import time

import schedule

from agents.funding_agent import FundingAgent, SCRAPER_REGISTRY
from utils import get_logger

logger = get_logger("run_agent")


def run_once(sources: list[str] = None, min_score: int = 0):
    """Run the funding agent once."""
    agent = FundingAgent(sources=sources, min_icp_score=min_score)
    results = agent.run()

    print(f"\nResults:")
    print(f"  Scraped:  {results['scraped']}")
    print(f"  Filtered: {results['filtered']}")
    print(f"  Imported: {results['imported']}")
    print(f"  Skipped:  {results['skipped']}")
    print(f"  Errors:   {results['errors']}")

    if results['leads']:
        print(f"\nNew leads:")
        for lead in results['leads']:
            print(f"  - {lead['company_name']} ({lead['funding_amount']}) {lead['icp_tag']}")

    return results


def run_daemon(sources: list[str] = None, min_score: int = 0, interval_hours: int = 6):
    """Run the funding agent on a schedule."""
    logger.info(f"Starting funding agent daemon (every {interval_hours}h)...")

    def job():
        run_once(sources=sources, min_score=min_score)

    schedule.every(interval_hours).hours.do(job)

    # Run immediately on startup
    logger.info("Running initial scrape...")
    job()

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(
        description="Funding News Agent — scrape and import leads to CRM"
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help=f"Scraper sources to use. Options: {', '.join(SCRAPER_REGISTRY.keys())}, all. "
             f"Default: techcrunch google_news"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run on a schedule (default: every 6 hours)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=6,
        help="Hours between runs in daemon mode (default: 6)"
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Minimum ICP score to import (default: 0 = all)"
    )

    args = parser.parse_args()

    # Handle 'all' sources
    sources = args.sources
    if sources and "all" in sources:
        sources = list(SCRAPER_REGISTRY.keys())

    if args.daemon:
        run_daemon(sources=sources, min_score=args.min_score, interval_hours=args.interval)
    else:
        run_once(sources=sources, min_score=args.min_score)


if __name__ == "__main__":
    main()
