"""
Website analysis extractors.
"""

from .last_updated import LastUpdatedExtractor
from .aesthetics import AestheticsExtractor
from .brand import BrandExtractor
from .social_presence import SocialPresenceExtractor

__all__ = [
    "LastUpdatedExtractor",
    "AestheticsExtractor",
    "BrandExtractor",
    "SocialPresenceExtractor",
]
