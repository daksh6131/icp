"""
Base analyzer class with caching and rate limiting.
"""

import hashlib
import json
import sqlite3
import time
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import config
from utils import get_logger

logger = get_logger(__name__)

# Cache database path
CACHE_DB_PATH = Path(__file__).parent.parent / "website_analysis.db"


class AnalysisCache:
    """SQLite-based cache for website analysis results."""

    def __init__(self, db_path: Path = CACHE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the cache database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS website_analysis (
                    domain TEXT PRIMARY KEY,
                    last_analyzed TIMESTAMP,
                    response_hash TEXT,
                    last_updated TEXT,
                    update_confidence TEXT,
                    aesthetics_score INTEGER,
                    aesthetics_notes TEXT,
                    brand_score INTEGER,
                    brand_notes TEXT,
                    social_links TEXT,
                    social_score INTEGER,
                    analysis_status TEXT,
                    raw_data JSON
                )
            """)
            conn.commit()

    def get(self, domain: str, ttl_days: int = 7) -> Optional[dict]:
        """
        Get cached analysis for a domain.
        Returns None if not found or expired.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM website_analysis WHERE domain = ?",
                (domain,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            # Check if expired
            last_analyzed = datetime.fromisoformat(row["last_analyzed"])
            if datetime.now() - last_analyzed > timedelta(days=ttl_days):
                logger.debug(f"Cache expired for {domain}")
                return None

            return dict(row)

    def set(self, domain: str, analysis: dict):
        """Store analysis results in cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO website_analysis
                (domain, last_analyzed, response_hash, last_updated, update_confidence,
                 aesthetics_score, aesthetics_notes, brand_score, brand_notes,
                 social_links, social_score, analysis_status, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                domain,
                datetime.now().isoformat(),
                analysis.get("response_hash", ""),
                analysis.get("last_updated", ""),
                analysis.get("update_confidence", ""),
                analysis.get("aesthetics_score", 0),
                analysis.get("aesthetics_notes", ""),
                analysis.get("brand_score", 0),
                analysis.get("brand_notes", ""),
                analysis.get("social_links", ""),
                analysis.get("social_score", 0),
                analysis.get("analysis_status", ""),
                json.dumps(analysis.get("raw_data", {}))
            ))
            conn.commit()

    def clear(self, domain: str = None):
        """Clear cache for a domain or all domains."""
        with sqlite3.connect(self.db_path) as conn:
            if domain:
                conn.execute("DELETE FROM website_analysis WHERE domain = ?", (domain,))
            else:
                conn.execute("DELETE FROM website_analysis")
            conn.commit()


class BaseAnalyzer(ABC):
    """Abstract base class for website analyzers."""

    def __init__(self):
        self.session = self._create_session()
        self.last_request_time = 0
        self.cache = AnalysisCache()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        })

        return session

    def _rate_limit(self, delay: float = None):
        """Enforce rate limiting between requests."""
        if delay is None:
            delay = getattr(config, "ANALYSIS_REQUEST_DELAY", 2.5)

        elapsed = time.time() - self.last_request_time
        delay = delay + random.uniform(0, 0.5)

        if elapsed < delay:
            sleep_time = delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a rate-limited GET request."""
        self._rate_limit()

        try:
            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.debug(f"Request failed for {url}: {e}")
            return None

    def head(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make a rate-limited HEAD request."""
        self._rate_limit(delay=0.5)  # Faster for HEAD requests

        try:
            response = self.session.head(url, timeout=15, allow_redirects=True, **kwargs)
            return response
        except requests.RequestException as e:
            logger.debug(f"HEAD request failed for {url}: {e}")
            return None

    def extract_domain(self, url: str) -> str:
        """Extract domain from a URL."""
        if not url:
            return ""
        url = url.lower().strip()
        for prefix in ["https://", "http://", "www."]:
            if url.startswith(prefix):
                url = url[len(prefix):]
        return url.split("/")[0].split("?")[0]

    def hash_content(self, content: str) -> str:
        """Create a hash of content for change detection."""
        return hashlib.md5(content.encode()).hexdigest()[:16]

    @abstractmethod
    def analyze(self, url: str) -> dict:
        """
        Analyze a website URL.
        Returns a dictionary with analysis results.
        """
        pass
