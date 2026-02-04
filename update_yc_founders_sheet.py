#!/usr/bin/env python3
"""
Update YC Founders sheet with company websites and ICP fit scoring.
Fetches company websites from YC Companies API and calculates ICP scores.
"""

import json
import sys
import time
import requests

# Add parent directory to path for imports
sys.path.insert(0, '/Users/daksh/Desktop/code/Content Project/icp-scraper')

from integrations.google_sheets import GoogleSheetsClient
from utils import get_logger

logger = get_logger(__name__)

# Algolia config for YC Companies (different index than Founders)
ALGOLIA_APP_ID = "45BWZJ1SGC"
ALGOLIA_API_KEY = "MjBjYjRiMzY0NzdhZWY0NjExY2NhZjYxMGIxYjc2MTAwNWFkNTkwNTc4NjgxYjU0YzFhYTY2ZGQ5OGY5NDMxZnJlc3RyaWN0SW5kaWNlcz0lNUIlMjJZQ0NvbXBhbnlfcHJvZHVjdGlvbiUyMiUyQyUyMllDQ29tcGFueV9CeV9MYXVuY2hfRGF0ZV9wcm9kdWN0aW9uJTIyJTVEJnRhZ0ZpbHRlcnM9JTVCJTIyeWNkY19wdWJsaWMlMjIlNUQmYW5hbHl0aWNzVGFncz0lNUIlMjJ5Y2RjJTIyJTVE"


def fetch_all_yc_companies():
    """Fetch all YC companies with their website URLs."""
    logger.info("Fetching all YC companies from Algolia...")

    url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
    params = {
        "x-algolia-agent": "Algolia for JavaScript (3.35.1); Browser",
        "x-algolia-application-id": ALGOLIA_APP_ID,
        "x-algolia-api-key": ALGOLIA_API_KEY,
    }
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://www.ycombinator.com",
        "Referer": "https://www.ycombinator.com/",
    }

    all_companies = {}
    page = 0
    hits_per_page = 1000

    while page < 20:  # Safety limit - should cover ~5000+ companies
        payload = {
            "requests": [{
                "indexName": "YCCompany_production",
                "params": f"hitsPerPage={hits_per_page}&page={page}"
            }]
        }

        try:
            response = requests.post(url, params=params, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [{}])[0]
            hits = results.get("hits", [])

            if not hits:
                break

            for company in hits:
                slug = company.get("slug", "")
                if slug:
                    all_companies[slug] = {
                        "name": company.get("name", ""),
                        "website": company.get("website", ""),
                        "batch": company.get("batch", ""),
                        "tags": company.get("tags", []),
                        "regions": company.get("regions", []),
                        "one_liner": company.get("one_liner", ""),
                    }

            logger.info(f"  Page {page + 1}: {len(hits)} companies (total: {len(all_companies)})")

            if len(hits) < hits_per_page:
                break

            page += 1
            time.sleep(0.5)  # Rate limiting

        except Exception as e:
            logger.error(f"Error fetching page {page}: {e}")
            break

    logger.info(f"Total companies fetched: {len(all_companies)}")
    return all_companies


def calculate_icp_score_for_founder(founder: dict, company_data: dict = None) -> tuple:
    """
    Calculate ICP score for a YC founder.
    Returns (tag, score, signals)
    """
    signals = []
    score = 0

    # Get data from founder and company
    industries = founder.get("industries", "").lower()
    location = founder.get("location", "").lower()
    batch = founder.get("batch", "")

    if company_data:
        tags = " ".join(company_data.get("tags", [])).lower()
        industries = industries + " " + tags

    # === 1. YC BATCH RECENCY (Max 25 points) ===
    recent_batches = ["W25", "S25", "X25", "X26"]
    good_batches = ["W24", "S24", "X24"]
    older_batches = ["W23", "S23"]

    if batch in recent_batches:
        signals.append(f"Recent Batch ({batch})")
        score += 25
    elif batch in good_batches:
        signals.append(f"2024 Batch ({batch})")
        score += 20
    elif batch in older_batches:
        signals.append(f"2023 Batch ({batch})")
        score += 15
    elif batch.startswith(("W22", "S22")):
        signals.append("2022 Batch")
        score += 10
    elif batch:
        signals.append(f"YC Alumni ({batch})")
        score += 5

    # === 2. AI/TECH FOCUS (Max 30 points) ===
    ai_keywords = ["artificial intelligence", "machine learning", "ai", "ml", "deep learning",
                   "generative ai", "llm", "gpt", "computer vision", "nlp"]

    if any(kw in industries for kw in ["generative ai", "llm", "gpt"]):
        signals.append("Generative AI/LLM")
        score += 30
    elif any(kw in industries for kw in ["artificial intelligence", "machine learning"]):
        signals.append("AI/ML Core")
        score += 25
    elif any(kw in industries for kw in ["deep learning", "computer vision", "nlp"]):
        signals.append("AI Vertical")
        score += 22
    elif "ai" in industries.split():
        signals.append("AI-Related")
        score += 18

    # B2B bonus
    if any(kw in industries for kw in ["b2b", "enterprise", "saas"]):
        signals.append("B2B Focus")
        score += 8

    # === 3. LOCATION (Max 20 points) ===
    if any(loc in location for loc in ["san francisco", "sf", "bay area", "silicon valley", "palo alto"]):
        signals.append("SF/Bay Area")
        score += 20
    elif any(loc in location for loc in ["new york", "ny", "nyc"]):
        signals.append("New York")
        score += 20
    elif any(loc in location for loc in ["london", "uk"]):
        signals.append("London")
        score += 15
    elif any(loc in location for loc in ["berlin", "germany"]):
        signals.append("Berlin")
        score += 15
    elif any(loc in location for loc in ["tel aviv", "israel"]):
        signals.append("Tel Aviv")
        score += 15
    elif any(loc in location for loc in ["boston", "seattle", "austin", "los angeles"]):
        signals.append("US Tech Hub")
        score += 10
    elif "united states" in location:
        signals.append("USA")
        score += 8

    # === 4. INDUSTRY VERTICALS (Max 15 points) ===
    if any(kw in industries for kw in ["fintech", "finance"]):
        signals.append("Fintech")
        score += 12
    elif any(kw in industries for kw in ["healthcare", "health"]):
        signals.append("Healthcare")
        score += 12
    elif any(kw in industries for kw in ["developer tools", "devtools", "infrastructure"]):
        signals.append("Developer Tools")
        score += 15
    elif any(kw in industries for kw in ["security", "cybersecurity"]):
        signals.append("Security")
        score += 12

    # === CALCULATE ICP TAG ===
    if score >= 70:
        icp_tag = "PERFECT FIT"
    elif score >= 55:
        icp_tag = "STRONG FIT"
    elif score >= 40:
        icp_tag = "GOOD FIT"
    elif score >= 25:
        icp_tag = "POTENTIAL"
    elif score >= 15:
        icp_tag = "REVIEW"
    else:
        icp_tag = "LOW FIT"

    return icp_tag, score, " | ".join(signals) if signals else "YC Company"


def main():
    """Update YC Founders sheet with websites and ICP scores."""

    # Load founders data
    logger.info("Loading founders data...")
    with open('/Users/daksh/Desktop/code/Content Project/icp-scraper/yc_founders_data.json', 'r') as f:
        founders = json.load(f)
    logger.info(f"Loaded {len(founders)} founders")

    # Fetch company data for website URLs
    companies = fetch_all_yc_companies()

    # Build updated data with websites and ICP scores
    logger.info("Calculating ICP scores and matching websites...")
    updated_data = []

    for founder in founders:
        company_slug = founder.get("company_slug", "")
        company_data = companies.get(company_slug, {})

        # Get website from company data
        website = company_data.get("website", "")

        # Calculate ICP score
        icp_tag, icp_score, icp_signals = calculate_icp_score_for_founder(founder, company_data)

        # Build row data
        row = {
            "founder_name": founder.get("founder_name", ""),
            "founder_title": founder.get("founder_title", "") or "",
            "company_name": founder.get("company_name", ""),
            "company_website": website,
            "batch": founder.get("batch", ""),
            "location": founder.get("location", ""),
            "industries": founder.get("industries", ""),
            "icp_tag": icp_tag,
            "icp_score": icp_score,
            "icp_signals": icp_signals,
            "all_companies": founder.get("all_companies", ""),
            "founder_profile_url": founder.get("founder_profile_url", ""),
            "yc_company_url": founder.get("company_url", ""),
        }
        updated_data.append(row)

    # Sort by ICP score (highest first)
    updated_data.sort(key=lambda x: x["icp_score"], reverse=True)

    # Log ICP distribution
    perfect = sum(1 for r in updated_data if r["icp_score"] >= 70)
    strong = sum(1 for r in updated_data if 55 <= r["icp_score"] < 70)
    good = sum(1 for r in updated_data if 40 <= r["icp_score"] < 55)
    potential = sum(1 for r in updated_data if 25 <= r["icp_score"] < 40)
    review = sum(1 for r in updated_data if 15 <= r["icp_score"] < 25)
    low = sum(1 for r in updated_data if r["icp_score"] < 15)

    logger.info(f"ICP Score Distribution:")
    logger.info(f"  PERFECT FIT (70+): {perfect}")
    logger.info(f"  STRONG FIT (55-69): {strong}")
    logger.info(f"  GOOD FIT (40-54): {good}")
    logger.info(f"  POTENTIAL (25-39): {potential}")
    logger.info(f"  REVIEW (15-24): {review}")
    logger.info(f"  LOW FIT (<15): {low}")

    # Update Google Sheet
    logger.info("Updating Google Sheet...")
    sheets = GoogleSheetsClient()

    # Headers for the sheet
    headers = [
        "Founder Name", "Title", "Company", "Company Website", "Batch",
        "Location", "Industries", "ICP Tag", "ICP Score", "ICP Signals",
        "All Companies", "Profile URL", "YC Company URL"
    ]

    # Convert to rows
    rows = [headers]
    for row in updated_data:
        rows.append([
            row["founder_name"],
            row["founder_title"],
            row["company_name"],
            row["company_website"],
            row["batch"],
            row["location"],
            row["industries"],
            row["icp_tag"],
            str(row["icp_score"]),
            row["icp_signals"],
            row["all_companies"],
            row["founder_profile_url"],
            row["yc_company_url"],
        ])

    # Write to YC Founders sheet
    sheet_name = "YC Founders"

    try:
        # Clear and update
        result = sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!A1",
            valueInputOption="RAW",
            body={"values": rows}
        ).execute()

        logger.info(f"Successfully updated {result.get('updatedCells', 0)} cells in '{sheet_name}'")

    except Exception as e:
        logger.error(f"Failed to update sheet: {e}")
        raise

    # Print top founders
    print("\n" + "="*80)
    print("TOP 20 YC FOUNDERS BY ICP FIT")
    print("="*80)
    for i, row in enumerate(updated_data[:20], 1):
        print(f"\n{i}. {row['founder_name']} - {row['icp_tag']} (Score: {row['icp_score']})")
        print(f"   Company: {row['company_name']} ({row['batch']})")
        print(f"   Website: {row['company_website'] or 'N/A'}")
        print(f"   Signals: {row['icp_signals']}")


if __name__ == "__main__":
    main()
