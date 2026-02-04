"""
DM Generator - Creates personalized cold DMs using Claude AI.
Fetches LinkedIn profile and company website to personalize messages.
"""

import requests
from bs4 import BeautifulSoup
import anthropic
import re
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config


class DMGenerator:
    """Generates personalized cold DMs using AI."""

    def __init__(self):
        self.client = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }

    def _get_client(self):
        """Lazy initialization of Anthropic client."""
        if self.client is None:
            if not config.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        return self.client

    def fetch_linkedin_profile(self, linkedin_url: str) -> dict:
        """
        Fetch and parse a public LinkedIn profile.
        Returns structured data about the founder.
        """
        if not linkedin_url:
            return {'error': 'No LinkedIn URL provided', 'raw_content': None}

        try:
            response = requests.get(
                linkedin_url,
                headers=self.headers,
                timeout=15,
                allow_redirects=True
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract text content (LinkedIn often requires JS, but we try anyway)
            # Remove script and style elements
            for script in soup(["script", "style", "noscript"]):
                script.decompose()

            # Get text content
            text = soup.get_text(separator='\n', strip=True)

            # Try to extract structured data from meta tags
            name = None
            headline = None

            # Try og:title which often has "Name - Title"
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title_content = og_title.get('content', '')
                if ' - ' in title_content:
                    parts = title_content.split(' - ')
                    name = parts[0].strip()
                    headline = parts[1].strip() if len(parts) > 1 else None

            # Try description meta
            description = None
            og_desc = soup.find('meta', property='og:description')
            if og_desc:
                description = og_desc.get('content', '')

            # Limit raw content length
            raw_content = text[:5000] if text else None

            return {
                'name': name,
                'headline': headline,
                'about': description,
                'raw_content': raw_content,
                'url': linkedin_url
            }

        except requests.exceptions.RequestException as e:
            return {
                'error': f'Failed to fetch LinkedIn: {str(e)}',
                'raw_content': None,
                'url': linkedin_url
            }

    def fetch_company_website(self, website_url: str) -> dict:
        """
        Fetch and parse company website content.
        Returns key information about the company.
        """
        if not website_url:
            return {'error': 'No website URL provided', 'raw_content': None}

        # Ensure URL has protocol
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url

        try:
            response = requests.get(
                website_url,
                headers=self.headers,
                timeout=15,
                allow_redirects=True
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                script.decompose()

            # Get page title
            title = soup.title.string if soup.title else None

            # Try to get meta description
            description = None
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                description = meta_desc.get('content', '')

            # Get main text content
            text = soup.get_text(separator='\n', strip=True)

            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            text = '\n'.join(lines)

            # Limit content length
            raw_content = text[:6000] if text else None

            return {
                'title': title,
                'description': description,
                'raw_content': raw_content,
                'url': website_url
            }

        except requests.exceptions.RequestException as e:
            return {
                'error': f'Failed to fetch website: {str(e)}',
                'raw_content': None,
                'url': website_url
            }

    def generate_dm(self, lead_data: dict, linkedin_data: dict = None, website_data: dict = None) -> dict:
        """
        Generate a personalized cold DM using Claude.

        Args:
            lead_data: Lead information from database
            linkedin_data: Parsed LinkedIn profile data
            website_data: Parsed company website data

        Returns:
            dict with 'dm' (the generated message) and 'context' (what was used)
        """
        client = self._get_client()

        # Build context from available data
        founder_name = lead_data.get('founders') or (linkedin_data or {}).get('name') or 'the founder'
        company_name = lead_data.get('company_name', 'the company')
        industry = lead_data.get('industry_tags', '')

        # LinkedIn context
        linkedin_context = ""
        if linkedin_data and not linkedin_data.get('error'):
            if linkedin_data.get('headline'):
                linkedin_context += f"- Their role: {linkedin_data['headline']}\n"
            if linkedin_data.get('about'):
                linkedin_context += f"- LinkedIn bio: {linkedin_data['about'][:500]}\n"
            if linkedin_data.get('raw_content'):
                linkedin_context += f"- Additional LinkedIn info: {linkedin_data['raw_content'][:1000]}\n"

        # Website context
        website_context = ""
        if website_data and not website_data.get('error'):
            if website_data.get('description'):
                website_context += f"- Website description: {website_data['description']}\n"
            if website_data.get('raw_content'):
                website_context += f"- Website content: {website_data['raw_content'][:2000]}\n"

        # Build the prompt
        prompt = f"""You are helping craft a personalized, casual cold DM to reach out to a startup founder.

TARGET PERSON:
- Name: {founder_name}
- Company: {company_name}
- Industry: {industry or 'Tech startup'}

THEIR LINKEDIN PROFILE:
{linkedin_context if linkedin_context else "- No LinkedIn data available"}

THEIR COMPANY WEBSITE:
{website_context if website_context else "- No website data available"}

ADDITIONAL CONTEXT:
- Funding: {lead_data.get('funding_amount', 'Unknown')}
- Location: {lead_data.get('location', 'Unknown')}

YOUR TASK:
Write a short, casual cold DM (like a Twitter/X DM or LinkedIn message) to {founder_name}.

GUIDELINES:
1. Keep it under 280 characters ideally, max 400 characters
2. Be genuinely curious about something specific from their profile or company
3. Reference ONE specific thing you noticed (product, recent news, their background)
4. Sound like a real person, not a sales bot - be warm and casual
5. Don't be salesy or pitch anything directly
6. Don't use excessive emojis (0-1 max, only if natural)
7. End with a soft, open question - not a hard call-to-action
8. Don't mention "I saw your profile" or similar generic openers
9. Don't use phrases like "I'd love to" or "I was wondering if"
10. Be specific, not generic. The message should only work for THIS person.

Write ONLY the DM text, nothing else. No quotes, no explanation."""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            dm_text = response.content[0].text.strip()

            # Clean up any quotes that might have been added
            dm_text = dm_text.strip('"\'')

            return {
                'success': True,
                'dm': dm_text,
                'char_count': len(dm_text),
                'context_used': {
                    'had_linkedin': bool(linkedin_context),
                    'had_website': bool(website_context),
                    'founder_name': founder_name,
                    'company_name': company_name
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to generate DM: {str(e)}',
                'dm': None
            }

    def generate_full(self, lead_data: dict) -> dict:
        """
        Full pipeline: fetch LinkedIn, fetch website, generate DM.

        Args:
            lead_data: Lead dictionary with linkedin_url, website, etc.

        Returns:
            dict with dm, linkedin_data, website_data, and status
        """
        # Fetch LinkedIn profile
        linkedin_data = self.fetch_linkedin_profile(lead_data.get('linkedin_url'))

        # Fetch company website
        website_data = self.fetch_company_website(lead_data.get('website'))

        # Generate the DM
        result = self.generate_dm(lead_data, linkedin_data, website_data)

        return {
            'success': result.get('success', False),
            'dm': result.get('dm'),
            'char_count': result.get('char_count'),
            'error': result.get('error'),
            'linkedin_data': {
                'fetched': not linkedin_data.get('error'),
                'name': linkedin_data.get('name'),
                'headline': linkedin_data.get('headline'),
                'error': linkedin_data.get('error')
            },
            'website_data': {
                'fetched': not website_data.get('error'),
                'title': website_data.get('title'),
                'description': website_data.get('description'),
                'error': website_data.get('error')
            },
            'context_used': result.get('context_used', {})
        }


# Singleton instance
_generator = None

def get_dm_generator() -> DMGenerator:
    """Get or create the DM generator singleton."""
    global _generator
    if _generator is None:
        _generator = DMGenerator()
    return _generator
