"""
Flask CRM application for managing ICP leads with dual-tracker support.
"""

import hashlib
import hmac
import threading
import time
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for
from config import config
from crm.models import Lead, Activity, Task, PipelineStage, ScrapingSource, get_db, get_dashboard_data, close_db, reset_db_connection
from utils import get_logger

app = Flask(__name__)
app.secret_key = 'icp-crm-secret-key'
logger = get_logger("crm.app")


def _verify_slack_signature(payload: bytes, timestamp: str, signature: str) -> bool:
    """Verify Slack request signature (v0)."""
    if not config.SLACK_SIGNING_SECRET:
        return False
    if not timestamp or not signature:
        return False
    try:
        # Reject replayed requests older than 5 minutes.
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False

    basestring = f"v0:{timestamp}:{payload.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        config.SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


def _is_duplicate_slack_event(event_id: str) -> bool:
    """Best-effort dedupe for Slack retries."""
    if not event_id:
        return False
    now = time.time()
    cache = getattr(app, "_slack_event_cache", {})

    # Drop old IDs to keep memory bounded.
    expired = [eid for eid, ts in cache.items() if now - ts > 600]
    for eid in expired:
        cache.pop(eid, None)

    duplicate = event_id in cache
    cache[event_id] = now
    app._slack_event_cache = cache
    return duplicate


def _post_slack_message(channel: str, text: str, thread_ts: str = None) -> bool:
    """Post a message via Slack Web API chat.postMessage."""
    if not config.SLACK_BOT_TOKEN:
        logger.error("SLACK_BOT_TOKEN not configured; cannot send Slack reply")
        return False

    payload = {
        "channel": channel,
        "text": text,
        "mrkdwn": True,
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {config.SLACK_BOT_TOKEN}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=payload,
            timeout=15,
        )
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Slack chat.postMessage failed: {data}")
            return False
        return True
    except Exception as exc:
        logger.error(f"Slack chat.postMessage request failed: {exc}")
        return False


def _post_to_slack_response_url(response_url: str, text: str, in_channel: bool = False) -> bool:
    """Post a message to a Slack slash-command response_url."""
    if not response_url:
        return False

    payload = {
        "text": text,
        "mrkdwn": True,
        "response_type": "in_channel" if in_channel else "ephemeral",
    }
    try:
        resp = requests.post(response_url, json=payload, timeout=15)
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.error(f"Slack response_url request failed: {exc}")
        return False


def _format_slack_trigger_report(result: dict, dashboard_url: str = "") -> str:
    """Build a concise scrape report for Slack replies."""
    lines = [
        "*ICP scrape finished*",
        f"• Scraped: *{result.get('scraped', 0)}*",
        f"• Filtered: *{result.get('filtered', 0)}*",
        f"• Imported: *{result.get('imported', 0)}*",
        f"• Skipped: *{result.get('skipped', 0)}*",
        f"• Errors: *{result.get('errors', 0)}*",
    ]

    leads = (result.get("leads") or [])[:5]
    if leads:
        lines.append("\n*New Imports*")
        for lead in leads:
            lines.append(
                f"• {lead.get('company_name', 'Unknown')} "
                f"({lead.get('funding_amount', 'N/A')}) "
                f"{lead.get('icp_tag', '')}"
            )
    else:
        lines.append("\nNo new leads imported this run.")

    if dashboard_url:
        lines.append(f"\nDashboard: {dashboard_url}")

    return "\n".join(lines)


@app.teardown_appcontext
def teardown_db(exception=None):
    """Close database connection at the end of each request."""
    close_db()


@app.errorhandler(Exception)
def handle_exception(e):
    """Handle exceptions by resetting DB connection if needed."""
    if 'authorization denied' in str(e).lower() or 'database is locked' in str(e).lower():
        reset_db_connection()
    raise e


# ============== DASHBOARD ==============

@app.route('/')
def dashboard():
    """Main dashboard view - optimized with single DB call."""
    data = get_dashboard_data()

    return render_template('dashboard.html',
        stats=data['stats'],
        recent_leads=data['recent_leads'],
        recent_activities=data['recent_activities'],
        pending_tasks=data['pending_tasks'],
        stages=data['stages'],
        stages_pre=data['stages_pre'],
        stages_post=data['stages_post']
    )


# ============== LEADS ==============

@app.route('/leads')
def leads_list():
    """List all leads with filtering and sorting."""
    stage = request.args.get('stage', 'all')
    tracker = request.args.get('tracker', 'pre')  # pre or post
    search = request.args.get('search', '')
    source = request.args.get('source', 'all')
    enriched_range = request.args.get('enriched', 'all')
    sort = request.args.get('sort', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    page = int(request.args.get('page', 1))
    per_page = 50

    leads = Lead.get_all(
        stage=stage if stage != 'all' else None,
        tracker=tracker,
        search=search if search else None,
        source=source if source != 'all' else None,
        enriched_range=enriched_range if enriched_range != 'all' else None,
        sort=sort,
        sort_dir=sort_dir,
        limit=per_page,
        offset=(page - 1) * per_page
    )

    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()
    stats = Lead.get_stats()
    sources = Lead.get_sources()

    return render_template('leads.html',
        leads=leads,
        stages_pre=stages_pre,
        stages_post=stages_post,
        stages=stages_pre if tracker == 'pre' else stages_post,
        stats=stats,
        sources=sources,
        current_stage=stage,
        current_tracker=tracker,
        current_source=source,
        current_enriched_range=enriched_range,
        current_sort=sort,
        current_sort_dir=sort_dir,
        search=search,
        page=page
    )


@app.route('/leads/<int:lead_id>')
def lead_detail(lead_id):
    """Lead detail view."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return redirect(url_for('leads_list'))

    activities = Activity.get_for_lead(lead_id)
    tasks = Task.get_pending(lead_id)
    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()

    return render_template('lead_detail.html',
        lead=lead,
        activities=activities,
        tasks=tasks,
        stages_pre=stages_pre,
        stages_post=stages_post
    )


@app.route('/leads/<int:lead_id>/edit', methods=['GET', 'POST'])
def lead_edit(lead_id):
    """Edit lead."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return redirect(url_for('leads_list'))

    if request.method == 'POST':
        data = {
            'company_name': request.form.get('company_name'),
            'website': request.form.get('website'),
            'funding_amount': request.form.get('funding_amount'),
            'funding_stage': request.form.get('funding_stage'),
            'location': request.form.get('location'),
            'industry_tags': request.form.get('industry_tags'),
            'founders': request.form.get('founders'),
            'stage': request.form.get('stage'),
            'stage_pre': request.form.get('stage_pre'),
            'stage_post': request.form.get('stage_post'),
            'priority': request.form.get('priority'),
        }
        Lead.update(lead_id, data)
        return redirect(url_for('lead_detail', lead_id=lead_id))

    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()
    return render_template('lead_edit.html', lead=lead, stages=stages_pre, stages_pre=stages_pre, stages_post=stages_post)


@app.route('/leads/new', methods=['GET', 'POST'])
def lead_new():
    """Create new lead."""
    if request.method == 'POST':
        data = {
            'company_name': request.form.get('company_name'),
            'website': request.form.get('website'),
            'funding_amount': request.form.get('funding_amount'),
            'funding_stage': request.form.get('funding_stage'),
            'location': request.form.get('location'),
            'industry_tags': request.form.get('industry_tags'),
            'founders': request.form.get('founders'),
            'stage': request.form.get('stage', 'new'),
            'stage_pre': request.form.get('stage_pre', 'research'),
            'priority': request.form.get('priority', 'medium'),
            'source': 'manual',
        }
        lead_id = Lead.create(data)
        return redirect(url_for('lead_detail', lead_id=lead_id))

    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()
    return render_template('lead_edit.html', lead=None, stages=stages_pre, stages_pre=stages_pre, stages_post=stages_post)


@app.route('/leads/<int:lead_id>/delete', methods=['POST'])
def lead_delete(lead_id):
    """Delete a lead."""
    Lead.delete(lead_id)
    return redirect(url_for('leads_list'))


# ============== SETTINGS ==============

@app.route('/settings')
def settings():
    """Settings page with links to Google Sheets and configuration."""
    from config import config

    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}" if config.GOOGLE_SHEET_ID else None
    sources = ScrapingSource.get_all()

    return render_template('settings.html',
        sheet_url=sheet_url,
        sheet_id=config.GOOGLE_SHEET_ID,
        config=config,
        sources=sources
    )


# ============== PIPELINE ==============

@app.route('/pipeline')
def pipeline():
    """Kanban pipeline view with dual trackers."""
    tracker = request.args.get('tracker', 'pre')  # pre or post

    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()

    # Get leads for the active tracker
    pipeline_data_pre = {}
    pipeline_data_post = {}

    for stage in stages_pre:
        pipeline_data_pre[stage['name']] = Lead.get_by_stage_pre(stage['name'])

    for stage in stages_post:
        pipeline_data_post[stage['name']] = Lead.get_by_stage_post(stage['name'])

    return render_template('pipeline.html',
        stages_pre=stages_pre,
        stages_post=stages_post,
        pipeline_data_pre=pipeline_data_pre,
        pipeline_data_post=pipeline_data_post,
        current_tracker=tracker
    )


# ============== API ENDPOINTS ==============

@app.route('/api/leads', methods=['POST'])
def api_create_lead():
    """API: Create a new lead."""
    from datetime import datetime
    data = request.json
    if not data.get('company_name'):
        return jsonify({'error': 'Company name is required'}), 400

    # Check if creating in post-conversation tracker
    stage_post = data.get('stage_post', '').strip()

    lead_data = {
        'company_name': data.get('company_name'),
        'website': data.get('website'),
        'funding_amount': data.get('funding_amount'),
        'funding_stage': data.get('funding_stage'),
        'location': data.get('location'),
        'industry_tags': data.get('industry_tags'),
        'founders': data.get('founders'),
        'social_links': data.get('social_links'),
        'stage': data.get('stage', 'new'),
        'stage_pre': data.get('stage_pre', 'research'),
        'stage_post': stage_post if stage_post else None,
        'conversation_started_at': datetime.now().isoformat() if stage_post else None,
        'priority': data.get('priority', 'medium'),
        'source': 'manual',
    }
    lead_id = Lead.create(lead_data)
    return jsonify({'success': True, 'id': lead_id})


@app.route('/api/leads/<int:lead_id>/stage', methods=['POST'])
def api_update_stage(lead_id):
    """API: Update lead stage (legacy, for backward compatibility)."""
    data = request.json
    new_stage = data.get('stage')

    if new_stage:
        Lead.update_stage(lead_id, new_stage)
        Activity.create(lead_id, 'stage_change', f'Moved to {new_stage}')
        return jsonify({'success': True})

    return jsonify({'error': 'No stage provided'}), 400


@app.route('/api/leads/<int:lead_id>/stage/pre', methods=['POST'])
def api_update_stage_pre(lead_id):
    """API: Update lead's pre-conversation stage."""
    data = request.json
    new_stage = data.get('stage')

    if new_stage:
        Lead.update_stage_pre(lead_id, new_stage)
        Activity.create(lead_id, 'stage_change_pre', f'Pre-conversation: Moved to {new_stage}')
        return jsonify({'success': True})

    return jsonify({'error': 'No stage provided'}), 400


@app.route('/api/leads/<int:lead_id>/stage/post', methods=['POST'])
def api_update_stage_post(lead_id):
    """API: Update lead's post-conversation stage."""
    data = request.json
    new_stage = data.get('stage')

    if new_stage:
        Lead.update_stage_post(lead_id, new_stage)
        Activity.create(lead_id, 'stage_change_post', f'Post-conversation: Moved to {new_stage}')
        return jsonify({'success': True})

    return jsonify({'error': 'No stage provided'}), 400


@app.route('/api/leads/<int:lead_id>/start-conversation', methods=['POST'])
def api_start_conversation(lead_id):
    """API: Mark lead as having started conversation - move to post tracker."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    Lead.start_conversation(lead_id)
    Activity.create(lead_id, 'conversation_started', 'Conversation started - moved to post-conversation tracker')
    return jsonify({'success': True})


@app.route('/api/leads/<int:lead_id>/move-to-pre', methods=['POST'])
def api_move_to_pre(lead_id):
    """API: Move lead back to pre-conversation tracker."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    Lead.move_to_pre(lead_id)
    Activity.create(lead_id, 'stage_change', 'Moved back to pre-conversation tracker')
    return jsonify({'success': True})


@app.route('/api/leads/<int:lead_id>/note', methods=['POST'])
def api_add_note(lead_id):
    """API: Add note to lead."""
    data = request.json
    content = data.get('content')

    if content:
        Activity.create(lead_id, 'note', content)
        return jsonify({'success': True})

    return jsonify({'error': 'No content provided'}), 400


@app.route('/api/leads/<int:lead_id>/generate-dm', methods=['POST'])
def api_generate_dm(lead_id):
    """API: Generate personalized cold DM for a lead."""
    from dm_generator import get_dm_generator

    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    # Only allow for pre-conversation leads
    if lead.get('stage_post'):
        return jsonify({'error': 'DM generation is only for pre-conversation leads'}), 400

    try:
        generator = get_dm_generator()
        result = generator.generate_full(lead)

        if result['success']:
            # Log as activity
            Activity.create(
                lead_id,
                'note',
                f"[AI Generated DM]\n{result['dm']}"
            )

        return jsonify(result)

    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': f'Failed to generate DM: {str(e)}'}), 500


@app.route('/api/tasks', methods=['POST'])
def api_create_task():
    """API: Create a task."""
    data = request.json
    task_id = Task.create(
        title=data.get('title'),
        lead_id=data.get('lead_id'),
        description=data.get('description'),
        due_date=data.get('due_date')
    )
    return jsonify({'success': True, 'task_id': task_id})


@app.route('/api/tasks/<int:task_id>/complete', methods=['POST'])
def api_complete_task(task_id):
    """API: Complete a task."""
    Task.complete(task_id)
    return jsonify({'success': True})


@app.route('/api/sync', methods=['POST'])
def api_sync_sheets():
    """API: Sync leads from Google Sheets."""
    try:
        from crm.sync_sheets import sync_from_sheets
        result = sync_from_sheets()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/leads/search')
def api_search_leads():
    """API: Search leads."""
    query = request.args.get('q', '')
    leads = Lead.get_all(search=query, limit=20)
    return jsonify(leads)


@app.route('/api/leads')
def api_list_leads():
    """API: Get leads list for a tracker."""
    stage = request.args.get('stage', 'all')
    tracker = request.args.get('tracker', 'pre')
    search = request.args.get('search', '')
    source = request.args.get('source', 'all')
    enriched_range = request.args.get('enriched', 'all')
    sort = request.args.get('sort', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    page = int(request.args.get('page', 1))
    per_page = 50

    leads = Lead.get_all(
        stage=stage if stage != 'all' else None,
        tracker=tracker,
        search=search if search else None,
        source=source if source != 'all' else None,
        enriched_range=enriched_range if enriched_range != 'all' else None,
        sort=sort,
        sort_dir=sort_dir,
        limit=per_page,
        offset=(page - 1) * per_page
    )

    stats = Lead.get_stats()
    stages = PipelineStage.get_pre_stages() if tracker == 'pre' else PipelineStage.get_post_stages()

    return jsonify({
        'leads': leads,
        'stats': stats,
        'stages': stages,
        'tracker': tracker,
        'stage': stage,
        'source': source,
        'enriched': enriched_range,
        'sort': sort,
        'sort_dir': sort_dir,
        'page': page
    })


@app.route('/api/leads/<int:lead_id>')
def api_get_lead(lead_id):
    """API: Get lead details as JSON."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    activities = Activity.get_for_lead(lead_id)
    tasks = Task.get_pending(lead_id)
    stages_pre = PipelineStage.get_pre_stages()
    stages_post = PipelineStage.get_post_stages()

    return jsonify({
        'lead': lead,
        'activities': activities,
        'tasks': tasks,
        'stages_pre': stages_pre,
        'stages_post': stages_post
    })


@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
def api_update_lead(lead_id):
    """API: Update a lead."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    Lead.update(lead_id, data)
    return jsonify({'success': True})


@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
def api_delete_lead(lead_id):
    """API: Delete a lead."""
    lead = Lead.get_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    Lead.delete(lead_id)
    return jsonify({'success': True})


# ============== SCRAPING SOURCES API ==============

@app.route('/api/sources', methods=['GET'])
def api_get_sources():
    """API: Get all scraping sources."""
    sources = ScrapingSource.get_all()
    return jsonify(sources)


@app.route('/api/sources', methods=['POST'])
def api_create_source():
    """API: Create a new scraping source."""
    data = request.json
    if not data.get('name') or not data.get('source_type'):
        return jsonify({'error': 'Name and source_type are required'}), 400

    source_id = ScrapingSource.create(data)
    return jsonify({'success': True, 'source_id': source_id})


@app.route('/api/sources/<int:source_id>', methods=['PUT'])
def api_update_source(source_id):
    """API: Update a scraping source."""
    data = request.json
    source = ScrapingSource.get_by_id(source_id)
    if not source:
        return jsonify({'error': 'Source not found'}), 404

    ScrapingSource.update(source_id, data)
    return jsonify({'success': True})


@app.route('/api/sources/<int:source_id>', methods=['DELETE'])
def api_delete_source(source_id):
    """API: Delete a scraping source."""
    source = ScrapingSource.get_by_id(source_id)
    if not source:
        return jsonify({'error': 'Source not found'}), 404

    ScrapingSource.delete(source_id)
    return jsonify({'success': True})


@app.route('/api/sources/<int:source_id>/toggle', methods=['POST'])
def api_toggle_source(source_id):
    """API: Toggle source enabled state."""
    source = ScrapingSource.get_by_id(source_id)
    if not source:
        return jsonify({'error': 'Source not found'}), 404

    ScrapingSource.update(source_id, {'enabled': not source['enabled']})
    return jsonify({'success': True, 'enabled': not source['enabled']})


# ============== CAL.COM INTEGRATION ==============

@app.route('/webhooks/slack/command', methods=['POST'])
def slack_command_webhook():
    """Handle Slack slash command trigger (e.g. /scrape)."""
    if not config.SLACK_SIGNING_SECRET:
        return jsonify({'error': 'SLACK_SIGNING_SECRET not configured'}), 503

    payload_bytes = request.get_data()
    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    if not _verify_slack_signature(payload_bytes, slack_timestamp, slack_signature):
        logger.warning("Slack slash-command signature verification failed")
        return jsonify({'error': 'Invalid signature'}), 401

    channel = request.form.get("channel_id", "")
    response_url = request.form.get("response_url", "")
    command = (request.form.get("command", "") or "").strip().lower()
    text = (request.form.get("text", "") or "").strip().lower()

    if config.SLACK_TRIGGER_CHANNEL_ID and channel != config.SLACK_TRIGGER_CHANNEL_ID:
        return jsonify({
            "response_type": "ephemeral",
            "text": "This command is only enabled in the configured scrape channel."
        })

    # Support /scrape or any slash command whose text includes "scrape".
    if "scrape" not in command and "scrape" not in text:
        return jsonify({
            "response_type": "ephemeral",
            "text": "Use `/scrape` to run the ICP scrape and post a report."
        })

    if getattr(app, '_agent_running', False):
        return jsonify({
            "response_type": "ephemeral",
            "text": "A scrape is already running. Please wait for it to complete."
        })

    dashboard_url = config.DASHBOARD_URL.strip() or request.host_url.rstrip("/")

    def run_agent_from_slash_command():
        try:
            app._agent_running = True
            from agents.funding_agent import FundingAgent
            agent = FundingAgent()
            result = agent.run()
            app._agent_last_result = result
            _post_to_slack_response_url(
                response_url,
                _format_slack_trigger_report(result, dashboard_url=dashboard_url),
                in_channel=True
            )
        except Exception as exc:
            logger.exception(f"Slash-command scrape failed: {exc}")
            app._agent_last_result = {'error': str(exc)}
            _post_to_slack_response_url(
                response_url,
                f"Scrape failed: `{exc}`",
                in_channel=False
            )
        finally:
            app._agent_running = False

    threading.Thread(target=run_agent_from_slash_command, daemon=True).start()
    return jsonify({
        "response_type": "ephemeral",
        "text": "Starting scrape now. I will post the report here when complete."
    })


@app.route('/webhooks/slack/events', methods=['POST'])
def slack_events_webhook():
    """Handle Slack app mentions and trigger scrape on demand."""
    if not config.SLACK_SIGNING_SECRET:
        return jsonify({'error': 'SLACK_SIGNING_SECRET not configured'}), 503

    payload_bytes = request.get_data()
    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    if not _verify_slack_signature(payload_bytes, slack_timestamp, slack_signature):
        logger.warning("Slack webhook signature verification failed")
        return jsonify({'error': 'Invalid signature'}), 401

    payload = request.get_json(silent=True) or {}

    # Slack URL verification handshake.
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload.get("challenge")})

    if payload.get("type") != "event_callback":
        return jsonify({'ok': True})

    event_id = payload.get("event_id", "")
    if _is_duplicate_slack_event(event_id):
        return jsonify({'ok': True})

    event = payload.get("event", {})
    if event.get("type") != "app_mention":
        return jsonify({'ok': True})
    if event.get("bot_id"):
        return jsonify({'ok': True})

    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not channel:
        return jsonify({'ok': True})

    text = (event.get("text") or "").lower()
    trigger_words = ("scrape", "run scrape", "refresh", "run report")
    if not any(word in text for word in trigger_words):
        _post_slack_message(
            channel,
            "Use `@codex scrape` (or `@claude scrape`) to run the ICP scrape and post a report.",
            thread_ts=thread_ts
        )
        return jsonify({'ok': True})

    if config.SLACK_TRIGGER_CHANNEL_ID and channel != config.SLACK_TRIGGER_CHANNEL_ID:
        _post_slack_message(
            channel,
            "This command is only enabled in the configured scrape channel.",
            thread_ts=thread_ts
        )
        return jsonify({'ok': True})

    if getattr(app, '_agent_running', False):
        _post_slack_message(
            channel,
            "A scrape is already running. I will post results when it completes.",
            thread_ts=thread_ts
        )
        return jsonify({'ok': True})

    _post_slack_message(
        channel,
        "Starting scrape now. I will post the report here when complete.",
        thread_ts=thread_ts
    )

    dashboard_url = config.DASHBOARD_URL.strip() or request.host_url.rstrip("/")

    def run_agent_from_slack():
        try:
            app._agent_running = True
            from agents.funding_agent import FundingAgent
            agent = FundingAgent()
            result = agent.run()
            app._agent_last_result = result
            _post_slack_message(
                channel,
                _format_slack_trigger_report(result, dashboard_url=dashboard_url),
                thread_ts=thread_ts
            )
        except Exception as exc:
            logger.exception(f"Slack-triggered scrape failed: {exc}")
            app._agent_last_result = {'error': str(exc)}
            _post_slack_message(
                channel,
                f"Scrape failed: `{exc}`",
                thread_ts=thread_ts
            )
        finally:
            app._agent_running = False

    threading.Thread(target=run_agent_from_slack, daemon=True).start()
    return jsonify({'ok': True})

@app.route('/webhooks/calcom', methods=['POST'])
def calcom_webhook():
    """Handle Cal.com webhook events (BOOKING_CREATED)."""
    from integrations.calcom import CalcomClient
    from crm.calcom_sync import handle_webhook_booking
    from utils.logger import get_logger

    logger = get_logger(__name__)

    # Get raw payload for signature verification
    payload_bytes = request.get_data()
    signature = request.headers.get('X-Cal-Signature-256', '')

    # Verify webhook signature
    client = CalcomClient()
    if not client.verify_webhook_signature(payload_bytes, signature):
        logger.warning("Cal.com webhook signature verification failed")
        return jsonify({'error': 'Invalid signature'}), 401

    # Parse and process the booking
    try:
        payload = request.json
        action, lead_id = handle_webhook_booking(payload)

        if action == "ignored":
            return jsonify({'status': 'ignored', 'reason': 'Not a BOOKING_CREATED event'})

        return jsonify({
            'status': 'success',
            'action': action,
            'lead_id': lead_id
        })

    except Exception as e:
        logger.error(f"Cal.com webhook error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/calcom/sync', methods=['POST'])
def api_calcom_sync():
    """API: Manually sync Cal.com bookings."""
    from crm.calcom_sync import sync_calcom_bookings
    from config import config

    if not config.CALCOM_API_KEY:
        return jsonify({'error': 'Cal.com API key not configured'}), 400

    try:
        # Get days parameter (default 30)
        data = request.get_json(silent=True) or {}
        since_days = data.get('since_days', 30)

        result = sync_calcom_bookings(since_days=since_days)
        return jsonify({
            'success': True,
            'result': result
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calcom/status', methods=['GET'])
def api_calcom_status():
    """API: Check Cal.com integration status."""
    from config import config

    return jsonify({
        'configured': bool(config.CALCOM_API_KEY),
        'webhook_secret_configured': bool(config.CALCOM_WEBHOOK_SECRET),
        'api_base_url': config.CALCOM_API_BASE_URL
    })


@app.route('/api/a16z/sync', methods=['POST'])
def api_a16z_sync():
    """API: Sync a16z Speedrun portfolio companies."""
    from a16z_sync import sync_a16z_speedrun

    try:
        result = sync_a16z_speedrun()
        return jsonify({
            'success': True,
            'result': result
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============== FUNDING AGENT ==============

@app.route('/api/agent/scrape', methods=['POST'])
def api_agent_scrape():
    """API: Run the funding news agent to scrape and import leads."""
    import threading

    data = request.json or {}
    sources = data.get('sources', None)
    if sources == 'all':
        sources = ["techcrunch", "google_news", "crunchbase", "yc_directory", "producthunt"]

    # Prevent concurrent runs
    if getattr(app, '_agent_running', False):
        return jsonify({'error': 'Agent is already running'}), 409

    def run_agent():
        try:
            app._agent_running = True
            from agents.funding_agent import FundingAgent
            agent = FundingAgent(sources=sources)
            result = agent.run()
            app._agent_last_result = result
        except Exception as e:
            app._agent_last_result = {'error': str(e)}
        finally:
            app._agent_running = False

    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Funding agent started. Check /api/agent/status for results.'
    })


@app.route('/api/agent/status', methods=['GET'])
def api_agent_status():
    """API: Check funding agent status and last results."""
    running = getattr(app, '_agent_running', False)
    last_result = getattr(app, '_agent_last_result', None)

    return jsonify({
        'running': running,
        'last_result': last_result,
    })


# ============== TEMPLATE FILTERS ==============

@app.template_filter('format_date')
def format_date(value):
    """Format date string."""
    if not value:
        return ''
    try:
        from datetime import datetime
        if 'T' in str(value):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(value[:10], '%Y-%m-%d')
        return dt.strftime('%b %d, %Y')
    except:
        return value


@app.template_filter('format_funding')
def format_funding(value):
    """Format funding amount."""
    if not value:
        return ''
    return value


@app.template_filter('truncate_text')
def truncate_text(value, length=50):
    """Truncate text."""
    if not value:
        return ''
    if len(value) <= length:
        return value
    return value[:length] + '...'


@app.template_filter('format_stage')
def format_stage(value):
    """Format stage name for display."""
    if not value:
        return ''
    return value.replace('_', ' ').title()


if __name__ == '__main__':
    app.run(debug=True, port=5001)
