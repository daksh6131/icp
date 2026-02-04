"""
ICP (Ideal Customer Profile) filtering logic.
Filters leads based on funding amount, location, and AI focus.
"""

import re
from datetime import datetime, timedelta
from typing import Optional

from config import config
from utils import get_logger

logger = get_logger(__name__)


class ICPFilter:
    """
    Filters leads to match the Ideal Customer Profile:
    - AI startups
    - $5M+ funding
    - Located in SF, NY, or Europe
    - Recent funding (within lookback period)
    """

    def __init__(
        self,
        min_funding: Optional[int] = None,
        lookback_days: Optional[int] = None,
        target_locations: Optional[list[str]] = None,
        ai_keywords: Optional[list[str]] = None,
    ):
        self.min_funding = min_funding or config.MIN_FUNDING_AMOUNT
        self.lookback_days = lookback_days or config.FUNDING_LOOKBACK_DAYS
        self.target_locations = target_locations or config.TARGET_LOCATIONS
        self.ai_keywords = ai_keywords or config.AI_KEYWORDS

    def filter_leads(self, leads: list[dict]) -> list[dict]:
        """Filter a list of leads to match ICP criteria."""
        filtered = []
        for lead in leads:
            if self.matches_icp(lead):
                filtered.append(lead)
            else:
                logger.debug(f"Filtered out: {lead.get('company_name', 'Unknown')}")

        logger.info(f"ICP filter: {len(filtered)}/{len(leads)} leads passed")
        return filtered

    def matches_icp(self, lead: dict) -> bool:
        """Check if a single lead matches all ICP criteria."""
        checks = [
            ("AI focus", self._check_ai_focus(lead)),
            ("Funding amount", self._check_funding_amount(lead)),
            ("Location", self._check_location(lead)),
            ("Funding date", self._check_funding_date(lead)),
        ]

        # Log which checks failed
        failed = [name for name, passed in checks if not passed]
        if failed:
            logger.debug(
                f"{lead.get('company_name', 'Unknown')} failed: {', '.join(failed)}"
            )

        return all(passed for _, passed in checks)

    def _check_ai_focus(self, lead: dict) -> bool:
        """Check if the company is AI-focused."""
        # Combine relevant fields for checking
        text_to_check = " ".join([
            lead.get("company_name", ""),
            lead.get("industry_tags", ""),
            lead.get("source_url", ""),
        ]).lower()

        # If we explicitly tagged it as AI, it passes
        if "ai" in lead.get("industry_tags", "").lower():
            return True

        # Check for AI keywords
        return any(kw in text_to_check for kw in self.ai_keywords)

    def _check_funding_amount(self, lead: dict) -> bool:
        """Check if funding meets minimum threshold."""
        amount_str = lead.get("funding_amount", "")
        if not amount_str:
            # If no amount specified, we can't filter by it
            # Could be lenient here or strict - choosing lenient
            return True

        amount = self._parse_funding_amount(amount_str)
        if amount is None:
            return True  # Can't parse, be lenient

        return amount >= self.min_funding

    def _check_location(self, lead: dict) -> bool:
        """Check if the company is in a target location."""
        location = lead.get("location", "").lower()
        if not location:
            # No location data - be lenient
            return True

        # Check if any target location is mentioned
        for target in self.target_locations:
            if target.lower() in location:
                return True

        # Also check common variants
        location_aliases = {
            "san francisco": ["sf", "bay area", "silicon valley"],
            "new york": ["ny", "nyc", "manhattan"],
            "london": ["uk", "united kingdom"],
            "berlin": ["germany", "de"],
            "paris": ["france", "fr"],
            "amsterdam": ["netherlands", "nl"],
        }

        for main_loc, aliases in location_aliases.items():
            if main_loc in self.target_locations:
                if any(alias in location for alias in aliases):
                    return True

        return False

    def _check_funding_date(self, lead: dict) -> bool:
        """Check if funding is within the lookback period."""
        date_str = lead.get("funding_date", "")
        if not date_str:
            # No date - be lenient for now
            return True

        funding_date = self._parse_date(date_str)
        if not funding_date:
            return True

        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        return funding_date >= cutoff

    def _parse_funding_amount(self, text: str) -> Optional[int]:
        """Parse funding amount from various formats."""
        if not text:
            return None

        text = text.lower().replace(",", "").replace(" ", "")

        # Match patterns like "$25M", "$1.5B", "$25 million"
        match = re.search(r'\$?([\d.]+)\s*(m|million|b|billion|k|thousand)?', text)
        if not match:
            return None

        try:
            amount = float(match.group(1))
            unit = match.group(2) or ""

            if unit.startswith("b"):
                amount *= 1_000_000_000
            elif unit.startswith("m"):
                amount *= 1_000_000
            elif unit.startswith("k") or unit.startswith("t"):
                amount *= 1_000

            return int(amount)
        except (ValueError, TypeError):
            return None

    def _parse_date(self, text: str) -> Optional[datetime]:
        """Parse date from various formats."""
        if not text:
            return None

        # Common date formats
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%dT%H:%M:%S",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(text.strip(), fmt)
            except ValueError:
                continue

        # Try parsing relative dates like "2 days ago"
        relative_match = re.search(r'(\d+)\s*(day|week|month)s?\s*ago', text.lower())
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2)
            if unit == "day":
                return datetime.now() - timedelta(days=amount)
            elif unit == "week":
                return datetime.now() - timedelta(weeks=amount)
            elif unit == "month":
                return datetime.now() - timedelta(days=amount * 30)

        return None

    def score_lead(self, lead: dict) -> int:
        """
        Score a lead based on how well it matches ICP.
        Higher score = better match.
        Useful for prioritizing outreach.
        """
        score = 0

        # AI focus: +30 points
        if self._check_ai_focus(lead):
            score += 30

        # Funding amount scoring
        amount = self._parse_funding_amount(lead.get("funding_amount", ""))
        if amount:
            if amount >= 50_000_000:
                score += 40  # $50M+ is prime target
            elif amount >= 20_000_000:
                score += 30  # $20-50M great
            elif amount >= 10_000_000:
                score += 20  # $10-20M good
            elif amount >= 5_000_000:
                score += 10  # $5-10M acceptable

        # Location scoring
        location = lead.get("location", "").lower()
        prime_locations = ["san francisco", "sf", "new york", "ny"]
        good_locations = ["london", "berlin", "paris"]

        if any(loc in location for loc in prime_locations):
            score += 20
        elif any(loc in location for loc in good_locations):
            score += 10

        # Recency scoring
        funding_date = self._parse_date(lead.get("funding_date", ""))
        if funding_date:
            days_ago = (datetime.now() - funding_date).days
            if days_ago <= 7:
                score += 20  # Last week - hot lead
            elif days_ago <= 14:
                score += 15
            elif days_ago <= 30:
                score += 10

        return score

    def tag_lead(self, lead: dict) -> dict:
        """
        Tag a lead with ICP fit indicators based on your specific ICP:

        ICP Definition:
        - AI startups that raised $5M+ in funding
        - Located in SF, NY, or Europe
        - Technical founding teams with product-market fit
        - Facing "gradient sameness" / credibility gap for enterprise sales
        - In momentum window (recent funding announcement)

        Returns lead with added 'icp_tag' and 'icp_signals' fields.
        """
        signals = []
        score = 0

        # === 1. FUNDING AMOUNT (Max 30 points) ===
        amount = self._parse_funding_amount(lead.get("funding_amount", ""))
        funding_stage = lead.get("funding_stage", "").lower()

        if amount:
            if amount >= 75_000_000:
                signals.append("$75M+ (Scale-up)")
                score += 25
            elif amount >= 40_000_000:
                signals.append("$40M+ (Series B+)")
                score += 30  # Sweet spot
            elif amount >= 20_000_000:
                signals.append("$20M+ (Series A/B)")
                score += 28
            elif amount >= 10_000_000:
                signals.append("$10M+ (Series A)")
                score += 22
            elif amount >= 5_000_000:
                signals.append("$5M+ (Seed+)")
                score += 15
            else:
                signals.append("<$5M (Early)")
                score += 5
        elif "series b" in funding_stage or "series c" in funding_stage:
            signals.append("Series B/C (est. $20M+)")
            score += 25
        elif "series a" in funding_stage:
            signals.append("Series A (est. $10M+)")
            score += 20
        elif "yc" in funding_stage.lower():
            # YC companies - check batch for recency
            batch = lead.get("funding_date", "")
            if batch in ["W24", "S24", "W25", "S25"]:
                signals.append("Recent YC Batch")
                score += 18
            elif batch in ["W23", "S23"]:
                signals.append("YC 2023")
                score += 12
            else:
                signals.append("YC Alumni")
                score += 8

        # === 2. LOCATION (Max 20 points) ===
        location = lead.get("location", "").lower()

        # Prime locations (SF, NY)
        if any(loc in location for loc in ["san francisco", "sf", "bay area", "silicon valley", "palo alto"]):
            signals.append("SF/Bay Area")
            score += 20
        elif any(loc in location for loc in ["new york", "ny", "nyc", "manhattan", "brooklyn"]):
            signals.append("New York")
            score += 20
        # Good European locations
        elif any(loc in location for loc in ["london", "uk", "united kingdom"]):
            signals.append("London")
            score += 15
        elif any(loc in location for loc in ["berlin", "germany"]):
            signals.append("Berlin")
            score += 15
        elif any(loc in location for loc in ["paris", "france"]):
            signals.append("Paris")
            score += 12
        elif any(loc in location for loc in ["amsterdam", "netherlands"]):
            signals.append("Amsterdam")
            score += 12
        elif any(loc in location for loc in ["tel aviv", "israel"]):
            signals.append("Tel Aviv")
            score += 14
        # Other locations
        elif any(loc in location for loc in ["boston", "seattle", "austin", "la", "los angeles"]):
            signals.append("US Tech Hub")
            score += 10
        elif location and "remote" not in location:
            signals.append("Other Location")
            score += 5

        # === 3. AI/TECH FOCUS (Max 25 points) ===
        tags = lead.get("industry_tags", "").lower()
        company_name = lead.get("company_name", "").lower()

        # Generative AI / LLM (hottest category)
        if any(kw in tags for kw in ["generative ai", "llm", "gpt", "large language"]):
            signals.append("Generative AI/LLM")
            score += 25
        elif any(kw in company_name for kw in [".ai", "ai", "gpt"]):
            signals.append("AI-Native")
            score += 22
        # Core AI categories
        elif any(kw in tags for kw in ["artificial intelligence", "machine learning", "deep learning"]):
            signals.append("AI/ML Core")
            score += 20
        elif any(kw in tags for kw in ["computer vision", "nlp", "natural language"]):
            signals.append("AI Vertical")
            score += 18
        # B2B SaaS with AI
        elif any(kw in tags for kw in ["b2b", "saas", "enterprise"]) and "ai" in tags:
            signals.append("B2B AI SaaS")
            score += 22
        elif "ai" in tags:
            signals.append("AI-Related")
            score += 15

        # === 4. MOMENTUM / RECENCY (Max 15 points) ===
        funding_date = self._parse_date(lead.get("funding_date", ""))
        if funding_date:
            days_ago = (datetime.now() - funding_date).days
            if days_ago <= 7:
                signals.append("Funded This Week!")
                score += 15
            elif days_ago <= 14:
                signals.append("Funded Last 2 Weeks")
                score += 12
            elif days_ago <= 30:
                signals.append("Funded This Month")
                score += 10
            elif days_ago <= 60:
                signals.append("Funded Last 2 Months")
                score += 6
            elif days_ago <= 90:
                signals.append("Funded Last Quarter")
                score += 3

        # === 5. ENTERPRISE READINESS SIGNALS (Max 10 points) ===
        # These indicate they might face the "credibility gap" problem
        if any(kw in tags for kw in ["enterprise", "b2b", "sales"]):
            signals.append("Enterprise Focus")
            score += 8
        if any(kw in tags for kw in ["api", "developer tools", "infrastructure"]):
            signals.append("Technical Product")
            score += 5
        if any(kw in tags for kw in ["healthcare", "fintech", "legal", "security"]):
            signals.append("Regulated Industry")
            score += 7  # Higher need for credibility

        # === CALCULATE ICP TAG ===
        if score >= 80:
            icp_tag = "🔥 PERFECT FIT"
        elif score >= 65:
            icp_tag = "⭐ STRONG FIT"
        elif score >= 50:
            icp_tag = "✅ GOOD FIT"
        elif score >= 35:
            icp_tag = "📊 POTENTIAL"
        elif score >= 20:
            icp_tag = "🔍 REVIEW"
        else:
            icp_tag = "❄️ LOW FIT"

        # Add to lead
        lead["icp_tag"] = icp_tag
        lead["icp_score"] = score
        lead["icp_signals"] = " | ".join(signals) if signals else "No signals"

        return lead

    def tag_and_filter_leads(self, leads: list[dict], min_score: int = 0) -> list[dict]:
        """Tag all leads and optionally filter by minimum score."""
        tagged = []
        for lead in leads:
            tagged_lead = self.tag_lead(lead)
            if tagged_lead["icp_score"] >= min_score:
                tagged.append(tagged_lead)

        # Sort by score descending
        tagged.sort(key=lambda x: x["icp_score"], reverse=True)

        logger.info(f"Tagged {len(tagged)} leads. Score distribution:")
        perfect = sum(1 for l in tagged if l["icp_score"] >= 80)
        strong = sum(1 for l in tagged if 65 <= l["icp_score"] < 80)
        good = sum(1 for l in tagged if 50 <= l["icp_score"] < 65)
        potential = sum(1 for l in tagged if 35 <= l["icp_score"] < 50)
        review = sum(1 for l in tagged if 20 <= l["icp_score"] < 35)
        low = sum(1 for l in tagged if l["icp_score"] < 20)

        logger.info(f"  🔥 Perfect Fit (80+): {perfect}")
        logger.info(f"  ⭐ Strong Fit (65-79): {strong}")
        logger.info(f"  ✅ Good Fit (50-64): {good}")
        logger.info(f"  📊 Potential (35-49): {potential}")
        logger.info(f"  🔍 Review (20-34): {review}")
        logger.info(f"  ❄️ Low Fit (<20): {low}")

        return tagged
