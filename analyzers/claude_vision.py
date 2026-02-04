"""
Claude Vision API integration for website visual analysis.
"""

import base64
from pathlib import Path
from typing import Optional

from config import config
from utils import get_logger

logger = get_logger(__name__)


class ClaudeVisionAnalyzer:
    """Analyzes website screenshots using Claude Vision API."""

    ANALYSIS_PROMPT = """Analyze this website screenshot and provide a professional assessment.

Score each category from 1-10 and provide brief notes:

1. **Design Modernity** (1-10): How modern and current does the design feel?
2. **Professionalism** (1-10): Does it look like a legitimate, professional company?
3. **Visual Hierarchy** (1-10): Is information well-organized and easy to scan?
4. **Color Usage** (1-10): Are colors appealing and appropriate?
5. **Typography** (1-10): Is text readable and typography well-chosen?
6. **Overall Polish** (1-10): General quality and attention to detail?

Respond in this exact JSON format:
{
    "design_modernity": 8,
    "professionalism": 7,
    "visual_hierarchy": 8,
    "color_usage": 7,
    "typography": 8,
    "overall_polish": 7,
    "average_score": 7.5,
    "notes": "Brief 1-2 sentence summary of strengths and weaknesses"
}

Only respond with the JSON, no other text."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or getattr(config, "ANTHROPIC_API_KEY", "")
        self._client = None

    @property
    def client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in config or environment")
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def analyze_screenshot(self, screenshot_path: Path) -> Optional[dict]:
        """
        Analyze a website screenshot using Claude Vision.

        Args:
            screenshot_path: Path to the screenshot image

        Returns:
            Dictionary with scores and notes, or None if failed
        """
        if not screenshot_path or not screenshot_path.exists():
            logger.debug(f"Screenshot not found: {screenshot_path}")
            return None

        try:
            # Read and encode the image
            with open(screenshot_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            # Determine media type
            suffix = screenshot_path.suffix.lower()
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }.get(suffix, "image/png")

            # Call Claude API
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": self.ANALYSIS_PROMPT,
                            }
                        ],
                    }
                ],
            )

            # Parse response
            response_text = response.content[0].text.strip()

            # Extract JSON from response
            import json
            try:
                # Try to parse directly
                result = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code block
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(1))
                else:
                    logger.error(f"Failed to parse Claude response: {response_text[:200]}")
                    return None

            logger.debug(f"Claude analysis: score={result.get('average_score')}")
            return result

        except Exception as e:
            logger.error(f"Claude Vision analysis failed: {e}")
            return None

    def is_available(self) -> bool:
        """Check if Claude Vision is available (API key set)."""
        return bool(self.api_key)


# Global instance
_claude_analyzer = None


def get_claude_analyzer() -> ClaudeVisionAnalyzer:
    """Get or create a global ClaudeVisionAnalyzer instance."""
    global _claude_analyzer
    if _claude_analyzer is None:
        _claude_analyzer = ClaudeVisionAnalyzer()
    return _claude_analyzer


def analyze_with_claude(screenshot_path: Path) -> Optional[dict]:
    """Convenience function to analyze a screenshot with Claude."""
    analyzer = get_claude_analyzer()
    if not analyzer.is_available():
        logger.debug("Claude Vision not available (no API key)")
        return None
    return analyzer.analyze_screenshot(screenshot_path)
