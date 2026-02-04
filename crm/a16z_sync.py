"""
Sync a16z Speedrun portfolio companies into the CRM.
Fetches from the Speedrun API and imports companies as leads.
"""

import requests
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from crm.models import Lead, Activity, get_db
from utils import get_logger

logger = get_logger(__name__)

API_BASE = "https://speedrun-be.a16z.com/api/companies/companies/"
PAGE_SIZE = 50


def fetch_all_companies() -> list:
    """Fetch all companies from the a16z Speedrun API."""
    companies = []
    offset = 0

    while True:
        url = f"{API_BASE}?limit={PAGE_SIZE}&offset={offset}&ordering=name"
        logger.info(f"Fetching a16z Speedrun companies (offset={offset})...")

        try:
            res = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                'Accept': 'application/json',
            })
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            logger.error(f"Failed to fetch a16z companies at offset {offset}: {e}")
            break

        results = data.get('results', [])
        if not results:
            break

        companies.extend(results)
        offset += PAGE_SIZE

        # Check if we've got them all
        total = data.get('count', 0)
        if offset >= total:
            break

    logger.info(f"Fetched {len(companies)} companies from a16z Speedrun")
    return companies


def parse_company(company: dict) -> dict:
    """Parse a16z Speedrun company data into CRM lead format."""
    # Extract founders
    founders = []
    founder_linkedin = None
    for founder in company.get('founder_set', []):
        name = f"{founder.get('first_name', '')} {founder.get('last_name', '')}".strip()
        if name:
            founders.append(name)
        # Grab first founder's LinkedIn
        if not founder_linkedin and founder.get('linkedin_url'):
            founder_linkedin = founder['linkedin_url']

    # Extract industries as tags
    industries = company.get('industries', [])
    industry_tags = ', '.join(industries) if industries else None

    # Build location
    location_parts = []
    if company.get('city'):
        location_parts.append(company['city'])
    if company.get('state'):
        location_parts.append(company['state'])
    if company.get('country'):
        location_parts.append(company['country'])
    location = ', '.join(location_parts) if location_parts else None

    # Description - use preamble (short tagline) or description
    description = company.get('preamble') or ''
    if not description and company.get('description'):
        # Take first 200 chars of description
        description = company['description'][:200]

    return {
        'company_name': company.get('name', '').strip(),
        'website': company.get('website_url', '').strip() or None,
        'industry_tags': industry_tags,
        'founders': ', '.join(founders) if founders else None,
        'location': location,
        'source': 'a16z_speedrun',
        'source_url': f"https://speedrun.a16z.com/companies/{company.get('slug', '')}",
        'funding_stage': f"a16z Speedrun {company.get('cohort', '')}".strip(),
        'notes': description,
        'linkedin_url': founder_linkedin,
        'stage_pre': 'research',
        'priority': 'medium',
    }


def sync_a16z_speedrun() -> dict:
    """
    Sync a16z Speedrun portfolio companies into the CRM.

    Returns:
        dict with imported, updated, skipped, errors counts
    """
    results = {
        'imported': 0,
        'updated': 0,
        'skipped': 0,
        'errors': 0,
        'total_fetched': 0,
    }

    companies = fetch_all_companies()
    results['total_fetched'] = len(companies)

    if not companies:
        logger.warning("No companies fetched from a16z Speedrun")
        return results

    conn = get_db()

    for company in companies:
        try:
            lead_data = parse_company(company)

            if not lead_data['company_name']:
                results['skipped'] += 1
                continue

            # Check if lead already exists by company name
            cursor = conn.execute(
                "SELECT id, source FROM leads WHERE LOWER(company_name) = LOWER(?)",
                (lead_data['company_name'],)
            )
            existing = cursor.fetchone()

            if existing:
                existing_id = existing[0]
                existing_source = existing[1] or ''

                # Skip if already from a16z
                if 'a16z' in existing_source:
                    results['skipped'] += 1
                    continue

                # Update existing lead with a16z data (enrich)
                update_fields = {}
                if lead_data['website'] and not existing.get('website'):
                    update_fields['website'] = lead_data['website']
                if lead_data['industry_tags']:
                    update_fields['industry_tags'] = lead_data['industry_tags']
                if lead_data['founders']:
                    update_fields['founders'] = lead_data['founders']
                if lead_data['location']:
                    update_fields['location'] = lead_data['location']
                if lead_data['funding_stage']:
                    update_fields['funding_stage'] = lead_data['funding_stage']
                if lead_data['linkedin_url']:
                    update_fields['linkedin_url'] = lead_data['linkedin_url']

                # Mark source as enriched
                update_fields['source'] = f"{existing_source},a16z_speedrun" if existing_source else 'a16z_speedrun'

                if update_fields:
                    Lead.update(existing_id, update_fields)
                    Activity.create(existing_id, 'note', f"Enriched with a16z Speedrun data ({lead_data.get('funding_stage', '')})")

                results['updated'] += 1
            else:
                # Create new lead
                lead_id = Lead.create(lead_data)
                Activity.create(lead_id, 'note', f"Imported from a16z Speedrun ({lead_data.get('funding_stage', '')})")
                results['imported'] += 1

        except Exception as e:
            logger.error(f"Error processing company {company.get('name', '?')}: {e}")
            results['errors'] += 1

    conn.close()

    logger.info(
        f"a16z Speedrun sync complete: "
        f"{results['imported']} imported, {results['updated']} updated, "
        f"{results['skipped']} skipped, {results['errors']} errors"
    )

    return results
