-- ERP: inventory, sales from every channel, purchases, expenses, accounts and partners.
-- Money is whole Toman (INTEGER). Dates the user picks are ISO YYYY-MM-DD; timestamps are Tehran local time.
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS partners (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  share REAL NOT NULL DEFAULT 50,          -- ownership %, all partners add up to 100
  color TEXT,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('shop','partner','agent')),
  partner_id INTEGER REFERENCES partners(id),
  user_id INTEGER,                         -- the seller who holds this money (kind = agent)
  note TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0
);



-- ERP profile of a core user (identity, password and module access live in core.db)
CREATE TABLE IF NOT EXISTS staff (
  user_id INTEGER PRIMARY KEY,             -- core.users.id
  partner_id INTEGER REFERENCES partners(id),
  account_id INTEGER REFERENCES accounts(id),  -- where money this user receives is recorded by default
  commission_pct REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  sku TEXT UNIQUE,
  name TEXT NOT NULL,
  brand TEXT,
  category TEXT,
  price INTEGER NOT NULL DEFAULT 0,        -- selling price (Toman)
  avg_cost REAL NOT NULL DEFAULT 0,        -- weighted average landed cost per unit (Toman)
  stock INTEGER NOT NULL DEFAULT 0,        -- cached SUM(stock_moves.qty)
  low_stock INTEGER NOT NULL DEFAULT 2,
  woo_id INTEGER,                          -- WooCommerce product id
  woo_variation_id INTEGER,                -- WooCommerce variation id (NULL = whole product)
  woo_name TEXT,
  woo_url TEXT,
  image TEXT,
  woo_state TEXT,                          -- pending | ok | error (stock push state)
  woo_error TEXT,
  woo_synced_at TEXT,
  woo_stock INTEGER,                       -- last stock we saw on the site
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_products_woo ON products(woo_id, IFNULL(woo_variation_id, 0))
  WHERE woo_id IS NOT NULL AND active = 1;

CREATE TABLE IF NOT EXISTS stock_moves (
  id INTEGER PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL,                    -- + in, - out
  kind TEXT NOT NULL,                      -- opening | purchase | purchase_void | sale | sale_void | adjust | split
  unit_cost REAL,                          -- landed cost for incoming stock
  ref_type TEXT,
  ref_id INTEGER,
  note TEXT,
  user_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_moves_product ON stock_moves(product_id, id);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE,
  date TEXT NOT NULL,
  channel TEXT NOT NULL,                   -- website | instagram | in_person | agent | other
  seller_id INTEGER,                       -- core user id
  customer_name TEXT,
  customer_phone TEXT,
  subtotal INTEGER NOT NULL DEFAULT 0,
  discount INTEGER NOT NULL DEFAULT 0,
  shipping INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  cogs REAL NOT NULL DEFAULT 0,
  commission INTEGER NOT NULL DEFAULT 0,
  paid INTEGER NOT NULL DEFAULT 1,
  account_id INTEGER REFERENCES accounts(id),
  status TEXT NOT NULL DEFAULT 'done',     -- done | void
  woo_order_id INTEGER UNIQUE,
  woo_status TEXT,
  note TEXT,
  created_by INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sales_date ON sales(date);

CREATE TABLE IF NOT EXISTS sale_items (
  id INTEGER PRIMARY KEY,
  sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id),
  name TEXT NOT NULL,
  qty INTEGER NOT NULL,
  unit_price INTEGER NOT NULL,
  unit_cost REAL NOT NULL DEFAULT 0,
  line_total INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sale_items_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS ix_sale_items_product ON sale_items(product_id);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE,
  date TEXT NOT NULL,
  supplier TEXT,
  subtotal INTEGER NOT NULL DEFAULT 0,
  shipping INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  account_id INTEGER REFERENCES accounts(id),  -- NULL: payment recorded separately (old Excel rows)
  receipt TEXT,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'done',
  created_by INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_items (
  id INTEGER PRIMARY KEY,
  purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id),
  qty INTEGER NOT NULL,
  unit_cost REAL NOT NULL,
  landed_cost REAL NOT NULL,
  line_total INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY,
  code TEXT,
  date TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT,
  amount INTEGER NOT NULL,
  account_id INTEGER REFERENCES accounts(id),
  is_inventory INTEGER NOT NULL DEFAULT 0,   -- money spent on stock (already counted as cost of goods)
  sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,  -- auto commission
  receipt TEXT,
  note TEXT,
  created_by INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_expenses_date ON expenses(date);

CREATE TABLE IF NOT EXISTS capital (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  partner_id INTEGER NOT NULL REFERENCES partners(id),
  kind TEXT NOT NULL CHECK (kind IN ('in','out')),   -- in: partner puts money in, out: partner takes money out
  amount INTEGER NOT NULL,
  account_id INTEGER REFERENCES accounts(id),
  note TEXT,
  created_by INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  from_account INTEGER NOT NULL REFERENCES accounts(id),
  to_account INTEGER NOT NULL REFERENCES accounts(id),
  amount INTEGER NOT NULL,
  kind TEXT NOT NULL DEFAULT 'transfer',   -- transfer | settlement | handover
  note TEXT,
  created_by INTEGER,
  created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS woo_log (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  action TEXT NOT NULL,
  ok INTEGER NOT NULL,
  detail TEXT
);

CREATE VIEW IF NOT EXISTS money_flows AS
  SELECT account_id, date, total AS amount, 'sale' AS src, id AS ref_id FROM sales
    WHERE status = 'done' AND paid = 1 AND account_id IS NOT NULL
  UNION ALL SELECT account_id, date, -total, 'purchase', id FROM purchases
    WHERE status = 'done' AND account_id IS NOT NULL
  UNION ALL SELECT account_id, date, -amount, 'expense', id FROM expenses WHERE account_id IS NOT NULL
  UNION ALL SELECT account_id, date, CASE kind WHEN 'in' THEN amount ELSE -amount END, 'capital', id FROM capital
    WHERE account_id IS NOT NULL
  UNION ALL SELECT from_account, date, -amount, 'transfer', id FROM transfers
  UNION ALL SELECT to_account, date, amount, 'transfer', id FROM transfers;
