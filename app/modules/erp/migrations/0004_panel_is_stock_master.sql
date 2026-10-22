-- Stock sync is now one-way for stock (stocksync.py): the panel is the one place stock is kept, the site shows it.
-- 1 = an item the site sells without counting was counted here; the site gets this number and starts counting.
ALTER TABLE products ADD COLUMN woo_counted INTEGER NOT NULL DEFAULT 0;
-- woo_base_move, woo_drift and woo_review (0003) belonged to the two-way merge and are no longer used.
-- States only that version knew are re-read: the next comparison with the site gives every product its state again.
UPDATE products SET woo_state = NULL WHERE woo_state IN ('drift', 'conflict', 'force');
