#!/usr/bin/env python3
"""
Utility script to remove duplicates and add duplicate protection to the ICP Leads sheet.

Usage:
    python cleanup_duplicates.py              # Check for duplicates
    python cleanup_duplicates.py --remove     # Remove duplicates
    python cleanup_duplicates.py --protect    # Add visual duplicate highlighting
    python cleanup_duplicates.py --all        # Do both
"""

import argparse
from integrations import GoogleSheetsClient
from utils import get_logger

logger = get_logger("cleanup")


def main():
    parser = argparse.ArgumentParser(description="Clean up duplicates in ICP Leads sheet")
    parser.add_argument("--remove", action="store_true", help="Remove duplicate entries")
    parser.add_argument("--protect", action="store_true", help="Add conditional formatting to highlight duplicates")
    parser.add_argument("--all", action="store_true", help="Remove duplicates and add protection")

    args = parser.parse_args()

    client = GoogleSheetsClient()

    # Always show current duplicate count
    print("\n" + "=" * 50)
    print("ICP LEADS DUPLICATE CHECK")
    print("=" * 50)

    counts = client.get_duplicate_count()
    print(f"\nTotal rows: {counts['total_rows']}")
    print(f"Duplicate company names: {counts['name_duplicates']}")
    print(f"Duplicate websites: {counts['website_duplicates']}")

    if args.all or args.remove:
        print("\n--- Removing Duplicates ---")
        removed = client.remove_duplicates()
        if removed > 0:
            print(f"Removed {removed} duplicate entries")

            # Show new counts
            new_counts = client.get_duplicate_count()
            print(f"\nAfter cleanup:")
            print(f"  Total rows: {new_counts['total_rows']}")
            print(f"  Duplicate names: {new_counts['name_duplicates']}")
            print(f"  Duplicate websites: {new_counts['website_duplicates']}")
        else:
            print("No duplicates to remove")

    if args.all or args.protect:
        print("\n--- Adding Duplicate Protection ---")
        if client.add_duplicate_protection():
            print("Added conditional formatting rules:")
            print("  - Red highlight: Duplicate company names (Column A)")
            print("  - Orange highlight: Duplicate websites (Column B)")
        else:
            print("Failed to add protection rules")

    if not (args.remove or args.protect or args.all):
        print("\nTo remove duplicates, run: python cleanup_duplicates.py --remove")
        print("To add visual protection, run: python cleanup_duplicates.py --protect")
        print("To do both, run: python cleanup_duplicates.py --all")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
