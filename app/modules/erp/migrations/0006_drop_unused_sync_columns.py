"""The two-way stock merge (0003) was replaced by "the panel keeps stock" (0004): its three columns are unused."""
import sqlite3


def up(con):
    if sqlite3.sqlite_version_info < (3, 35, 0):
        return                      # DROP COLUMN needs SQLite 3.35+; on an older one the unused columns simply stay
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    for col in ("woo_base_move", "woo_drift", "woo_review"):
        if col in cols:
            con.execute(f"ALTER TABLE products DROP COLUMN {col}")
