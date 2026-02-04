#!/usr/bin/env python3
"""
Utility script to tag existing leads in the ICP Leads sheet with ICP fit scores.

Usage:
    python tag_existing_leads.py              # Preview tags (dry run)
    python tag_existing_leads.py --apply      # Apply tags to sheet
"""

import argparse
from integrations import GoogleSheetsClient
from processors import ICPFilter
from utils import get_logger

logger = get_logger("tag_leads")


def main():
    parser = argparse.ArgumentParser(description="Tag existing leads with ICP fit scores")
    parser.add_argument("--apply", action="store_true", help="Apply tags to Google Sheet (default is dry run)")
    parser.add_argument("--min-score", type=int, default=0, help="Only show leads with score >= this value")

    args = parser.parse_args()

    client = GoogleSheetsClient()
    icp_filter = ICPFilter()

    print("\n" + "=" * 60)
    print("ICP LEAD TAGGING")
    print("=" * 60)

    # Get all existing leads from the sheet
    print("\nFetching existing leads from Google Sheet...")

    try:
        # Use the Google Sheets API directly
        result = client.service.spreadsheets().values().get(
            spreadsheetId=client.sheet_id,
            range="Sheet1!A:M"
        ).execute()

        values = result.get("values", [])
        if not values or len(values) < 2:
            print("No leads found in sheet.")
            return

        headers = values[0]
        all_records = []
        for row in values[1:]:
            # Pad row to match headers length
            row = row + [""] * (len(headers) - len(row))
            record = dict(zip(headers, row))
            all_records.append(record)

        print(f"Found {len(all_records)} existing leads")
    except Exception as e:
        logger.error(f"Failed to fetch leads: {e}")
        return

    if not all_records:
        print("No leads found in sheet.")
        return

    # Convert sheet records to lead format and tag them
    tagged_leads = []
    for record in all_records:
        lead = {
            "company_name": record.get("Company Name", ""),
            "website": record.get("Website", ""),
            "funding_amount": record.get("Funding Amount", ""),
            "funding_date": record.get("Funding Date", ""),
            "funding_stage": record.get("Funding Stage", ""),
            "location": record.get("Location", ""),
            "industry_tags": record.get("Industry Tags", ""),
            "founders": record.get("Founders", ""),
            "investors": record.get("Investors", ""),
            "source_url": record.get("Source URL", ""),
        }

        tagged_lead = icp_filter.tag_lead(lead)
        tagged_lead["row_index"] = all_records.index(record) + 2  # +2 for header and 1-indexed
        tagged_leads.append(tagged_lead)

    # Sort by score
    tagged_leads.sort(key=lambda x: x["icp_score"], reverse=True)

    # Filter by min score
    filtered_leads = [l for l in tagged_leads if l["icp_score"] >= args.min_score]

    # Show distribution
    print("\n" + "-" * 60)
    print("ICP FIT DISTRIBUTION")
    print("-" * 60)

    perfect = [l for l in tagged_leads if l["icp_score"] >= 80]
    strong = [l for l in tagged_leads if 65 <= l["icp_score"] < 80]
    good = [l for l in tagged_leads if 50 <= l["icp_score"] < 65]
    potential = [l for l in tagged_leads if 35 <= l["icp_score"] < 50]
    review = [l for l in tagged_leads if 20 <= l["icp_score"] < 35]
    low = [l for l in tagged_leads if l["icp_score"] < 20]

    print(f"  🔥 PERFECT FIT (80+):   {len(perfect):4d} leads")
    print(f"  ⭐ STRONG FIT (65-79):  {len(strong):4d} leads")
    print(f"  ✅ GOOD FIT (50-64):    {len(good):4d} leads")
    print(f"  📊 POTENTIAL (35-49):   {len(potential):4d} leads")
    print(f"  🔍 REVIEW (20-34):      {len(review):4d} leads")
    print(f"  ❄️ LOW FIT (<20):       {len(low):4d} leads")
    print("-" * 60)

    # Show top leads
    print("\n" + "-" * 60)
    print("TOP 20 LEADS BY ICP FIT")
    print("-" * 60)

    for i, lead in enumerate(filtered_leads[:20], 1):
        print(f"\n{i}. {lead['company_name']} - {lead['icp_tag']} (Score: {lead['icp_score']})")
        print(f"   Funding: {lead.get('funding_amount', 'N/A')} | Location: {lead.get('location', 'N/A')}")
        print(f"   Signals: {lead['icp_signals']}")

    # Apply tags if requested
    if args.apply:
        print("\n" + "-" * 60)
        print("APPLYING TAGS TO GOOGLE SHEET")
        print("-" * 60)

        # ICP columns: M (Tag), N (Score), O (Signals)
        # Column M = 13, N = 14, O = 15

        # Update ICP columns for each lead
        print(f"Updating {len(tagged_leads)} leads...")

        # Batch update for efficiency using Google Sheets API
        updates = []
        for lead in tagged_leads:
            row = lead["row_index"]
            # Update ICP Tag (column M)
            updates.append({
                "range": f"Sheet1!M{row}",
                "values": [[lead['icp_tag']]]
            })
            # Update ICP Score (column N)
            updates.append({
                "range": f"Sheet1!N{row}",
                "values": [[str(lead['icp_score'])]]
            })
            # Update ICP Signals (column O)
            updates.append({
                "range": f"Sheet1!O{row}",
                "values": [[lead['icp_signals']]]
            })

        # Update in batches of 100
        batch_size = 100
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            try:
                body = {
                    "valueInputOption": "RAW",
                    "data": batch
                }
                client.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=client.sheet_id,
                    body=body
                ).execute()
                print(f"  Updated {min(i + batch_size, len(updates))} / {len(updates)} cells")
            except Exception as e:
                logger.error(f"Failed to update batch: {e}")

        print(f"\nSuccessfully tagged {len(tagged_leads)} leads!")
    else:
        print("\n" + "=" * 60)
        print("DRY RUN - No changes made to sheet")
        print("Run with --apply to update the Notes column with ICP tags")
        print("=" * 60)


if __name__ == "__main__":
    main()
