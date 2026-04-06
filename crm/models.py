"""
Database models for the CRM.
Optimized for fast dashboard loading with dual-tracker support.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List

DB_PATH = Path(__file__).parent / "crm.db"

# Cache for pipeline stages (they rarely change)
_stages_cache_pre = None
_stages_cache_post = None

# Thread-local storage for connections
_local = threading.local()


def get_db():
    """Get database connection with optimizations.

    Uses thread-local storage to reuse connections within the same thread,
    preventing connection leaks and WAL file corruption.
    """
    if not hasattr(_local, 'conn') or _local.conn is None:
        conn = sqlite3.connect(
            DB_PATH,
            timeout=30.0,  # Wait up to 30 seconds for locks
            check_same_thread=False,
            isolation_level=None  # Autocommit mode - we handle transactions explicitly
        )
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read performance
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=30000")  # 30 second busy timeout
        _local.conn = conn
    return _local.conn


def close_db():
    """Close the thread-local database connection."""
    if hasattr(_local, 'conn') and _local.conn is not None:
        try:
            _local.conn.close()
        except:
            pass
        _local.conn = None


@contextmanager
def get_db_connection():
    """Context manager for database connections with automatic cleanup."""
    conn = get_db()
    try:
        yield conn
    except sqlite3.Error as e:
        # On error, close and reset connection to recover from corruption
        close_db()
        raise e


def reset_db_connection():
    """Force reset the database connection. Call this if you encounter errors."""
    close_db()
    # Also try to clean up any stale WAL files
    try:
        wal_path = Path(str(DB_PATH) + "-wal")
        shm_path = Path(str(DB_PATH) + "-shm")
        # Don't delete, just checkpoint the WAL
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Connection managed by thread-local storage
    except:
        pass


def init_db():
    """Initialize the database schema with indexes."""
    # Use a fresh dedicated connection for init to avoid issues
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    cursor = conn.cursor()

    # Leads table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            website TEXT,
            funding_amount TEXT,
            funding_date TEXT,
            funding_stage TEXT,
            location TEXT,
            industry_tags TEXT,
            founders TEXT,
            investors TEXT,
            source_url TEXT,
            source TEXT,

            -- ICP scoring
            icp_tag TEXT,
            icp_score INTEGER,
            icp_signals TEXT,

            -- Website analysis
            website_last_updated TEXT,
            aesthetics_score INTEGER,
            brand_score INTEGER,
            social_score INTEGER,
            social_links TEXT,

            -- Pipeline (legacy, for backward compatibility)
            stage TEXT DEFAULT 'new',
            priority TEXT DEFAULT 'medium',
            owner TEXT,

            -- Dual Tracker Pipeline
            stage_pre TEXT DEFAULT 'research',
            stage_post TEXT DEFAULT NULL,
            conversation_started_at TEXT DEFAULT NULL,

            -- Cal.com Booking Data
            calcom_booking_id TEXT DEFAULT NULL,
            booking_date TEXT DEFAULT NULL,
            attendee_email TEXT DEFAULT NULL,

            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(company_name, website)
        )
    """)

    # Add new columns if they don't exist (migration for existing DBs)
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN stage_pre TEXT DEFAULT 'research'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN stage_post TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN conversation_started_at TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Cal.com booking columns
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN calcom_booking_id TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN booking_date TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN attendee_email TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN notes TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN source_channel TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Potential value for post-conversation leads
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN potential_value TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # LinkedIn URL for founder profile
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN linkedin_url TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # LinkedIn URL for company page
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN company_linkedin_url TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    # Activities/notes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            type TEXT NOT NULL,  -- note, email, call, meeting, task, stage_change_pre, stage_change_post
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)

    # Tasks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            due_date DATE,
            completed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        )
    """)

    # Pipeline stages configuration with tracker_type
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            order_index INTEGER,
            color TEXT DEFAULT '#6B7280',
            tracker_type TEXT DEFAULT 'pre'
        )
    """)

    # Add tracker_type column if it doesn't exist
    try:
        cursor.execute("ALTER TABLE pipeline_stages ADD COLUMN tracker_type TEXT DEFAULT 'pre'")
    except sqlite3.OperationalError:
        pass

    # Scraping sources configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scraping_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,  -- rss, api, manual
            url TEXT,
            description TEXT,
            enabled BOOLEAN DEFAULT TRUE,
            last_scraped TEXT,
            leads_count INTEGER DEFAULT 0,
            config TEXT,  -- JSON config for source-specific settings
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create indexes for fast queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage_pre ON leads(stage_pre)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage_post ON leads(stage_post)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_icp_score ON leads(icp_score DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_icp_tag ON leads(icp_tag)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage_score ON leads(stage, icp_score DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_lead_id ON activities(lead_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_created_at ON activities(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_completed ON tasks(completed)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_stages_tracker ON pipeline_stages(tracker_type, order_index)")

    # Composite index for dual-tracker dashboard queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_pre_tracker ON leads(stage_pre, icp_score DESC) WHERE stage_post IS NULL OR stage_post = ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_post_tracker ON leads(stage_post, icp_score DESC) WHERE stage_post IS NOT NULL AND stage_post != ''")

    # Initialize pipeline stages only if table is empty (not on every restart)
    stage_count = cursor.execute("SELECT COUNT(*) FROM pipeline_stages").fetchone()[0]
    if stage_count == 0:
        # Pre-conversation stages
        pre_stages = [
            ('research', 0, '#6B7280', 'pre'),      # Gray
            ('queued', 1, '#3B82F6', 'pre'),        # Blue
            ('dm_sent', 2, '#8B5CF6', 'pre'),       # Purple
            ('follow_up_1', 3, '#F59E0B', 'pre'),   # Amber
            ('follow_up_2', 4, '#EC4899', 'pre'),   # Pink
            ('no_response', 5, '#EF4444', 'pre'),   # Red
        ]

        # Post-conversation stages
        post_stages = [
            ('replied', 0, '#10B981', 'post'),           # Green
            ('discovery_booked', 1, '#3B82F6', 'post'),  # Blue
            ('discovery_done', 2, '#8B5CF6', 'post'),    # Purple
            ('audit_scheduled', 3, '#F59E0B', 'post'),   # Amber
            ('proposal_sent', 4, '#EC4899', 'post'),     # Pink
            ('negotiation', 5, '#F97316', 'post'),       # Orange
            ('paid', 6, '#22C55E', 'post'),              # Bright Green
            ('rejected', 7, '#EF4444', 'post'),          # Red
        ]

        for name, order, color, tracker_type in pre_stages + post_stages:
            cursor.execute("""
                INSERT INTO pipeline_stages (name, order_index, color, tracker_type)
                VALUES (?, ?, ?, ?)
            """, (name, order, color, tracker_type))

    # Insert default scraping sources
    default_sources = [
        ('TechCrunch Funding', 'rss', 'https://techcrunch.com/tag/fundraising/feed/', 'TechCrunch funding announcements RSS feed'),
        ('TechCrunch AI', 'rss', 'https://techcrunch.com/tag/artificial-intelligence/feed/', 'TechCrunch AI news RSS feed'),
        ('Google Sheets', 'api', None, 'ICP leads and YC founders from Google Sheets'),
    ]

    for name, stype, url, desc in default_sources:
        cursor.execute("""
            INSERT OR IGNORE INTO scraping_sources (name, source_type, url, description)
            SELECT ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM scraping_sources WHERE name = ?)
        """, (name, stype, url, desc, name))

    # One-time migration: map old stage to stage_pre (only for unmigrated leads)
    cursor.execute("""
        UPDATE leads
        SET stage_pre = CASE
            WHEN stage = 'new' THEN 'research'
            WHEN stage = 'contacted' THEN 'dm_sent'
            WHEN stage IN ('qualified', 'proposal', 'negotiation') THEN 'dm_sent'
            WHEN stage = 'won' THEN 'dm_sent'
            WHEN stage = 'lost' THEN 'no_response'
            ELSE 'research'
        END
        WHERE stage_pre IS NULL
    """)

    conn.commit()
    conn.close()  # Close the dedicated init connection


class Lead:
    """Lead model with dual-tracker support."""

    @staticmethod
    def get_all(stage: str = None, tracker: str = None, search: str = None,
                source: str = None, sort: str = None, sort_dir: str = 'desc',
                limit: int = 100, offset: int = 0) -> List[dict]:
        """Get all leads with optional filtering by stage, tracker, and source.

        Leads are mutually exclusive between trackers:
        - Pre-conversation: leads where stage_post IS NULL or empty
        - Post-conversation: leads where stage_post IS NOT NULL and not empty

        Args:
            sort: Column to sort by (company_name, founders, source, priority, icp_score, created_at)
            sort_dir: Sort direction ('asc' or 'desc')
        """
        conn = get_db()
        query = "SELECT * FROM leads WHERE 1=1"
        params = []

        # Filter by tracker (mutually exclusive)
        if tracker == 'pre':
            query += " AND (stage_post IS NULL OR stage_post = '')"
            if stage and stage != 'all':
                query += " AND stage_pre = ?"
                params.append(stage)
        elif tracker == 'post':
            query += " AND stage_post IS NOT NULL AND stage_post != ''"
            if stage and stage != 'all':
                query += " AND stage_post = ?"
                params.append(stage)
        elif stage and stage != 'all':
            # Legacy: filter by old stage field
            query += " AND stage = ?"
            params.append(stage)

        # Filter by source
        if source and source != 'all':
            query += " AND source = ?"
            params.append(source)

        if search:
            query += " AND (company_name LIKE ? OR industry_tags LIKE ? OR founders LIKE ?)"
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])

        # Sorting - whitelist valid columns to prevent SQL injection
        valid_sort_columns = {
            'company_name': 'company_name',
            'founders': 'founders',
            'source': 'source',
            'priority': 'priority',
            'icp_score': 'icp_score',
            'created_at': 'created_at',
        }

        sort_column = valid_sort_columns.get(sort, 'icp_score')
        sort_direction = 'ASC' if sort_dir == 'asc' else 'DESC'

        # For text columns, use COLLATE NOCASE for case-insensitive sorting
        if sort_column in ('company_name', 'founders', 'source'):
            query += f" ORDER BY {sort_column} COLLATE NOCASE {sort_direction}, created_at DESC"
        else:
            query += f" ORDER BY {sort_column} {sort_direction}, created_at DESC"

        query += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        leads = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return leads

    @staticmethod
    def get_sources() -> List[dict]:
        """Get all distinct lead sources with counts."""
        conn = get_db()
        cursor = conn.execute("""
            SELECT source, COUNT(*) as count
            FROM leads
            WHERE source IS NOT NULL AND source != ''
            GROUP BY source
            ORDER BY count DESC
        """)
        sources = [{'name': row['source'], 'count': row['count']} for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return sources

    @staticmethod
    def get_by_id(lead_id: int) -> Optional[dict]:
        """Get a lead by ID."""
        conn = get_db()
        cursor = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,))
        row = cursor.fetchone()
        # Connection managed by thread-local storage
        return dict(row) if row else None

    @staticmethod
    def get_by_stage_pre(stage: str, limit: int = 100) -> List[dict]:
        """Get leads by pre-conversation stage (only leads NOT in post-conversation)."""
        conn = get_db()
        cursor = conn.execute(
            "SELECT * FROM leads WHERE stage_pre = ? AND (stage_post IS NULL OR stage_post = '') ORDER BY icp_score DESC LIMIT ?",
            (stage, limit)
        )
        leads = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return leads

    @staticmethod
    def get_by_stage_post(stage: str, limit: int = 100) -> List[dict]:
        """Get leads by post-conversation stage (only leads that ARE in post-conversation)."""
        conn = get_db()
        cursor = conn.execute(
            "SELECT * FROM leads WHERE stage_post = ? AND stage_post IS NOT NULL AND stage_post != '' ORDER BY icp_score DESC LIMIT ?",
            (stage, limit)
        )
        leads = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return leads

    @staticmethod
    def get_by_stage(stage: str, limit: int = 100) -> List[dict]:
        """Get leads by pipeline stage (legacy)."""
        conn = get_db()
        cursor = conn.execute(
            "SELECT * FROM leads WHERE stage = ? ORDER BY icp_score DESC LIMIT ?",
            (stage, limit)
        )
        leads = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return leads

    @staticmethod
    def create(data: dict) -> int:
        """Create a new lead. Auto-scores with ICP filter if no score provided."""
        # Auto-score if no icp_score provided
        if not data.get('icp_score'):
            try:
                from processors.icp_filter import ICPFilter
                icp = ICPFilter()
                icp.tag_lead(data)
            except Exception:
                pass  # Don't block creation if scoring fails

        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO leads (
                company_name, website, funding_amount, funding_date, funding_stage,
                location, industry_tags, founders, investors, source_url, source,
                icp_tag, icp_score, icp_signals,
                website_last_updated, aesthetics_score, brand_score, social_score, social_links,
                stage, priority, stage_pre, stage_post, conversation_started_at,
                calcom_booking_id, booking_date, attendee_email, notes, source_channel
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('company_name'),
            data.get('website'),
            data.get('funding_amount'),
            data.get('funding_date'),
            data.get('funding_stage'),
            data.get('location'),
            data.get('industry_tags'),
            data.get('founders'),
            data.get('investors'),
            data.get('source_url'),
            data.get('source', 'manual'),
            data.get('icp_tag'),
            data.get('icp_score', 0),
            data.get('icp_signals'),
            data.get('website_last_updated'),
            data.get('aesthetics_score', 0),
            data.get('brand_score', 0),
            data.get('social_score', 0),
            data.get('social_links'),
            data.get('stage', 'new'),
            data.get('priority', 'medium'),
            data.get('stage_pre', 'research'),
            data.get('stage_post'),
            data.get('conversation_started_at'),
            data.get('calcom_booking_id'),
            data.get('booking_date'),
            data.get('attendee_email'),
            data.get('notes'),
            data.get('source_channel'),
        ))
        lead_id = cursor.lastrowid
        conn.commit()
        # Connection managed by thread-local storage
        return lead_id

    @staticmethod
    def update(lead_id: int, data: dict):
        """Update a lead."""
        conn = get_db()

        # Build dynamic update query
        fields = []
        values = []
        for key, value in data.items():
            if key != 'id':
                fields.append(f"{key} = ?")
                values.append(value)

        fields.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(lead_id)

        query = f"UPDATE leads SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def update_stage(lead_id: int, stage: str):
        """Update lead's pipeline stage (legacy)."""
        conn = get_db()
        conn.execute(
            "UPDATE leads SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, datetime.now().isoformat(), lead_id)
        )
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def update_stage_pre(lead_id: int, stage: str):
        """Update lead's pre-conversation stage."""
        conn = get_db()
        conn.execute(
            "UPDATE leads SET stage_pre = ?, updated_at = ? WHERE id = ?",
            (stage, datetime.now().isoformat(), lead_id)
        )
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def update_stage_post(lead_id: int, stage: str):
        """Update lead's post-conversation stage."""
        conn = get_db()
        conn.execute(
            "UPDATE leads SET stage_post = ?, updated_at = ? WHERE id = ?",
            (stage, datetime.now().isoformat(), lead_id)
        )
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def start_conversation(lead_id: int):
        """Mark conversation as started - move lead to post-conversation tracker."""
        conn = get_db()
        conn.execute(
            "UPDATE leads SET stage_post = 'replied', conversation_started_at = ?, updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), datetime.now().isoformat(), lead_id)
        )
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def move_to_pre(lead_id: int):
        """Move lead back to pre-conversation tracker (clear stage_post)."""
        conn = get_db()
        conn.execute(
            "UPDATE leads SET stage_post = NULL, conversation_started_at = NULL, updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), lead_id)
        )
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def delete(lead_id: int):
        """Delete a lead."""
        conn = get_db()
        conn.execute("DELETE FROM activities WHERE lead_id = ?", (lead_id,))
        conn.execute("DELETE FROM tasks WHERE lead_id = ?", (lead_id,))
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def get_stats() -> dict:
        """Get lead statistics for both trackers."""
        conn = get_db()

        # Basic stats
        result = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN created_at > datetime('now', '-7 days') THEN 1 ELSE 0 END) as recent,
                ROUND(AVG(CASE WHEN aesthetics_score > 0 THEN aesthetics_score END), 1) as avg_aesthetics,
                ROUND(AVG(CASE WHEN brand_score > 0 THEN brand_score END), 1) as avg_brand,
                ROUND(AVG(CASE WHEN social_score > 0 THEN social_score END), 1) as avg_social,
                SUM(CASE WHEN aesthetics_score > 0 OR brand_score > 0 THEN 1 ELSE 0 END) as websites_analyzed,
                SUM(CASE WHEN stage_post IS NOT NULL THEN 1 ELSE 0 END) as in_conversation,
                SUM(CASE WHEN stage_post = 'paid' THEN 1 ELSE 0 END) as deals_won
            FROM leads
        """).fetchone()

        # Pre-conversation stage counts (only leads NOT in post-conversation)
        pre_stages = conn.execute("""
            SELECT stage_pre, COUNT(*) as count
            FROM leads
            WHERE stage_post IS NULL OR stage_post = ''
            GROUP BY stage_pre
        """).fetchall()
        by_stage_pre = {row['stage_pre']: row['count'] for row in pre_stages if row['stage_pre']}

        # Post-conversation stage counts (only leads IN post-conversation)
        post_stages = conn.execute("""
            SELECT stage_post, COUNT(*) as count
            FROM leads
            WHERE stage_post IS NOT NULL AND stage_post != ''
            GROUP BY stage_post
        """).fetchall()
        by_stage_post = {row['stage_post']: row['count'] for row in post_stages if row['stage_post']}

        # Legacy by_stage for backward compatibility
        stages = conn.execute("""
            SELECT stage, COUNT(*) as count
            FROM leads
            GROUP BY stage
        """).fetchall()
        by_stage = {row['stage']: row['count'] for row in stages}

        # By ICP tag
        icp_tags = conn.execute("""
            SELECT icp_tag, COUNT(*) as count
            FROM leads
            WHERE icp_tag IS NOT NULL AND icp_tag != ''
            GROUP BY icp_tag
            ORDER BY count DESC
        """).fetchall()
        by_icp = {row['icp_tag']: row['count'] for row in icp_tags}

        # Connection managed by thread-local storage

        return {
            'total': result['total'] or 0,
            'by_stage': by_stage,
            'by_stage_pre': by_stage_pre,
            'by_stage_post': by_stage_post,
            'by_icp': by_icp,
            'recent': result['recent'] or 0,
            'avg_aesthetics': result['avg_aesthetics'],
            'avg_brand': result['avg_brand'],
            'avg_social': result['avg_social'],
            'websites_analyzed': result['websites_analyzed'] or 0,
            'in_conversation': result['in_conversation'] or 0,
            'deals_won': result['deals_won'] or 0,
        }


class Activity:
    """Activity/note model."""

    @staticmethod
    def get_for_lead(lead_id: int) -> List[dict]:
        """Get all activities for a lead."""
        conn = get_db()
        cursor = conn.execute(
            "SELECT * FROM activities WHERE lead_id = ? ORDER BY created_at DESC",
            (lead_id,)
        )
        activities = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return activities

    @staticmethod
    def create(lead_id: int, activity_type: str, content: str, created_by: str = None) -> int:
        """Create a new activity."""
        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO activities (lead_id, type, content, created_by)
            VALUES (?, ?, ?, ?)
        """, (lead_id, activity_type, content, created_by))
        activity_id = cursor.lastrowid
        conn.commit()
        # Connection managed by thread-local storage
        return activity_id

    @staticmethod
    def get_recent(limit: int = 20) -> List[dict]:
        """Get recent activities across all leads."""
        conn = get_db()
        cursor = conn.execute("""
            SELECT a.*, l.company_name
            FROM activities a
            JOIN leads l ON a.lead_id = l.id
            ORDER BY a.created_at DESC
            LIMIT ?
        """, (limit,))
        activities = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return activities


class Task:
    """Task model."""

    @staticmethod
    def get_pending(lead_id: int = None, limit: int = 10) -> List[dict]:
        """Get pending tasks."""
        conn = get_db()

        if lead_id:
            cursor = conn.execute("""
                SELECT t.*, l.company_name
                FROM tasks t
                LEFT JOIN leads l ON t.lead_id = l.id
                WHERE t.completed = FALSE AND t.lead_id = ?
                ORDER BY t.due_date ASC
                LIMIT ?
            """, (lead_id, limit))
        else:
            cursor = conn.execute("""
                SELECT t.*, l.company_name
                FROM tasks t
                LEFT JOIN leads l ON t.lead_id = l.id
                WHERE t.completed = FALSE
                ORDER BY t.due_date ASC
                LIMIT ?
            """, (limit,))

        tasks = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return tasks

    @staticmethod
    def create(title: str, lead_id: int = None, description: str = None, due_date: str = None) -> int:
        """Create a new task."""
        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO tasks (lead_id, title, description, due_date)
            VALUES (?, ?, ?, ?)
        """, (lead_id, title, description, due_date))
        task_id = cursor.lastrowid
        conn.commit()
        # Connection managed by thread-local storage
        return task_id

    @staticmethod
    def complete(task_id: int):
        """Mark a task as completed."""
        conn = get_db()
        conn.execute("UPDATE tasks SET completed = TRUE WHERE id = ?", (task_id,))
        conn.commit()
        # Connection managed by thread-local storage


class PipelineStage:
    """Pipeline stage model with dual-tracker support and caching."""

    @staticmethod
    def get_all(tracker_type: str = None) -> List[dict]:
        """Get all pipeline stages, optionally filtered by tracker type."""
        global _stages_cache_pre, _stages_cache_post

        if tracker_type == 'pre':
            if _stages_cache_pre is not None:
                return _stages_cache_pre
            conn = get_db()
            cursor = conn.execute(
                "SELECT * FROM pipeline_stages WHERE tracker_type = 'pre' ORDER BY order_index"
            )
            _stages_cache_pre = [dict(row) for row in cursor.fetchall()]
            # Connection managed by thread-local storage
            return _stages_cache_pre

        elif tracker_type == 'post':
            if _stages_cache_post is not None:
                return _stages_cache_post
            conn = get_db()
            cursor = conn.execute(
                "SELECT * FROM pipeline_stages WHERE tracker_type = 'post' ORDER BY order_index"
            )
            _stages_cache_post = [dict(row) for row in cursor.fetchall()]
            # Connection managed by thread-local storage
            return _stages_cache_post

        else:
            # Return all stages
            conn = get_db()
            cursor = conn.execute("SELECT * FROM pipeline_stages ORDER BY tracker_type, order_index")
            stages = [dict(row) for row in cursor.fetchall()]
            # Connection managed by thread-local storage
            return stages

    @staticmethod
    def get_pre_stages() -> List[dict]:
        """Get pre-conversation stages."""
        return PipelineStage.get_all('pre')

    @staticmethod
    def get_post_stages() -> List[dict]:
        """Get post-conversation stages."""
        return PipelineStage.get_all('post')

    @staticmethod
    def clear_cache():
        """Clear the stages cache."""
        global _stages_cache_pre, _stages_cache_post
        _stages_cache_pre = None
        _stages_cache_post = None


class ScrapingSource:
    """Scraping source model."""

    @staticmethod
    def get_all() -> List[dict]:
        """Get all scraping sources."""
        conn = get_db()
        cursor = conn.execute("SELECT * FROM scraping_sources ORDER BY created_at DESC")
        sources = [dict(row) for row in cursor.fetchall()]
        # Connection managed by thread-local storage
        return sources

    @staticmethod
    def get_by_id(source_id: int) -> Optional[dict]:
        """Get a scraping source by ID."""
        conn = get_db()
        cursor = conn.execute("SELECT * FROM scraping_sources WHERE id = ?", (source_id,))
        row = cursor.fetchone()
        # Connection managed by thread-local storage
        return dict(row) if row else None

    @staticmethod
    def create(data: dict) -> int:
        """Create a new scraping source."""
        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO scraping_sources (name, source_type, url, description, enabled, config)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.get('name'),
            data.get('source_type', 'rss'),
            data.get('url'),
            data.get('description'),
            data.get('enabled', True),
            data.get('config'),
        ))
        source_id = cursor.lastrowid
        conn.commit()
        # Connection managed by thread-local storage
        return source_id

    @staticmethod
    def update(source_id: int, data: dict):
        """Update a scraping source."""
        conn = get_db()
        fields = []
        values = []
        for key, value in data.items():
            if key != 'id':
                fields.append(f"{key} = ?")
                values.append(value)
        values.append(source_id)
        query = f"UPDATE scraping_sources SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def delete(source_id: int):
        """Delete a scraping source."""
        conn = get_db()
        conn.execute("DELETE FROM scraping_sources WHERE id = ?", (source_id,))
        conn.commit()
        # Connection managed by thread-local storage

    @staticmethod
    def update_last_scraped(source_id: int, leads_count: int = 0):
        """Update last scraped timestamp and leads count."""
        conn = get_db()
        conn.execute("""
            UPDATE scraping_sources
            SET last_scraped = ?, leads_count = leads_count + ?
            WHERE id = ?
        """, (datetime.now().isoformat(), leads_count, source_id))
        conn.commit()
        # Connection managed by thread-local storage


def get_dashboard_data() -> dict:
    """
    Get all dashboard data in a single optimized function.
    Includes dual-tracker stats.
    """
    conn = get_db()

    # Get stats with single query
    stats_row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN created_at > datetime('now', '-7 days') THEN 1 ELSE 0 END) as recent,
            ROUND(AVG(CASE WHEN aesthetics_score > 0 THEN aesthetics_score END), 1) as avg_aesthetics,
            ROUND(AVG(CASE WHEN brand_score > 0 THEN brand_score END), 1) as avg_brand,
            ROUND(AVG(CASE WHEN social_score > 0 THEN social_score END), 1) as avg_social,
            SUM(CASE WHEN aesthetics_score > 0 OR brand_score > 0 THEN 1 ELSE 0 END) as websites_analyzed,
            SUM(CASE WHEN stage_post IS NOT NULL AND stage_post != '' THEN 1 ELSE 0 END) as in_conversation,
            SUM(CASE WHEN stage_post = 'paid' THEN 1 ELSE 0 END) as deals_won,
            SUM(CASE WHEN stage_pre IN ('dm_sent', 'follow_up_1', 'follow_up_2') AND (stage_post IS NULL OR stage_post = '') THEN 1 ELSE 0 END) as awaiting_response
        FROM leads
    """).fetchone()

    # Pre-conversation stage counts (only leads NOT in post-conversation)
    pre_rows = conn.execute("""
        SELECT stage_pre, COUNT(*) as count
        FROM leads
        WHERE stage_post IS NULL OR stage_post = ''
        GROUP BY stage_pre
    """).fetchall()
    by_stage_pre = {row['stage_pre']: row['count'] for row in pre_rows if row['stage_pre']}

    # Post-conversation stage counts (only leads IN post-conversation)
    post_rows = conn.execute("""
        SELECT stage_post, COUNT(*) as count
        FROM leads
        WHERE stage_post IS NOT NULL AND stage_post != ''
        GROUP BY stage_post
    """).fetchall()
    by_stage_post = {row['stage_post']: row['count'] for row in post_rows if row['stage_post']}

    # Legacy by_stage
    stages_rows = conn.execute("""
        SELECT stage, COUNT(*) as count FROM leads GROUP BY stage
    """).fetchall()
    by_stage = {row['stage']: row['count'] for row in stages_rows}

    # By ICP tag
    icp_rows = conn.execute("""
        SELECT icp_tag, COUNT(*) as count FROM leads
        WHERE icp_tag IS NOT NULL AND icp_tag != ''
        GROUP BY icp_tag ORDER BY count DESC
    """).fetchall()
    by_icp = {row['icp_tag']: row['count'] for row in icp_rows}

    # Recent leads
    recent_leads = conn.execute("""
        SELECT id, company_name, industry_tags, location, icp_score, icp_tag,
               funding_amount, aesthetics_score, brand_score, stage_pre, stage_post
        FROM leads
        ORDER BY icp_score DESC, created_at DESC
        LIMIT 10
    """).fetchall()

    # Recent activities
    recent_activities = conn.execute("""
        SELECT a.id, a.lead_id, a.type, a.content, a.created_at, l.company_name
        FROM activities a
        JOIN leads l ON a.lead_id = l.id
        ORDER BY a.created_at DESC
        LIMIT 10
    """).fetchall()

    # Pending tasks
    pending_tasks = conn.execute("""
        SELECT t.id, t.title, t.due_date, l.company_name
        FROM tasks t
        LEFT JOIN leads l ON t.lead_id = l.id
        WHERE t.completed = FALSE
        ORDER BY t.due_date ASC
        LIMIT 5
    """).fetchall()

    # Connection managed by thread-local storage

    stats = {
        'total': stats_row['total'] or 0,
        'recent': stats_row['recent'] or 0,
        'by_stage': by_stage,
        'by_stage_pre': by_stage_pre,
        'by_stage_post': by_stage_post,
        'by_icp': by_icp,
        'avg_aesthetics': stats_row['avg_aesthetics'],
        'avg_brand': stats_row['avg_brand'],
        'avg_social': stats_row['avg_social'],
        'websites_analyzed': stats_row['websites_analyzed'] or 0,
        'in_conversation': stats_row['in_conversation'] or 0,
        'deals_won': stats_row['deals_won'] or 0,
        'awaiting_response': stats_row['awaiting_response'] or 0,
    }

    return {
        'stats': stats,
        'recent_leads': [dict(row) for row in recent_leads],
        'recent_activities': [dict(row) for row in recent_activities],
        'pending_tasks': [dict(row) for row in pending_tasks],
        'stages': PipelineStage.get_all(),
        'stages_pre': PipelineStage.get_pre_stages(),
        'stages_post': PipelineStage.get_post_stages(),
    }


# Initialize database on import
init_db()
