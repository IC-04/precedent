-- Northwind-style company world. See docs/03_contracts.md section 2.
-- Money is stored in minor units (paise or cents) as integers.

CREATE TABLE employees (
  id TEXT PRIMARY KEY,          -- E-ana
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  email TEXT NOT NULL,
  manager_id TEXT
);

CREATE TABLE accounts (
  code TEXT PRIMARY KEY,        -- 1400
  name TEXT NOT NULL,
  type TEXT NOT NULL
);

CREATE TABLE vendors (
  id TEXT PRIMARY KEY,          -- V-112
  name TEXT NOT NULL,
  legal_name TEXT,
  tax_id TEXT,
  email TEXT,
  phone TEXT,
  address TEXT,
  bank_account TEXT,
  status TEXT NOT NULL,         -- active | draft | retired
  created_by TEXT,
  created_at TEXT
);

CREATE TABLE bills (
  id TEXT PRIMARY KEY,          -- INV-921
  vendor_id TEXT NOT NULL,
  invoice_no TEXT NOT NULL,     -- FIG-1842; duplicates are allowed on purpose
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  issue_date TEXT,
  due_date TEXT,
  account_code TEXT,
  approver_id TEXT,
  status TEXT NOT NULL,         -- draft | pending_approval | approved | paid
  attachment_file_id TEXT,
  created_by TEXT,
  created_at TEXT,
  notes TEXT
);

CREATE TABLE approvals (
  id TEXT PRIMARY KEY,
  bill_id TEXT NOT NULL,
  approver_id TEXT NOT NULL,
  status TEXT NOT NULL,         -- pending | approved | rejected
  requested_by TEXT,
  requested_at TEXT,
  decided_at TEXT
);

CREATE TABLE mail_messages (
  id TEXT PRIMARY KEY,          -- m-0412
  thread_id TEXT,
  folder TEXT NOT NULL,
  from_name TEXT,
  from_addr TEXT,
  to_addr TEXT,
  subject TEXT,
  body TEXT,
  sent_at TEXT
);

CREATE TABLE mail_attachments (
  message_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  PRIMARY KEY (message_id, file_id)
);

CREATE TABLE files (
  id TEXT PRIMARY KEY,          -- f-...
  folder TEXT NOT NULL,
  name TEXT NOT NULL,
  mime TEXT NOT NULL,
  path TEXT NOT NULL,           -- relative to worlds/<seed>/
  uploaded_by TEXT,
  uploaded_at TEXT,
  sha256 TEXT
);

CREATE TABLE chat_channels (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);

CREATE TABLE chat_messages (
  id TEXT PRIMARY KEY,
  channel_id TEXT NOT NULL,
  author_id TEXT,
  body TEXT NOT NULL,
  posted_at TEXT
);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,          -- E-... or ava
  app TEXT NOT NULL,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  before_json TEXT,
  after_json TEXT
);
