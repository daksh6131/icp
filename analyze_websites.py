#!/usr/bin/env python3
"""
CLI for analyzing websites in Google Sheets.
Adds website quality metrics to ICP Leads or YC Founders sheets.
"""

import argparse
import sys
import time
from datetime import datetime

from analyzers import WebsiteAnalyzer
from integrations.google_sheets import GoogleSheetsClient
from utils import get_logger

logger = get_logger(__name__)


# Column mappings for different sheets
SHEET_CONFIGS = {
    "ICP Leads": {
        "website_col": "B",  # Website URL column
        "company_col": "A",  # Company name column
        "analysis_start_col": "Q",  # Where to start writing analysis
        "headers": [
            "Website Last Updated",
            "Update Confidence",
            "Aesthetics Score",
            "Aesthetics Notes",
            "Brand Score",
            "Brand Notes",
            "Social Links",
            "Social Score",
            "Analysis Date",
            "Analysis Status",
        ],
    },
    "YC Founders": {
        "website_col": "D",  # Company Website column
        "company_col": "C",  # Company name column
        "analysis_start_col": "N",  # Where to start writing analysis
        "headers": [
            "Website Last Updated",
            "Update Confidence",
            "Aesthetics Score",
            "Aesthetics Notes",
            "Brand Score",
            "Brand Notes",
            "Social Links",
            "Social Score",
            "Analysis Date",
            "Analysis Status",
        ],
    },
}


def get_sheet_data(sheets: GoogleSheetsClient, sheet_name: str, config: dict) -> list:
    """Get website URLs and company names from sheet."""
    # Get website and company columns
    website_col = config["website_col"]
    company_col = config["company_col"]

    try:
        result = sheets.service.spreadsheets().values().get(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!{company_col}:{website_col}",
        ).execute()

        values = result.get("values", [])
        if not values:
            return []

        # Skip header row
        return values[1:]

    except Exception as e:
        logger.error(f"Failed to get sheet data: {e}")
        return []


def get_existing_analysis(sheets: GoogleSheetsClient, sheet_name: str, config: dict) -> set:
    """Get rows that already have analysis data."""
    start_col = config["analysis_start_col"]

    try:
        result = sheets.service.spreadsheets().values().get(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!{start_col}:{start_col}",
        ).execute()

        values = result.get("values", [])
        analyzed_rows = set()

        for i, row in enumerate(values[1:], start=2):  # Skip header, 1-indexed
            if row and row[0]:  # Has analysis data
                analyzed_rows.add(i)

        return analyzed_rows

    except Exception as e:
        logger.debug(f"Could not get existing analysis: {e}")
        return set()


def add_analysis_headers(sheets: GoogleSheetsClient, sheet_name: str, config: dict):
    """Add analysis column headers if not present."""
    start_col = config["analysis_start_col"]
    headers = config["headers"]

    # Convert column letter to index
    col_index = ord(start_col.upper()) - ord('A')

    try:
        # Check if headers exist
        result = sheets.service.spreadsheets().values().get(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!{start_col}1",
        ).execute()

        existing = result.get("values", [[]])[0]
        if existing and existing[0] == headers[0]:
            logger.debug("Analysis headers already exist")
            return

        # Add headers
        end_col = chr(ord(start_col) + len(headers) - 1)
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!{start_col}1:{end_col}1",
            valueInputOption="RAW",
            body={"values": [headers]}
        ).execute()

        logger.info(f"Added analysis headers to {sheet_name}")

    except Exception as e:
        logger.error(f"Failed to add headers: {e}")


def write_analysis_batch(
    sheets: GoogleSheetsClient,
    sheet_name: str,
    config: dict,
    start_row: int,
    results: list
):
    """Write a batch of analysis results to the sheet."""
    start_col = config["analysis_start_col"]
    end_col = chr(ord(start_col) + len(config["headers"]) - 1)

    # Convert results to rows
    rows = []
    for result in results:
        rows.append([
            result.get("last_updated", ""),
            result.get("update_confidence", ""),
            str(result.get("aesthetics_score", "")),
            result.get("aesthetics_notes", ""),
            str(result.get("brand_score", "")),
            result.get("brand_notes", ""),
            result.get("social_links", ""),
            str(result.get("social_score", "")),
            result.get("analysis_date", ""),
            result.get("analysis_status", ""),
        ])

    try:
        end_row = start_row + len(rows) - 1
        sheets.service.spreadsheets().values().update(
            spreadsheetId=sheets.sheet_id,
            range=f"'{sheet_name}'!{start_col}{start_row}:{end_col}{end_row}",
            valueInputOption="RAW",
            body={"values": rows}
        ).execute()

        logger.debug(f"Wrote {len(rows)} results to rows {start_row}-{end_row}")

    except Exception as e:
        logger.error(f"Failed to write batch: {e}")


def main():
    parser = argparse.ArgumentParser(description="Analyze websites in Google Sheets")
    parser.add_argument(
        "--sheet",
        choices=["ICP Leads", "YC Founders"],
        default="YC Founders",
        help="Sheet to analyze (default: YC Founders)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of websites to analyze (0 = no limit)"
    )
    parser.add_argument(
        "--skip-analyzed",
        action="store_true",
        help="Skip rows that already have analysis data"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-analyze all websites (ignore cache)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze but don't write to sheet"
    )
    parser.add_argument(
        "--no-claude",
        action="store_true",
        help="Disable Claude Vision (use heuristics only)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of websites to process before writing to sheet"
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=2,
        help="Row to start from (default: 2, skipping header)"
    )

    args = parser.parse_args()

    sheet_name = args.sheet
    config = SHEET_CONFIGS[sheet_name]

    logger.info(f"Starting website analysis for '{sheet_name}'")
    logger.info(f"Options: limit={args.limit}, skip_analyzed={args.skip_analyzed}, dry_run={args.dry_run}")

    # Initialize clients
    sheets = GoogleSheetsClient()
    analyzer = WebsiteAnalyzer(
        use_claude=not args.no_claude,
        use_cache=not args.force
    )

    # Add headers if needed
    if not args.dry_run:
        add_analysis_headers(sheets, sheet_name, config)

    # Get data from sheet
    data = get_sheet_data(sheets, sheet_name, config)
    if not data:
        logger.error("No data found in sheet")
        return

    logger.info(f"Found {len(data)} rows in sheet")

    # Get already analyzed rows
    analyzed_rows = set()
    if args.skip_analyzed:
        analyzed_rows = get_existing_analysis(sheets, sheet_name, config)
        logger.info(f"Found {len(analyzed_rows)} already analyzed rows")

    # Filter and prepare data
    to_analyze = []
    row_indices = []

    for i, row in enumerate(data, start=args.start_row):
        if args.skip_analyzed and i in analyzed_rows:
            continue

        # Get website URL
        if len(row) >= 2:
            company = row[0] if row else ""
            website = row[-1] if row else ""  # Last column in range
        else:
            company = row[0] if row else ""
            website = ""

        if not website or website.lower() in ["n/a", "none", ""]:
            continue

        to_analyze.append((company, website))
        row_indices.append(i)

        if args.limit > 0 and len(to_analyze) >= args.limit:
            break

    logger.info(f"Will analyze {len(to_analyze)} websites")

    if not to_analyze:
        logger.info("Nothing to analyze")
        return

    # Analyze in batches
    batch_size = args.batch_size
    total = len(to_analyze)
    analyzed = 0
    failed = 0

    start_time = time.time()

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch = to_analyze[batch_start:batch_end]
        batch_rows = row_indices[batch_start:batch_end]

        logger.info(f"Processing batch {batch_start + 1}-{batch_end} of {total}")

        results = []
        for company, website in batch:
            try:
                result = analyzer.analyze(website, company)
                results.append(result)

                if result.get("analysis_status") == "Complete":
                    analyzed += 1
                else:
                    failed += 1

                # Log progress
                progress = batch_start + len(results)
                logger.info(
                    f"[{progress}/{total}] {company[:30]}: "
                    f"aesthetics={result.get('aesthetics_score', 0)}, "
                    f"brand={result.get('brand_score', 0)}, "
                    f"social={result.get('social_score', 0)}"
                )

            except Exception as e:
                logger.error(f"Error analyzing {website}: {e}")
                results.append({
                    "analysis_status": "Error",
                    "aesthetics_notes": str(e)[:50],
                })
                failed += 1

        # Write batch to sheet
        if not args.dry_run and results:
            write_analysis_batch(sheets, sheet_name, config, batch_rows[0], results)
            logger.info(f"Wrote batch to sheet (rows {batch_rows[0]}-{batch_rows[-1]})")

    # Clean up
    analyzer.close()

    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("ANALYSIS COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total processed: {total}")
    logger.info(f"Successfully analyzed: {analyzed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
    logger.info(f"Average per website: {elapsed/total:.2f} seconds")

    if args.dry_run:
        logger.info("(Dry run - no data written to sheet)")


if __name__ == "__main__":
    main()
