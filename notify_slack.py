#!/usr/bin/env python3
"""
Send a Slack notification with latest scrape results to #sales-engine.
Uses a Slack incoming webhook URL from `.env`.

Usage:
    python notify_slack.py                    # Send update with latest leads
    python notify_slack.py --results '...'    # Pass scrape results JSON
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
import os

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from crm.models import get_db


SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()


def get_scrape_summary():
    """Get summary stats and top leads from CRM database."""
    db = get_db()

    total = db.execute("SELECT COUNT(*) as c FROM leads").fetchone()["c"]
    today = db.execute(
        "SELECT COUNT(*) as c FROM leads WHERE created_at >= datetime('now', '-1 day')"
    ).fetchone()["c"]
    avg_score = db.execute(
        "SELECT AVG(icp_score) as a FROM leads WHERE icp_score > 0"
    ).fetchone()["a"] or 0

    top_leads = db.execute(
        "SELECT company_name, funding_amount, funding_stage, icp_score, source "
        "FROM leads ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    return {
        "total": total,
        "new_today": today,
        "avg_score": round(avg_score, 1),
        "top_leads": [dict(l) for l in top_leads],
    }


def format_slack_message(summary, scrape_results=None):
    """Format a Slack markdown message from scrape summary."""
    now = datetime.now().strftime("%b %d, %Y %I:%M %p")

    leads_table = ""
    for l in summary["top_leads"]:
        name = l["company_name"]
        funding = l["funding_amount"] or "N/A"
        stage = l["funding_stage"] or "\u2014"
        score = l["icp_score"]
        source = l["source"]
        leads_table += f"| {name} | {funding} | {stage} | {score} | {source} |\n"

    scraped = imported = errors = ""
    if scrape_results:
        scraped = f"\n- Scraped: **{scrape_results.get('scraped', 'N/A')}** companies"
        imported = f"\n- Imported: **{scrape_results.get('imported', 'N/A')}** new leads"
        errors = f"\n- Errors: **{scrape_results.get('errors', 0)}**"

    msg = (
        f"# ICP Lead Scraper \u2014 Daily Update\n"
        f"*{now}*\n\n"
        f"**Database Stats**\n"
        f"- Total leads: **{summary['total']:,}**\n"
        f"- New today: **{summary['new_today']}**\n"
        f"- Avg ICP Score: **{summary['avg_score']}**"
        f"{scraped}{imported}{errors}\n\n"
        f"---\n\n"
        f"## Latest Leads\n\n"
        f"| Company | Funding | Stage | ICP | Source |\n"
        f"|---------|---------|-------|-----|--------|\n"
        f"{leads_table}\n"
        f"---\n\n"
        f"> Portal: http://localhost:8080"
    )
    return msg


def send_slack_notification(message):
    """Send message to Slack via incoming webhook."""
    print("Sending Slack notification...")
    print(f"Message length: {len(message)} chars")

    # Keep a local copy for debugging even if Slack delivery fails.
    msg_file = Path(__file__).parent / ".last_scrape_message.txt"
    msg_file.write_text(message)
    print(f"Message saved to {msg_file}")

    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL is not configured in .env")
        return False

    try:
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code != 200:
            print(
                f"ERROR: Slack webhook failed ({response.status_code}): "
                f"{response.text.strip()}"
            )
            return False
        print("Slack notification sent successfully")
        return True
    except requests.RequestException as exc:
        print(f"ERROR: Slack request failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Send Slack scrape notification")
    parser.add_argument("--results", type=str, default=None, help="Scrape results JSON")
    args = parser.parse_args()

    scrape_results = None
    if args.results:
        scrape_results = json.loads(args.results)

    summary = get_scrape_summary()
    message = format_slack_message(summary, scrape_results)

    print(message)
    sent = send_slack_notification(message)
    if not sent:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
