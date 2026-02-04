"""
Main website analyzer that orchestrates all extractors.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from .base_analyzer import BaseAnalyzer, AnalysisCache
from .extractors import (
    LastUpdatedExtractor,
    AestheticsExtractor,
    BrandExtractor,
    SocialPresenceExtractor,
)
from .screenshot import capture_screenshot, get_screenshot_capture
from .claude_vision import get_claude_analyzer
from config import config
from utils import get_logger

logger = get_logger(__name__)


class WebsiteAnalyzer(BaseAnalyzer):
    """
    Comprehensive website analyzer.
    Orchestrates all extractors and combines results.
    """

    def __init__(self, use_claude: bool = True, use_cache: bool = True):
        """
        Initialize the analyzer.

        Args:
            use_claude: Whether to use Claude Vision for aesthetics
            use_cache: Whether to use caching
        """
        super().__init__()
        self.use_claude = use_claude and get_claude_analyzer().is_available()
        self.use_cache = use_cache

        # Initialize extractors
        self.last_updated_extractor = LastUpdatedExtractor()
        self.aesthetics_extractor = AestheticsExtractor()
        self.brand_extractor = BrandExtractor()
        self.social_extractor = SocialPresenceExtractor(validate_links=True)

        if self.use_claude:
            logger.info("Claude Vision enabled for aesthetics analysis")
        else:
            logger.info("Using heuristics-only for aesthetics analysis")

    def analyze(self, url: str, company_name: str = "") -> dict:
        """
        Analyze a website URL.

        Args:
            url: Website URL to analyze
            company_name: Company name for brand matching

        Returns:
            Dictionary with all analysis results
        """
        if not url:
            return self._empty_result("No URL provided")

        # Normalize URL
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        domain = self.extract_domain(url)

        # Check cache
        if self.use_cache:
            cached = self.cache.get(domain)
            if cached:
                logger.debug(f"Cache hit for {domain}")
                return {
                    "last_updated": cached.get("last_updated", ""),
                    "update_confidence": cached.get("update_confidence", ""),
                    "aesthetics_score": cached.get("aesthetics_score", 0),
                    "aesthetics_notes": cached.get("aesthetics_notes", ""),
                    "brand_score": cached.get("brand_score", 0),
                    "brand_notes": cached.get("brand_notes", ""),
                    "social_links": cached.get("social_links", ""),
                    "social_score": cached.get("social_score", 0),
                    "analysis_date": cached.get("last_analyzed", "")[:10],
                    "analysis_status": cached.get("analysis_status", "Cached"),
                }

        # Fetch website
        logger.debug(f"Analyzing {url}")
        response = self.get(url)

        if not response:
            result = self._empty_result("Failed to fetch website")
            if self.use_cache:
                self.cache.set(domain, {**result, "analysis_status": "Failed"})
            return result

        html = response.text
        response_hash = self.hash_content(html)

        # Take screenshot for Claude analysis
        screenshot_path = None
        if self.use_claude:
            try:
                screenshot_path = capture_screenshot(url)
            except Exception as e:
                logger.debug(f"Screenshot failed for {url}: {e}")

        # Run all extractors
        try:
            # 1. Last updated
            last_updated, update_confidence = self.last_updated_extractor.extract(response, html)

            # 2. Aesthetics (with Claude if available)
            aesthetics_score, aesthetics_notes = self.aesthetics_extractor.extract(
                html, screenshot_path, use_claude=self.use_claude
            )

            # 3. Brand coherency
            brand_score, brand_notes = self.brand_extractor.extract(html, url, company_name)

            # 4. Social presence
            social_score, social_links = self.social_extractor.extract(html, self.session)

            result = {
                "last_updated": last_updated or "",
                "update_confidence": update_confidence,
                "aesthetics_score": aesthetics_score,
                "aesthetics_notes": aesthetics_notes,
                "brand_score": brand_score,
                "brand_notes": brand_notes,
                "social_links": social_links,
                "social_score": social_score,
                "analysis_date": datetime.now().strftime("%Y-%m-%d"),
                "analysis_status": "Complete",
            }

            # Cache result
            if self.use_cache:
                self.cache.set(domain, {
                    **result,
                    "response_hash": response_hash,
                    "raw_data": {
                        "url": url,
                        "company_name": company_name,
                    }
                })

            logger.info(f"Analyzed {domain}: aesthetics={aesthetics_score}, brand={brand_score}, social={social_score}")
            return result

        except Exception as e:
            logger.error(f"Analysis failed for {url}: {e}")
            return self._empty_result(f"Analysis error: {str(e)[:50]}")

    def analyze_batch(
        self,
        urls: list,
        company_names: list = None,
        skip_analyzed: bool = True,
        progress_callback=None
    ) -> list:
        """
        Analyze multiple URLs.

        Args:
            urls: List of URLs to analyze
            company_names: Optional list of company names (same order as urls)
            skip_analyzed: Skip URLs already in cache
            progress_callback: Optional callback(current, total) for progress

        Returns:
            List of analysis results (same order as urls)
        """
        results = []
        total = len(urls)

        for i, url in enumerate(urls):
            company_name = company_names[i] if company_names and i < len(company_names) else ""

            # Check cache if skipping analyzed
            if skip_analyzed and self.use_cache:
                domain = self.extract_domain(url) if url else ""
                if domain and self.cache.get(domain):
                    logger.debug(f"Skipping {domain} (cached)")
                    results.append(self.analyze(url, company_name))  # Will return cached
                    if progress_callback:
                        progress_callback(i + 1, total)
                    continue

            result = self.analyze(url, company_name)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results

    def _empty_result(self, reason: str = "") -> dict:
        """Return an empty result dictionary."""
        return {
            "last_updated": "",
            "update_confidence": "Low",
            "aesthetics_score": 0,
            "aesthetics_notes": reason or "Not analyzed",
            "brand_score": 0,
            "brand_notes": "",
            "social_links": "",
            "social_score": 0,
            "analysis_date": datetime.now().strftime("%Y-%m-%d"),
            "analysis_status": "Failed" if reason else "Not analyzed",
        }

    def calculate_website_score(self, analysis: dict) -> int:
        """
        Calculate composite website quality score.

        Scoring:
        - Last Updated: 20 points max
        - Aesthetics: 30 points max
        - Brand: 25 points max
        - Social: 25 points max

        Returns:
            Score 0-100
        """
        score = 0

        # Last Updated (0-20)
        last_updated = analysis.get("last_updated", "")
        confidence = analysis.get("update_confidence", "Low")
        if last_updated:
            from datetime import datetime
            try:
                update_date = datetime.strptime(last_updated[:10], "%Y-%m-%d")
                days_ago = (datetime.now() - update_date).days

                if days_ago <= 30:
                    score += 20
                elif days_ago <= 90:
                    score += 15
                elif days_ago <= 180:
                    score += 10
                elif days_ago <= 365:
                    score += 5
            except ValueError:
                pass
        elif confidence == "Low":
            score += 5  # Give some credit if we just couldn't detect

        # Aesthetics (0-30)
        aesthetics = analysis.get("aesthetics_score", 0)
        score += int(aesthetics * 3)  # Scale 1-10 to 3-30

        # Brand (0-25)
        brand = analysis.get("brand_score", 0)
        score += int(brand * 2.5)  # Scale 1-10 to 2.5-25

        # Social (0-25)
        social = analysis.get("social_score", 0)
        score += int(social * 2.5)  # Scale 1-10 to 2.5-25

        return min(100, max(0, score))

    def get_website_tag(self, score: int) -> str:
        """Get classification tag from score."""
        if score >= 80:
            return "Excellent Website"
        elif score >= 60:
            return "Good Website"
        elif score >= 40:
            return "Needs Improvement"
        elif score >= 20:
            return "Outdated Website"
        else:
            return "Poor/No Website"

    def close(self):
        """Clean up resources."""
        try:
            get_screenshot_capture().close_sync()
        except Exception:
            pass
