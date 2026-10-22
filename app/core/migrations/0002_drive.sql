-- Receipts and invoices copied to the owners' Google Drive (core/drive.py). The files stay on the server too.
CREATE TABLE IF NOT EXISTS drive_files (
  id INTEGER PRIMARY KEY,
  ref TEXT NOT NULL,                        -- what the file belongs to, e.g. erp:purchase:12
  local_path TEXT NOT NULL,                 -- under data/uploads
  folder TEXT NOT NULL,                     -- path under the panel's root folder, "/"-separated
  name TEXT NOT NULL,                       -- file name in Drive
  size INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | error | held (over the cap) | replaced | removed
  drive_id TEXT,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  done_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_drive_files_ref_path ON drive_files(ref, local_path);
CREATE INDEX IF NOT EXISTS ix_drive_files_status ON drive_files(status, id);

-- Folder ids already created in Drive, by path under the root folder ("" = the root itself)
CREATE TABLE IF NOT EXISTS drive_folders (path TEXT PRIMARY KEY, drive_id TEXT NOT NULL);
