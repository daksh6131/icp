"""
Sync leads from Google Sheets to CRM database.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.google_sheets import GoogleSheetsClient
from crm.models import Lead, get_db
from utils import get_logger

logger = get_logger(__name__)


def sync_from_sheets(sheet_name: str = None) -> dict:
    """
    Sync leads from Google Sheets to the CRM database.

    Args:
        sheet_name: Specific sheet to sync (default: syncs both ICP Leads and YC Founders)

    Returns:
        Dictionary with sync results
    """
    sheets = GoogleSheetsClient()
    results = {
        'imported': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
    }

    sheets_to_sync = []
    if sheet_name:
        sheets_to_sync = [sheet_name]
    else:
        sheets_to_sync = ['ICP Leads', 'YC Founders']

    for sheet in sheets_to_sync:
        logger.info(f"Syncing {sheet}...")
        try:
            if sheet == 'ICP Leads':
                sync_icp_leads(sheets, results)
            elif sheet == 'YC Founders':
                sync_yc_founders(sheets, results)
        except Exception as e:
            logger.error(f"Error syncing {sheet}: {e}")
            results['errors'] += 1

    logger.info(f"Sync complete: {results}")
    return results


def sync_icp_leads(sheets: GoogleSheetsClient, results: dict):
    """Sync ICP Leads sheet."""
    try:
        result = sheets.service.spreadsheets().values().get(
            spreadsheetId=sheets.sheet_id,
            range="'ICP Leads'!A:P"
        ).execute()

        values = result.get('values', [])
        if not values or len(values) < 2:
            logger.info("No ICP Leads data found")
            return

        headers = values[0]
        rows = values[1:]

        for row in rows:
            try:
                # Pad row to match headers
                while len(row) < len(headers):
                    row.append('')

                data = dict(zip(headers, row))

                lead_data = {
                    'company_name': data.get('Company Name', ''),
                    'website': data.get('Website', ''),
                    'funding_amount': data.get('Funding Amount', ''),
                    'funding_date': data.get('Funding Date', ''),
                    'funding_stage': data.get('Funding Stage', ''),
                    'location': data.get('Location', ''),
                    'industry_tags': data.get('Industry Tags', ''),
                    'founders': data.get('Founders', ''),
                    'investors': data.get('Investors', ''),
                    'source_url': data.get('Source URL', ''),
                    'source': 'ICP Leads',
                    'icp_tag': data.get('ICP Tag', ''),
                    'icp_score': parse_int(data.get('ICP Score', '')),
                    'icp_signals': data.get('ICP Signals', ''),
                }

                if not lead_data['company_name']:
                    continue

                # Check if lead exists
                existing = find_lead(lead_data['company_name'], lead_data['website'])
                if existing:
                    results['skipped'] += 1
                else:
                    Lead.create(lead_data)
                    results['imported'] += 1

            except Exception as e:
                logger.debug(f"Error processing row: {e}")
                results['errors'] += 1

    except Exception as e:
        logger.error(f"Error fetching ICP Leads: {e}")
        raise


def sync_yc_founders(sheets: GoogleSheetsClient, results: dict):
    """Sync YC Founders sheet."""
    try:
        result = sheets.service.spreadsheets().values().get(
            spreadsheetId=sheets.sheet_id,
            range="'YC Founders'!A:W"
        ).execute()

        values = result.get('values', [])
        if not values or len(values) < 2:
            logger.info("No YC Founders data found")
            return

        headers = values[0]
        rows = values[1:]

        for row in rows:
            try:
                # Pad row to match headers
                while len(row) < len(headers):
                    row.append('')

                data = dict(zip(headers, row))

                # Map YC Founders columns to lead format
                lead_data = {
                    'company_name': data.get('Company', ''),
                    'website': data.get('Company Website', ''),
                    'funding_date': data.get('Batch', ''),  # Use batch as funding date
                    'funding_stage': f"YC {data.get('Batch', '')}",
                    'location': data.get('Location', ''),
                    'industry_tags': data.get('Industries', ''),
                    'founders': data.get('Founder Name', ''),
                    'source_url': data.get('YC Company URL', '') or data.get('Profile URL', ''),
                    'source': 'YC Founders',
                    'icp_tag': data.get('ICP Tag', ''),
                    'icp_score': parse_int(data.get('ICP Score', '')),
                    'icp_signals': data.get('ICP Signals', ''),
                    'website_last_updated': data.get('Website Last Updated', ''),
                    'aesthetics_score': parse_int(data.get('Aesthetics Score', '')),
                    'brand_score': parse_int(data.get('Brand Score', '')),
                    'social_score': parse_int(data.get('Social Score', '')),
                    'social_links': data.get('Social Links', ''),
                }

                if not lead_data['company_name']:
                    continue

                # Check if lead exists (by company name for YC since many founders per company)
                existing = find_lead(lead_data['company_name'], lead_data['website'])
                if existing:
                    # Update with website analysis data if available
                    if lead_data.get('aesthetics_score') or lead_data.get('brand_score'):
                        Lead.update(existing['id'], {
                            'website_last_updated': lead_data.get('website_last_updated'),
                            'aesthetics_score': lead_data.get('aesthetics_score'),
                            'brand_score': lead_data.get('brand_score'),
                            'social_score': lead_data.get('social_score'),
                            'social_links': lead_data.get('social_links'),
                        })
                        results['updated'] += 1
                    else:
                        results['skipped'] += 1
                else:
                    Lead.create(lead_data)
                    results['imported'] += 1

            except Exception as e:
                logger.debug(f"Error processing YC row: {e}")
                results['errors'] += 1

    except Exception as e:
        logger.error(f"Error fetching YC Founders: {e}")
        raise


def find_lead(company_name: str, website: str) -> dict:
    """Find existing lead by company name or website."""
    conn = get_db()

    # Try by company name
    cursor = conn.execute(
        "SELECT * FROM leads WHERE LOWER(company_name) = LOWER(?)",
        (company_name,)
    )
    row = cursor.fetchone()
    if row:
        conn.close()
        return dict(row)

    # Try by website domain
    if website:
        domain = website.lower().replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
        cursor = conn.execute(
            "SELECT * FROM leads WHERE LOWER(website) LIKE ?",
            (f'%{domain}%',)
        )
        row = cursor.fetchone()
        if row:
            conn.close()
            return dict(row)

    conn.close()
    return None


def parse_int(value: str) -> int:
    """Parse string to int, return 0 if invalid."""
    try:
        return int(value) if value else 0
    except (ValueError, TypeError):
        return 0


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Sync leads from Google Sheets')
    parser.add_argument('--sheet', choices=['ICP Leads', 'YC Founders'], help='Specific sheet to sync')
    args = parser.parse_args()

    result = sync_from_sheets(args.sheet)
    print(f"Sync complete: {result}")
