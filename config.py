"""
Configuration management for ICP Scraper.
Loads settings from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Google Sheets
    GOOGLE_SHEETS_CREDENTIALS_FILE = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

    # ICP Filter Settings
    MIN_FUNDING_AMOUNT = int(os.getenv("MIN_FUNDING_AMOUNT", "5000000"))
    FUNDING_LOOKBACK_DAYS = int(os.getenv("FUNDING_LOOKBACK_DAYS", "30"))

    # Target Locations
    TARGET_LOCATIONS = [
        loc.strip().lower()
        for loc in os.getenv(
            "TARGET_LOCATIONS",
            "San Francisco,New York,London,Berlin,Paris,Amsterdam,Remote"
        ).split(",")
    ]

    # AI Keywords for filtering
    AI_KEYWORDS = [
        kw.strip().lower()
        for kw in os.getenv(
            "AI_KEYWORDS",
            "artificial intelligence,machine learning,AI,ML,deep learning,LLM,GPT,neural network,computer vision,NLP"
        ).split(",")
    ]

    # Rate Limiting
    REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "2"))

    # User Agent for requests
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Notifications (optional)
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_TRIGGER_CHANNEL_ID = os.getenv("SLACK_TRIGGER_CHANNEL_ID", "")
    DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")

    # Data Sources
    TECHCRUNCH_RSS_URL = "https://techcrunch.com/tag/fundraising/feed/"
    TECHCRUNCH_AI_RSS_URL = "https://techcrunch.com/tag/artificial-intelligence/feed/"

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "icp_scraper.log")

    # Website Analysis
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANALYSIS_CACHE_FILE = os.getenv("ANALYSIS_CACHE_FILE", "website_analysis.db")
    ANALYSIS_CACHE_TTL_DAYS = int(os.getenv("ANALYSIS_CACHE_TTL_DAYS", "7"))
    ANALYSIS_BATCH_SIZE = int(os.getenv("ANALYSIS_BATCH_SIZE", "100"))
    ANALYSIS_REQUEST_DELAY = float(os.getenv("ANALYSIS_REQUEST_DELAY", "2.5"))

    # Cal.com Integration
    CALCOM_API_KEY = os.getenv("CALCOM_API_KEY", "")
    CALCOM_WEBHOOK_SECRET = os.getenv("CALCOM_WEBHOOK_SECRET", "")
    CALCOM_API_BASE_URL = os.getenv("CALCOM_API_BASE_URL", "https://api.cal.com/v2")


config = Config()
