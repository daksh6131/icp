#!/usr/bin/env python3
"""
Utility script to validate and clean up data in the ICP Leads sheet.

Usage:
    python cleanup_data.py              # Check for issues (dry run)
    python cleanup_data.py --fix        # Fix issues automatically
"""

import argparse
import re
from integrations import GoogleSheetsClient
from processors import ICPFilter
from utils import get_logger

logger = get_logger("cleanup")

# Invalid company name patterns
INVALID_COMPANY_NAMES = {
    # Common words
    "the", "a", "an", "this", "that", "here", "there",
    "how", "why", "what", "when", "where", "who", "which",

    # Generic business terms
    "ai", "startup", "startups", "company", "companies", "firm",
    "business", "venture", "capital", "fund", "funding",

    # Nationalities
    "indian", "chinese", "american", "european", "asian",
    "british", "german", "french", "japanese", "korean", "israeli",
    "us", "uk", "eu",

    # Cities and locations
    "san", "new", "los", "silicon", "valley", "bay", "area",
    "francisco", "york", "angeles", "boston", "seattle", "austin",
    "london", "berlin", "paris", "tokyo", "beijing", "mumbai",
    "amsterdam", "stockholm", "singapore", "toronto", "chicago",
    "tel", "aviv",

    # People names
    "musk", "bezos", "zuckerberg", "altman", "andreessen", "horowitz",

    # News words
    "report", "reports", "news", "update", "latest", "breaking",

    # Specific false positives
    "vibe", "emergent", "humans&", "converge", "bio", "superorganism", "ivo",
}


def validate_company_name(name: str) -> tuple[bool, str]:
    """Validate a company name and return (is_valid, reason)."""
    if not name or not name.strip():
        return False, "Empty name"

    name_lower = name.lower().strip()

    # Check against invalid names
    if name_lower in INVALID_COMPANY_NAMES:
        return False, f"Invalid name: '{name}' is a common word"

    # Check if too short
    if len(name) < 2:
        return False, f"Name too short: '{name}'"

    # Check if looks like a location pattern (e.g., "Hamburg-based", "SF-based")
    if re.search(r'^[A-Za-z]+-based$', name, re.IGNORECASE):
        return False, f"Looks like location: '{name}'"

    # All caps is OK for company names like "AXDRAFT", "D-ID", "IBM"
    # Only flag if it's a very long all-caps string (likely noise from headlines)
    if name.isupper() and len(name) > 10 and " " not in name:
        return False, f"Suspicious all caps: '{name}'"

    return True, ""


def validate_website(url: str) -> tuple[bool, str]:
    """Validate a website URL."""
    if not url:
        return True, ""  # Empty is OK

    url = url.strip()

    # Should start with http/https
    if not url.startswith(("http://", "https://")):
        return False, f"Invalid URL (no protocol): '{url}'"

    # Should have a domain
    if "." not in url:
        return False, f"Invalid URL (no domain): '{url}'"

    return True, ""


def validate_funding_amount(amount: str) -> tuple[bool, str]:
    """Validate funding amount format."""
    if not amount:
        return True, ""  # Empty is OK

    amount = amount.strip()

    # Should match $XM, $XB, or $X.XM format
    if not re.match(r'^\$[\d.]+[MBK]?$', amount, re.IGNORECASE):
        return False, f"Invalid funding format: '{amount}'"

    return True, ""


def validate_funding_date(date: str) -> tuple[bool, str]:
    """Validate funding date format."""
    if not date:
        return True, ""  # Empty is OK

    date = date.strip()

    # Valid formats: YYYY-MM-DD, YC batch (W24, S23), Season Year
    valid_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',  # YYYY-MM-DD
        r'^[WS]\d{2}$',  # W24, S23
        r'^(Winter|Spring|Summer|Fall) \d{4}$',  # Season Year
    ]

    if not any(re.match(p, date) for p in valid_patterns):
        return False, f"Invalid date format: '{date}'"

    return True, ""


def validate_location(location: str) -> tuple[bool, str]:
    """Validate and potentially clean location."""
    if not location:
        return True, ""

    # Check for suspicious patterns
    if re.match(r'^[A-Z]{2,3}$', location):  # Just country code
        return False, f"Likely country code: '{location}'"

    return True, ""


def validate_row(row: list, row_idx: int) -> list[dict]:
    """Validate a single row and return list of issues."""
    issues = []

    # Ensure row has enough columns
    row = row + [""] * (16 - len(row))

    company_name = row[0]
    website = row[1]
    funding_amount = row[2]
    funding_date = row[3]
    location = row[5]
    industry_tags = row[6]
    source_url = row[9]
    icp_tag = row[12]
    icp_score = row[13]

    # Validate company name
    valid, reason = validate_company_name(company_name)
    if not valid:
        issues.append({
            "row": row_idx,
            "column": "Company Name",
            "value": company_name,
            "issue": reason,
            "action": "remove_row"
        })

    # Validate website
    valid, reason = validate_website(website)
    if not valid:
        issues.append({
            "row": row_idx,
            "column": "Website",
            "value": website,
            "issue": reason,
            "action": "clear_cell"
        })

    # Validate funding amount
    valid, reason = validate_funding_amount(funding_amount)
    if not valid:
        issues.append({
            "row": row_idx,
            "column": "Funding Amount",
            "value": funding_amount,
            "issue": reason,
            "action": "clear_cell"
        })

    # Validate funding date
    valid, reason = validate_funding_date(funding_date)
    if not valid:
        issues.append({
            "row": row_idx,
            "column": "Funding Date",
            "value": funding_date,
            "issue": reason,
            "action": "flag"  # Don't auto-fix dates
        })

    # Check for missing critical data
    if not source_url:
        issues.append({
            "row": row_idx,
            "column": "Source URL",
            "value": "",
            "issue": "Missing source URL",
            "action": "flag"
        })

    # Check ICP tag consistency
    if icp_score and icp_tag:
        try:
            score = int(icp_score)
            expected_tag = ""
            if score >= 80:
                expected_tag = "🔥 PERFECT FIT"
            elif score >= 65:
                expected_tag = "⭐ STRONG FIT"
            elif score >= 50:
                expected_tag = "✅ GOOD FIT"
            elif score >= 35:
                expected_tag = "📊 POTENTIAL"
            elif score >= 20:
                expected_tag = "🔍 REVIEW"
            else:
                expected_tag = "❄️ LOW FIT"

            if icp_tag != expected_tag:
                issues.append({
                    "row": row_idx,
                    "column": "ICP Tag",
                    "value": icp_tag,
                    "issue": f"Tag mismatch (score {score} should be '{expected_tag}')",
                    "action": "fix_tag"
                })
        except ValueError:
            issues.append({
                "row": row_idx,
                "column": "ICP Score",
                "value": icp_score,
                "issue": "Invalid score (not a number)",
                "action": "recalculate"
            })

    return issues


def main():
    parser = argparse.ArgumentParser(description="Validate and clean ICP Leads data")
    parser.add_argument("--fix", action="store_true", help="Fix issues automatically")
    args = parser.parse_args()

    client = GoogleSheetsClient()

    print("\n" + "=" * 60)
    print("ICP LEADS DATA VALIDATION")
    print("=" * 60)

    # Get all data
    print("\nFetching data from Google Sheet...")
    result = client.service.spreadsheets().values().get(
        spreadsheetId=client.sheet_id,
        range="Sheet1!A:P"
    ).execute()

    values = result.get("values", [])
    if len(values) < 2:
        print("No data found.")
        return

    headers = values[0]
    rows = values[1:]
    print(f"Found {len(rows)} rows to validate")

    # Validate all rows
    all_issues = []
    rows_to_remove = set()

    for idx, row in enumerate(rows):
        row_issues = validate_row(row, idx + 2)  # +2 for header and 1-indexed
        all_issues.extend(row_issues)

        # Track rows to remove
        for issue in row_issues:
            if issue["action"] == "remove_row":
                rows_to_remove.add(idx)

    # Report issues
    print("\n" + "-" * 60)
    print("VALIDATION RESULTS")
    print("-" * 60)

    if not all_issues:
        print("\n✅ No issues found! Data looks clean.")
        return

    print(f"\n⚠️  Found {len(all_issues)} issues:")

    # Group by issue type
    by_action = {}
    for issue in all_issues:
        action = issue["action"]
        if action not in by_action:
            by_action[action] = []
        by_action[action].append(issue)

    for action, issues in by_action.items():
        print(f"\n  {action}: {len(issues)} issues")
        for issue in issues[:5]:  # Show first 5
            print(f"    Row {issue['row']}: {issue['column']} - {issue['issue']}")
        if len(issues) > 5:
            print(f"    ... and {len(issues) - 5} more")

    # Summary of rows to remove
    if rows_to_remove:
        print(f"\n🗑️  Rows to remove: {len(rows_to_remove)}")
        for idx in sorted(rows_to_remove)[:10]:
            print(f"    Row {idx + 2}: {rows[idx][0]}")
        if len(rows_to_remove) > 10:
            print(f"    ... and {len(rows_to_remove) - 10} more")

    # Fix issues if requested
    if args.fix:
        print("\n" + "-" * 60)
        print("FIXING ISSUES")
        print("-" * 60)

        # Remove bad rows
        if rows_to_remove:
            print(f"\nRemoving {len(rows_to_remove)} invalid rows...")
            clean_rows = [row for idx, row in enumerate(rows) if idx not in rows_to_remove]

            # Clear and rewrite
            client.service.spreadsheets().values().clear(
                spreadsheetId=client.sheet_id,
                range="Sheet1!A2:P"
            ).execute()

            if clean_rows:
                client.service.spreadsheets().values().update(
                    spreadsheetId=client.sheet_id,
                    range="Sheet1!A2:P",
                    valueInputOption="RAW",
                    body={"values": clean_rows}
                ).execute()

            print(f"  Removed {len(rows_to_remove)} rows, {len(clean_rows)} remaining")

        # Fix ICP tags
        tag_fixes = [i for i in all_issues if i["action"] == "fix_tag" and i["row"] - 2 not in rows_to_remove]
        if tag_fixes:
            print(f"\nFixing {len(tag_fixes)} ICP tag mismatches...")
            # Re-tag all leads
            icp_filter = ICPFilter()

            # Get updated data
            result = client.service.spreadsheets().values().get(
                spreadsheetId=client.sheet_id,
                range="Sheet1!A:P"
            ).execute()
            values = result.get("values", [])
            rows = values[1:]

            updates = []
            for idx, row in enumerate(rows):
                row = row + [""] * (16 - len(row))
                lead = {
                    "company_name": row[0],
                    "website": row[1],
                    "funding_amount": row[2],
                    "funding_date": row[3],
                    "funding_stage": row[4],
                    "location": row[5],
                    "industry_tags": row[6],
                }
                tagged = icp_filter.tag_lead(lead)

                row_num = idx + 2
                updates.append({"range": f"Sheet1!M{row_num}", "values": [[tagged["icp_tag"]]]})
                updates.append({"range": f"Sheet1!N{row_num}", "values": [[str(tagged["icp_score"])]]})
                updates.append({"range": f"Sheet1!O{row_num}", "values": [[tagged["icp_signals"]]]})

            # Batch update
            for i in range(0, len(updates), 100):
                batch = updates[i:i + 100]
                client.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=client.sheet_id,
                    body={"valueInputOption": "RAW", "data": batch}
                ).execute()

            print(f"  Updated ICP tags for {len(rows)} rows")

        print("\n✅ Fixes applied!")

    else:
        print("\n" + "=" * 60)
        print("DRY RUN - No changes made")
        print("Run with --fix to apply fixes")
        print("=" * 60)


if __name__ == "__main__":
    main()
