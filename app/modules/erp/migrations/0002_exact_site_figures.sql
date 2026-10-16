-- Exact website figures for accounting, and where each sale came from.
-- sales.total stays "money the shop keeps" (after refunds), so account balances and reports need no change.
ALTER TABLE sale_items ADD COLUMN discount INTEGER NOT NULL DEFAULT 0;     -- coupon / discount on this line (Toman)
ALTER TABLE sales ADD COLUMN refunded INTEGER NOT NULL DEFAULT 0;         -- refunded on the site (already taken off total)
ALTER TABLE sales ADD COLUMN fees INTEGER NOT NULL DEFAULT 0;             -- site fee lines (gateway fee, gift wrap, ...)
ALTER TABLE sales ADD COLUMN tax INTEGER NOT NULL DEFAULT 0;
ALTER TABLE sales ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';       -- manual | site | sheet
-- 1 = created from the site; its opening stock is set to the site's stock on the next full sync
ALTER TABLE products ADD COLUMN site_created INTEGER NOT NULL DEFAULT 0;

UPDATE sales SET source = 'site' WHERE woo_order_id IS NOT NULL;
UPDATE sales SET source = 'sheet' WHERE woo_order_id IS NULL AND note LIKE '%از فایل اکسل%';
CREATE INDEX IF NOT EXISTS ix_sales_channel_date ON sales(channel, date);
