-- Core: who can log in, what each person may open, and one activity feed for every module.

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,        -- owner: every module + team & system settings
  active INTEGER NOT NULL DEFAULT 1,
  notif_seen INTEGER NOT NULL DEFAULT 0,      -- last activity id this user has seen in the bell
  created_at TEXT NOT NULL,
  last_login_at TEXT
);

-- Module access for non-admin users. role is one of the roles the module declares (e.g. erp: admin | seller).
CREATE TABLE IF NOT EXISTS user_modules (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (user_id, module)
);

-- Only a SHA-256 of the cookie token is stored, so a copy of the database cannot be used to log in.
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT,
  ip TEXT,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  module TEXT NOT NULL,                       -- core | erp | pricing | media | ...
  user_id INTEGER,
  kind TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'info',         -- info | success | warning | danger
  title TEXT NOT NULL,
  body TEXT,
  link TEXT,
  notify INTEGER NOT NULL DEFAULT 0           -- shown in the bell
);
CREATE INDEX IF NOT EXISTS ix_activity_module ON activity(module, id);
