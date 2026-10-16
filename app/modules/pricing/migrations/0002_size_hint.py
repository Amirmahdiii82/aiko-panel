"""Databases created by early standalone versions lack products.size_hint."""


def up(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "size_hint" not in cols:
        con.execute("ALTER TABLE products ADD COLUMN size_hint TEXT")
