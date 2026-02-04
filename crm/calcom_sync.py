"""
Cal.com booking sync logic for CRM.
Syncs bookings to leads in the discovery_booked stage.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from crm.models import Lead, Activity, get_db
from integrations.calcom import CalcomClient
from utils.logger import get_logger

logger = get_logger(__name__)


def find_lead_by_email(email: str) -> Optional[Dict]:
    """Find an existing lead by attendee email."""
    if not email:
        return None

    conn = get_db()
    cursor = conn.execute(
        "SELECT * FROM leads WHERE attendee_email = ? OR website LIKE ? LIMIT 1",
        (email, f"%{email.split('@')[1]}%" if '@' in email else "")
    )
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def find_lead_by_booking_id(booking_id: str) -> Optional[Dict]:
    """Check if a booking has already been synced."""
    if not booking_id:
        return None

    conn = get_db()
    cursor = conn.execute(
        "SELECT * FROM leads WHERE calcom_booking_id = ? LIMIT 1",
        (booking_id,)
    )
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def update_lead_with_booking(lead_id: int, booking_data: Dict):
    """Update an existing lead with booking information."""
    conn = get_db()
    conn.execute("""
        UPDATE leads SET
            stage_post = 'discovery_booked',
            conversation_started_at = COALESCE(conversation_started_at, ?),
            calcom_booking_id = ?,
            booking_date = ?,
            attendee_email = COALESCE(attendee_email, ?),
            updated_at = ?
        WHERE id = ?
    """, (
        datetime.now().isoformat(),
        booking_data.get("calcom_booking_id"),
        booking_data.get("booking_date"),
        booking_data.get("attendee_email"),
        datetime.now().isoformat(),
        lead_id
    ))
    conn.commit()
    conn.close()

    # Log activity
    Activity.create(
        lead_id,
        "booking",
        f"Discovery call booked for {booking_data.get('booking_date', 'N/A')}"
    )

    logger.info(f"Updated lead {lead_id} with booking {booking_data.get('calcom_booking_id')}")


def create_lead_from_booking(booking_data: Dict) -> int:
    """Create a new lead from Cal.com booking data."""
    # Use company name from form, or extract from website domain, or use attendee name as last resort
    company_name = booking_data.get("company_name", "").strip()
    website = booking_data.get("website", "").strip()

    if not company_name and website:
        # Try to extract company name from website domain
        import re
        domain_match = re.search(r'(?:https?://)?(?:www\.)?([^/]+)', website)
        if domain_match:
            domain = domain_match.group(1)
            # Remove TLD and capitalize
            company_name = domain.split('.')[0].title()

    if not company_name:
        company_name = booking_data.get("attendee_name", "Unknown")

    lead_data = {
        "company_name": company_name,
        "website": website,
        "founders": booking_data.get("attendee_name", ""),
        "stage_pre": "research",
        "stage_post": "discovery_booked",
        "conversation_started_at": datetime.now().isoformat(),
        "calcom_booking_id": booking_data.get("calcom_booking_id"),
        "booking_date": booking_data.get("booking_date"),
        "attendee_email": booking_data.get("attendee_email"),
        "source": "calcom",
        "source_channel": booking_data.get("source_channel", ""),
        "priority": "high",  # Booked calls are high priority
        "notes": booking_data.get("notes", ""),
    }

    lead_id = Lead.create(lead_data)

    # Log activity
    Activity.create(
        lead_id,
        "booking",
        f"Lead created from Cal.com booking. Discovery call scheduled for {booking_data.get('booking_date', 'N/A')}"
    )

    logger.info(f"Created new lead {lead_id} from booking {booking_data.get('calcom_booking_id')}")
    return lead_id


def sync_booking(booking_data: Dict) -> Tuple[str, Optional[int]]:
    """
    Sync a single booking to the CRM.

    Returns:
        Tuple of (action, lead_id) where action is 'created', 'updated', or 'skipped'
    """
    booking_id = booking_data.get("calcom_booking_id")
    email = booking_data.get("attendee_email")

    # Check if already synced
    existing = find_lead_by_booking_id(booking_id)
    if existing:
        logger.debug(f"Booking {booking_id} already synced to lead {existing['id']}")
        return ("skipped", existing["id"])

    # Try to match by email
    lead = find_lead_by_email(email)

    if lead:
        update_lead_with_booking(lead["id"], booking_data)
        return ("updated", lead["id"])
    else:
        lead_id = create_lead_from_booking(booking_data)
        return ("created", lead_id)


def sync_calcom_bookings(since_days: int = 30) -> Dict:
    """
    Sync all recent Cal.com bookings to CRM.

    Args:
        since_days: Sync bookings from the last N days

    Returns:
        Summary dict with counts
    """
    client = CalcomClient()
    since_date = datetime.now() - timedelta(days=since_days)

    result = {
        "total": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Fetch upcoming and past bookings
    for status in ["upcoming", "past"]:
        bookings = client.get_bookings(since_date=since_date, status=status)

        for booking in bookings:
            result["total"] += 1

            try:
                booking_data = client.parse_booking_to_lead_data(booking)
                action, lead_id = sync_booking(booking_data)
                result[action] += 1

            except Exception as e:
                logger.error(f"Error syncing booking: {e}")
                result["errors"] += 1

    logger.info(f"Cal.com sync complete: {result}")
    return result


def handle_webhook_booking(payload: Dict) -> Tuple[str, Optional[int]]:
    """
    Handle a Cal.com webhook BOOKING_CREATED event.

    Args:
        payload: Webhook payload (already parsed)

    Returns:
        Tuple of (action, lead_id)
    """
    from integrations.calcom import parse_webhook_event

    booking_data = parse_webhook_event(payload)

    if not booking_data:
        return ("ignored", None)

    return sync_booking(booking_data)
