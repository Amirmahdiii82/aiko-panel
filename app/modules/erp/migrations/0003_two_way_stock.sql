-- Two-way stock sync with the site (stocksync.py): changes made here and changes made on the site are
-- both kept. Each linked product remembers the last point where the panel and the site agreed.
ALTER TABLE products ADD COLUMN woo_base_move INTEGER;  -- last stock move already reflected on the site (NULL = not agreed yet)
ALTER TABLE products ADD COLUMN woo_manage INTEGER;     -- 1 = the site counts this item, 0 = the site only says in/out of stock
ALTER TABLE products ADD COLUMN woo_in_stock INTEGER;   -- the site's own "in stock" flag
ALTER TABLE products ADD COLUMN woo_drift INTEGER;      -- a stock change made on the site, seen once; applied when seen again
ALTER TABLE products ADD COLUMN woo_price INTEGER;      -- last price seen on the site (a price change there updates the price here)
ALTER TABLE products ADD COLUMN woo_checked_at TEXT;    -- last time the site's stock was read
-- 1 = the numbers here and on the site differed before the two sides agreed (an old link, a new link): a person says
-- once which one is right. 2 = they said "the site" (applied at the next read). 0 = agreed, synced automatically.
ALTER TABLE products ADD COLUMN woo_review INTEGER NOT NULL DEFAULT 0;
