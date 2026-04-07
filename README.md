# ICP Scraper

Automatically find AI startups with recent funding and add them to Google Sheets.

## ICP (Ideal Customer Profile)

- **Target**: AI startups that raised $5M+ in funding
- **Locations**: SF, NY, London, Berlin, Paris, Amsterdam
- **Trigger**: Recent funding announcements (within 30 days)
- **Goal**: Identify companies in the "momentum window" after funding

## Quick Start

### 1. Install Dependencies

```bash
cd icp-scraper
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set Up Google Sheets API

#### Create Google Cloud Project
1. Go to https://console.cloud.google.com/
2. Click "Select a Project" → "New Project"
3. Name it "icp-scraper" → Create

#### Enable APIs
1. Go to "APIs & Services" → "Library"
2. Search and enable **Google Sheets API**
3. Also enable **Google Drive API**

#### Create Service Account
1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "Service Account"
3. Name: "icp-scraper-bot" → Create
4. Skip optional permissions → Done
5. Click on the service account you created
6. Go to "Keys" tab → "Add Key" → "Create new key" → JSON
7. Save the downloaded file as `credentials.json` in this folder

#### Create & Share Google Sheet
1. Create a new Google Sheet, name it "ICP Leads"
2. Open `credentials.json` and copy the `client_email` value
3. Share the Google Sheet with that email (give Editor access)
4. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/[THIS_IS_YOUR_SHEET_ID]/edit
   ```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
```
GOOGLE_SHEET_ID=your_sheet_id_here
```

### 4. Run the Scraper

```bash
# Run once
python main.py

# Run as daemon (daily at 10:00am IST)
python main.py --daemon
```

### 5. Set Up Daily Automation (Optional)

```bash
./setup_cron.sh
```

This will set up either a cron job or launchd task to run daily at 10:00am IST.

### Run While Laptop Is Off (Cloud Scheduler)

For fully automatic runs (no laptop required), deploy the cron service in
`render.yaml`:

- Service: `icp-scraper-daily`
- Schedule: `30 4 * * *` (UTC) = **10:00 AM IST daily**
- Command: `bash start_scraper.sh`

Set these environment variables for the cron service in Render Dashboard:

- `SLACK_WEBHOOK_URL` (required for Slack messages)
- Any other keys your scrapers need

## Data Sources

| Source | Type | Reliability | Notes |
|--------|------|-------------|-------|
| TechCrunch | RSS | High | Best for recent funding news |
| Crunchbase | Web scrape | Medium | May be blocked; consider API |

### Improving Data Quality

For more reliable Crunchbase data, consider:
- **Crunchbase Basic API** ($99/month) - Clean, reliable data
- Set `CRUNCHBASE_API_KEY` in `.env` (requires code modification)

## Google Sheet Columns

| Column | Description |
|--------|-------------|
| Company Name | Startup name |
| Website | Company URL |
| Funding Amount | Latest round amount |
| Funding Date | When funding was announced |
| Funding Stage | Seed, Series A, etc. |
| Location | Company HQ |
| Industry Tags | AI, ML, etc. |
| Founders | Key founders |
| Investors | Lead investors |
| Source URL | Where we found them |
| Date Added | When added to sheet |
| Status | New/Contacted/Qualified |
| Notes | ICP score & your notes |

## Configuration

Edit `.env` to customize:

```bash
# Minimum funding threshold
MIN_FUNDING_AMOUNT=5000000  # $5M

# How far back to look
FUNDING_LOOKBACK_DAYS=30

# Target locations (comma-separated)
TARGET_LOCATIONS=San Francisco,New York,London,Berlin,Paris,Amsterdam

# AI keywords for filtering
AI_KEYWORDS=artificial intelligence,machine learning,AI,ML,deep learning,LLM

# Optional: Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx

# Optional: Slack @mention trigger (web app webhook)
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_TRIGGER_CHANNEL_ID=C0123456789
```

## Trigger Scrape From Slack (No Enterprise Needed)

If mention-based bot permissions are restricted in your workspace, use a slash
command instead (recommended fallback):

- Command: `/scrape`
- Endpoint: `https://<your-crm-domain>/webhooks/slack/command`

What it does:

- Runs the ICP scrape on demand
- Posts the final report in the same channel automatically

Setup:

1. Create a Slack app and install it to your workspace.
2. Enable **Slash Commands** and create `/scrape`.
3. Set Request URL to: `https://<your-crm-domain>/webhooks/slack/command`
4. Set these env vars on the CRM web service:
   - `SLACK_SIGNING_SECRET`
   - `SLACK_TRIGGER_CHANNEL_ID` (optional channel lock)

Optional mention trigger (if your workspace allows it):

- Mention text: `@codex scrape` or `@claude scrape`
- Endpoint: `https://<your-crm-domain>/webhooks/slack/events`
- Scopes: `app_mentions:read`, `chat:write`
- Env var: `SLACK_BOT_TOKEN`

## Project Structure

```
icp-scraper/
├── main.py                 # Entry point
├── config.py               # Configuration
├── requirements.txt        # Dependencies
├── .env                    # Your settings (create from .env.example)
├── credentials.json        # Google API credentials (you create this)
│
├── scrapers/
│   ├── base_scraper.py     # Base class with rate limiting
│   ├── techcrunch.py       # TechCrunch RSS scraper
│   └── crunchbase.py       # Crunchbase web scraper
│
├── processors/
│   └── icp_filter.py       # ICP filtering & scoring
│
├── integrations/
│   └── google_sheets.py    # Google Sheets API client
│
└── utils/
    └── logger.py           # Logging utilities
```

## Troubleshooting

### "Credentials file not found"
Make sure `credentials.json` is in the icp-scraper folder.

### "Permission denied" on Google Sheet
Share the sheet with the service account email from `credentials.json`.

### "No leads found"
- TechCrunch RSS might have fewer AI funding stories some days
- Crunchbase may be blocking requests - consider their API
- Check the log file for errors

### Rate limiting
The scraper includes built-in rate limiting. If you're getting blocked:
- Increase `REQUEST_DELAY_SECONDS` in `.env`
- Use a proxy (requires code modification)
