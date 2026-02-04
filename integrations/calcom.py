"""
Cal.com API integration for syncing booking data to CRM.
"""

import requests
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class CalcomClient:
    """Client for Cal.com API v2."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.CALCOM_API_KEY
        self.base_url = config.CALCOM_API_BASE_URL
        self.webhook_secret = config.CALCOM_WEBHOOK_SECRET

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "cal-api-version": "2024-08-13"
        }

    def get_bookings(self, since_date: datetime = None, status: str = "upcoming", event_type_slug: str = "discovery") -> List[Dict]:
        """
        Fetch bookings from Cal.com API.

        Args:
            since_date: Only fetch bookings after this date (default: 30 days ago)
            status: Filter by status - 'upcoming', 'recurring', 'past', 'cancelled', 'unconfirmed'
            event_type_slug: Only return bookings for this event type (default: 'discovery')

        Returns:
            List of booking dictionaries
        """
        if not self.api_key:
            logger.error("Cal.com API key not configured")
            return []

        if since_date is None:
            since_date = datetime.now() - timedelta(days=30)

        params = {
            "status": status,
            "afterStart": since_date.strftime("%Y-%m-%dT00:00:00Z"),
        }

        try:
            response = requests.get(
                f"{self.base_url}/bookings",
                headers=self._get_headers(),
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                bookings = data.get("data", [])

                # Filter by event type slug (only discovery calls)
                if event_type_slug:
                    bookings = [
                        b for b in bookings
                        if b.get("eventType", {}).get("slug") == event_type_slug
                    ]

                logger.info(f"Fetched {len(bookings)} {event_type_slug} bookings from Cal.com")
                return bookings
            else:
                logger.error(f"Cal.com API error: {response.status_code} - {response.text}")
                return []

        except requests.RequestException as e:
            logger.error(f"Cal.com API request failed: {e}")
            return []

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify Cal.com webhook HMAC-SHA256 signature.

        Args:
            payload: Raw request body bytes
            signature: X-Cal-Signature-256 header value

        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured, skipping verification")
            return True

        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected}", signature)

    def parse_booking_to_lead_data(self, booking: Dict) -> Dict:
        """
        Convert Cal.com booking data to CRM lead format.

        Args:
            booking: Cal.com booking object

        Returns:
            Dictionary with lead field mappings
        """
        attendees = booking.get("attendees", [])
        attendee = attendees[0] if attendees else {}

        # Extract custom form responses from bookingFieldsResponses
        responses = booking.get("bookingFieldsResponses", {}) or {}
        metadata = booking.get("metadata", {}) or {}

        # Get company name from form field "title" (your discovery form uses this)
        company_name = (
            responses.get("title") or  # Your form's company field
            responses.get("company") or
            responses.get("companyName") or
            metadata.get("company") or
            ""
        )

        # Get website from "current-website" field
        website = (
            responses.get("current-website") or
            responses.get("website") or
            responses.get("companyWebsite") or
            metadata.get("website") or
            ""
        )

        # Normalize website URL
        if website and not website.startswith(("http://", "https://")):
            website = f"https://{website}"

        # Get notes/description
        notes = responses.get("notes") or booking.get("description") or ""

        # Get budget info if available
        budget = responses.get("Project-Budget") or ""
        if budget:
            notes = f"Budget: {budget}\n{notes}".strip()

        # Get classification/needs
        classification = responses.get("classification", [])
        if classification:
            needs = ", ".join(classification) if isinstance(classification, list) else classification
            notes = f"Needs: {needs}\n{notes}".strip()

        return {
            "company_name": company_name,
            "website": website,
            "attendee_email": attendee.get("email", ""),
            "attendee_name": attendee.get("name", ""),
            "calcom_booking_id": booking.get("uid") or str(booking.get("id", "")),
            "booking_date": booking.get("start", "") or booking.get("startTime", ""),
            "booking_title": booking.get("title", "Discovery Call"),
            "notes": notes,
            "location": booking.get("location", ""),
            "source_channel": responses.get("How-did-you-find-us", ""),
        }


def parse_webhook_event(payload: Dict) -> Optional[Dict]:
    """
    Parse Cal.com webhook payload for BOOKING_CREATED events.

    Args:
        payload: Webhook JSON payload

    Returns:
        Lead data dict or None if not a booking event
    """
    trigger = payload.get("triggerEvent")

    if trigger != "BOOKING_CREATED":
        logger.debug(f"Ignoring webhook event: {trigger}")
        return None

    booking = payload.get("payload", {})
    client = CalcomClient()

    return client.parse_booking_to_lead_data(booking)
