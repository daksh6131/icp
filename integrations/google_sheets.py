"""
Google Sheets integration for ICP Scraper.
Handles reading, writing, and deduplication of leads in Google Sheets.
"""

import os
from datetime import datetime
from typing import Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import config
from utils import get_logger

logger = get_logger(__name__)

# Sheet column headers
HEADERS = [
    "Company Name",
    "Website",
    "Funding Amount",
    "Funding Date",
    "Funding Stage",
    "Location",
    "Industry Tags",
    "Founders",
    "Investors",
    "Source URL",
    "Date Added",
    "Status",
    "ICP Tag",
    "ICP Score",
    "ICP Signals",
    "Notes"
]


class GoogleSheetsClient:
    """Client for interacting with Google Sheets."""

    def __init__(self, credentials_file: Optional[str] = None, sheet_id: Optional[str] = None):
        self.credentials_file = credentials_file or config.GOOGLE_SHEETS_CREDENTIALS_FILE
        self.sheet_id = sheet_id or config.GOOGLE_SHEET_ID
        self._service = None
        self._existing_domains: set[str] = set()

    @property
    def service(self):
        """Lazy-load the Google Sheets service."""
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self):
        """Build and return the Google Sheets API service."""
        if not os.path.exists(self.credentials_file):
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_file}\n"
                "Please follow the setup instructions in the README."
            )

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file, scopes=scopes
        )
        return build("sheets", "v4", credentials=credentials)

    def initialize_sheet(self) -> bool:
        """Initialize the sheet with headers if empty."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A1:P1"
            ).execute()

            values = result.get("values", [])
            if not values:
                # Sheet is empty, add headers
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range="A1:P1",
                    valueInputOption="RAW",
                    body={"values": [HEADERS]}
                ).execute()
                logger.info("Initialized sheet with headers")

            return True
        except HttpError as e:
            logger.error(f"Failed to initialize sheet: {e}")
            return False

    def load_existing_domains(self) -> set[str]:
        """Load existing company names and domains from the sheet for deduplication."""
        try:
            # Load both company names (A) and websites (B)
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A:B"
            ).execute()

            values = result.get("values", [])
            identifiers = set()

            for row in values[1:]:  # Skip header
                # Add company name (normalized)
                if row and row[0]:
                    name = row[0].lower().strip()
                    if name:
                        identifiers.add(f"name:{name}")

                # Add website domain
                if len(row) > 1 and row[1]:
                    domain = self._normalize_domain(row[1])
                    if domain:
                        identifiers.add(f"domain:{domain}")

            self._existing_domains = identifiers
            logger.info(f"Loaded {len(identifiers)} existing entries for deduplication")
            return identifiers
        except HttpError as e:
            logger.error(f"Failed to load existing entries: {e}")
            return set()

    def _normalize_domain(self, url: str) -> str:
        """Normalize a URL to just the domain for comparison."""
        url = url.lower().strip()
        # Remove protocol
        for prefix in ["https://", "http://", "www."]:
            if url.startswith(prefix):
                url = url[len(prefix):]
        # Remove trailing slash and path
        url = url.split("/")[0]
        return url

    def is_duplicate(self, company_name: str, website: str) -> bool:
        """Check if a company already exists in the sheet by name or domain."""
        if not self._existing_domains:
            self.load_existing_domains()

        # Check by company name
        if company_name:
            name_key = f"name:{company_name.lower().strip()}"
            if name_key in self._existing_domains:
                return True

        # Check by website domain
        if website:
            domain = self._normalize_domain(website)
            if domain:
                domain_key = f"domain:{domain}"
                if domain_key in self._existing_domains:
                    return True

        return False

    def add_lead(self, lead: dict) -> bool:
        """Add a single lead to the sheet."""
        company_name = lead.get("company_name", "")
        website = lead.get("website", "")

        if self.is_duplicate(company_name, website):
            logger.debug(f"Skipping duplicate: {company_name or 'Unknown'}")
            return False

        row = [
            lead.get("company_name", ""),
            website,
            lead.get("funding_amount", ""),
            lead.get("funding_date", ""),
            lead.get("funding_stage", ""),
            lead.get("location", ""),
            lead.get("industry_tags", ""),
            lead.get("founders", ""),
            lead.get("investors", ""),
            lead.get("source_url", ""),
            datetime.now().strftime("%Y-%m-%d"),
            "New",
            lead.get("icp_tag", ""),
            str(lead.get("icp_score", "")),
            lead.get("icp_signals", ""),
            lead.get("notes", "")
        ]

        try:
            self.service.spreadsheets().values().append(
                spreadsheetId=self.sheet_id,
                range="A:P",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]}
            ).execute()

            # Add to cache
            if company_name:
                self._existing_domains.add(f"name:{company_name.lower().strip()}")
            if website:
                domain = self._normalize_domain(website)
                if domain:
                    self._existing_domains.add(f"domain:{domain}")

            logger.info(f"Added lead: {company_name or 'Unknown'}")
            return True
        except HttpError as e:
            logger.error(f"Failed to add lead: {e}")
            return False

    def add_leads_batch(self, leads: list[dict], batch_size: int = 50) -> int:
        """Add multiple leads in batches to avoid rate limits."""
        import time

        # First filter out duplicates
        new_leads = []
        for lead in leads:
            company_name = lead.get("company_name", "")
            website = lead.get("website", "")
            if not self.is_duplicate(company_name, website):
                new_leads.append(lead)

        if not new_leads:
            logger.info("No new leads to add (all duplicates)")
            return 0

        logger.info(f"Adding {len(new_leads)} new leads in batches of {batch_size}")

        # Prepare all rows
        rows = []
        for lead in new_leads:
            row = [
                lead.get("company_name", ""),
                lead.get("website", ""),
                lead.get("funding_amount", ""),
                lead.get("funding_date", ""),
                lead.get("funding_stage", ""),
                lead.get("location", ""),
                lead.get("industry_tags", ""),
                lead.get("founders", ""),
                lead.get("investors", ""),
                lead.get("source_url", ""),
                datetime.now().strftime("%Y-%m-%d"),
                "New",
                lead.get("icp_tag", ""),
                str(lead.get("icp_score", "")),
                lead.get("icp_signals", ""),
                lead.get("notes", "")
            ]
            rows.append(row)

        # Add in batches
        added_count = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            try:
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.sheet_id,
                    range="A:P",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": batch}
                ).execute()
                added_count += len(batch)
                logger.info(f"  Batch {i // batch_size + 1}: Added {len(batch)} leads (total: {added_count})")

                # Update cache
                for lead in new_leads[i:i + batch_size]:
                    company_name = lead.get("company_name", "")
                    website = lead.get("website", "")
                    if company_name:
                        self._existing_domains.add(f"name:{company_name.lower().strip()}")
                    if website:
                        domain = self._normalize_domain(website)
                        if domain:
                            self._existing_domains.add(f"domain:{domain}")

                # Rate limit: wait between batches
                if i + batch_size < len(rows):
                    time.sleep(2)  # 2 second delay between batches

            except HttpError as e:
                logger.error(f"Failed to add batch: {e}")
                # Wait longer if rate limited
                if "429" in str(e) or "Quota" in str(e):
                    logger.info("Rate limited, waiting 60 seconds...")
                    time.sleep(60)

        logger.info(f"Added {added_count}/{len(leads)} leads total")
        return added_count

    def add_leads(self, leads: list[dict]) -> int:
        """Add multiple leads to the sheet, skipping duplicates."""
        added_count = 0
        for lead in leads:
            if self.add_lead(lead):
                added_count += 1
        logger.info(f"Added {added_count}/{len(leads)} leads (duplicates skipped)")
        return added_count

    def get_all_leads(self) -> list[dict]:
        """Get all leads from the sheet."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A:P"
            ).execute()

            values = result.get("values", [])
            if len(values) <= 1:
                return []

            leads = []
            headers = values[0]
            for row in values[1:]:
                # Pad row to match headers length
                row = row + [""] * (16 - len(row))
                lead = {
                    "company_name": row[0],
                    "website": row[1],
                    "funding_amount": row[2],
                    "funding_date": row[3],
                    "funding_stage": row[4],
                    "location": row[5],
                    "industry_tags": row[6],
                    "founders": row[7],
                    "investors": row[8],
                    "source_url": row[9],
                    "date_added": row[10],
                    "status": row[11],
                    "icp_tag": row[12],
                    "icp_score": row[13],
                    "icp_signals": row[14],
                    "notes": row[15]
                }
                leads.append(lead)

            return leads
        except HttpError as e:
            logger.error(f"Failed to get leads: {e}")
            return []

    def remove_duplicates(self) -> int:
        """Remove duplicate entries from the sheet based on company name."""
        try:
            # Get all data
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A:P"
            ).execute()

            values = result.get("values", [])
            if len(values) <= 1:
                logger.info("No data to deduplicate")
                return 0

            headers = values[0]
            rows = values[1:]

            # Track seen company names (case-insensitive)
            seen_names = set()
            seen_websites = set()
            unique_rows = []
            duplicates_removed = 0

            for row in rows:
                # Pad row if needed
                row = row + [""] * (16 - len(row))

                company_name = row[0].lower().strip() if row[0] else ""
                website = self._normalize_domain(row[1]) if len(row) > 1 and row[1] else ""

                # Check if duplicate
                is_duplicate = False
                if company_name and company_name in seen_names:
                    is_duplicate = True
                if website and website in seen_websites:
                    is_duplicate = True

                if is_duplicate:
                    duplicates_removed += 1
                    logger.debug(f"Removing duplicate: {row[0]}")
                else:
                    unique_rows.append(row)
                    if company_name:
                        seen_names.add(company_name)
                    if website:
                        seen_websites.add(website)

            if duplicates_removed == 0:
                logger.info("No duplicates found")
                return 0

            # Clear the sheet and rewrite with unique data
            logger.info(f"Removing {duplicates_removed} duplicates...")

            # Clear existing data (keep headers)
            self.service.spreadsheets().values().clear(
                spreadsheetId=self.sheet_id,
                range="A2:P"
            ).execute()

            # Write unique rows back
            if unique_rows:
                self.service.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range="A2:P",
                    valueInputOption="RAW",
                    body={"values": unique_rows}
                ).execute()

            logger.info(f"Removed {duplicates_removed} duplicates. {len(unique_rows)} unique rows remain.")
            return duplicates_removed

        except HttpError as e:
            logger.error(f"Failed to remove duplicates: {e}")
            return 0

    def add_duplicate_protection(self) -> bool:
        """
        Add conditional formatting to highlight duplicates in the sheet.
        This creates a visual indicator for any duplicate company names.
        """
        try:
            # Get sheet ID (not spreadsheet ID)
            spreadsheet = self.service.spreadsheets().get(
                spreadsheetId=self.sheet_id
            ).execute()
            sheet_id = spreadsheet["sheets"][0]["properties"]["sheetId"]

            # Add conditional formatting rule to highlight duplicates in column A
            requests = [
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": sheet_id,
                                "startRowIndex": 1,  # Skip header
                                "startColumnIndex": 0,  # Column A (Company Name)
                                "endColumnIndex": 1
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{
                                        "userEnteredValue": "=COUNTIF($A:$A,$A2)>1"
                                    }]
                                },
                                "format": {
                                    "backgroundColor": {
                                        "red": 1.0,
                                        "green": 0.8,
                                        "blue": 0.8
                                    }
                                }
                            }
                        },
                        "index": 0
                    }
                },
                # Also highlight duplicate websites in column B
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "startColumnIndex": 1,  # Column B (Website)
                                "endColumnIndex": 2
                            }],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{
                                        "userEnteredValue": "=AND(B2<>\"\",COUNTIF($B:$B,$B2)>1)"
                                    }]
                                },
                                "format": {
                                    "backgroundColor": {
                                        "red": 1.0,
                                        "green": 0.9,
                                        "blue": 0.6
                                    }
                                }
                            }
                        },
                        "index": 1
                    }
                }
            ]

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.sheet_id,
                body={"requests": requests}
            ).execute()

            logger.info("Added duplicate highlighting rules to sheet")
            return True

        except HttpError as e:
            logger.error(f"Failed to add duplicate protection: {e}")
            return False

    def get_duplicate_count(self) -> dict:
        """Count duplicates in the sheet."""
        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.sheet_id,
                range="A:B"
            ).execute()

            values = result.get("values", [])
            if len(values) <= 1:
                return {"name_duplicates": 0, "website_duplicates": 0, "total_rows": 0}

            rows = values[1:]

            # Count name duplicates
            names = [row[0].lower().strip() for row in rows if row and row[0]]
            name_counts = {}
            for name in names:
                name_counts[name] = name_counts.get(name, 0) + 1
            name_duplicates = sum(1 for count in name_counts.values() if count > 1)

            # Count website duplicates
            websites = [self._normalize_domain(row[1]) for row in rows if len(row) > 1 and row[1]]
            website_counts = {}
            for site in websites:
                if site:
                    website_counts[site] = website_counts.get(site, 0) + 1
            website_duplicates = sum(1 for count in website_counts.values() if count > 1)

            return {
                "name_duplicates": name_duplicates,
                "website_duplicates": website_duplicates,
                "total_rows": len(rows)
            }

        except HttpError as e:
            logger.error(f"Failed to count duplicates: {e}")
            return {"name_duplicates": 0, "website_duplicates": 0, "total_rows": 0}
