-- Media studio: every generation (video or image) the team made, shared as one library.
-- Files live in data/media/YYYY/MM/; this table keeps the request, status, cost and output paths.

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS generations (
  id INTEGER PRIMARY KEY,
  batch_id TEXT NOT NULL,                   -- one submit with several models = one batch (comparison)
  kind TEXT NOT NULL CHECK (kind IN ('video', 'image')),
  model_id TEXT NOT NULL,
  model_name TEXT,
  prompt TEXT NOT NULL,
  request TEXT NOT NULL,                    -- JSON payload sent to OpenRouter
  status TEXT NOT NULL,                     -- queued | submitting | pending | in_progress | completed | failed | cancelled | expired
  job_id TEXT,                              -- OpenRouter video job id
  generation_id TEXT,
  usage TEXT,                               -- JSON usage block from OpenRouter
  cost REAL,                                -- USD, when OpenRouter reports it
  error TEXT,                               -- JSON {code, message}
  outputs TEXT,                             -- JSON [{index, path, media_type, bytes}]
  favorite INTEGER NOT NULL DEFAULT 0,
  poll_failures INTEGER NOT NULL DEFAULT 0,
  next_poll_at TEXT,
  created_by INTEGER,                       -- core user id
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_generations_status ON generations(status);
CREATE INDEX IF NOT EXISTS ix_generations_batch ON generations(batch_id);
