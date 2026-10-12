CREATE TABLE IF NOT EXISTS scheduling_settings (
 id TEXT PRIMARY KEY, organizer_id TEXT NOT NULL, timezone TEXT NOT NULL,
 reference_date TEXT NOT NULL, work_start INTEGER NOT NULL, work_end INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS calendars (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
 readable INTEGER NOT NULL, writable INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_drafts (
 id TEXT PRIMARY KEY, intent_key TEXT NOT NULL UNIQUE, organizer_id TEXT NOT NULL,
 recipient_id TEXT NOT NULL, recipient_email TEXT NOT NULL, topic TEXT NOT NULL,
 subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
 range_start TEXT NOT NULL, range_end TEXT NOT NULL, timezone TEXT NOT NULL,
 duration INTEGER NOT NULL, slot1 TEXT NOT NULL, slot2 TEXT NOT NULL,
 source_refs TEXT NOT NULL, source_quotes TEXT NOT NULL,
 version INTEGER NOT NULL, created_by TEXT NOT NULL, updated_by TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
 id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL, title TEXT NOT NULL,
 start_at TEXT NOT NULL, end_at TEXT NOT NULL, timezone TEXT NOT NULL,
 all_day INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
 participant_id TEXT, draft_id TEXT, version INTEGER NOT NULL,
 created_by TEXT NOT NULL, updated_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_hold_per_draft ON calendar_events(draft_id)
 WHERE draft_id IS NOT NULL AND status != 'cancelled';
