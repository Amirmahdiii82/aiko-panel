-- Price checker: your products, competitor offers and their price history, crawl runs, new-product research.
-- Written with IF NOT EXISTS so a database copied from the standalone app is adopted as-is.
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY,          -- WooCommerce product id on your site
    name            TEXT NOT NULL,
    slug            TEXT,
    sku             TEXT,
    permalink       TEXT,
    image           TEXT,
    brand           TEXT,
    categories      TEXT,                          -- JSON list
    price           INTEGER,                       -- Toman
    regular_price   INTEGER,
    in_stock        INTEGER,
    active          INTEGER DEFAULT 1,             -- 0 = no longer on the site
    tracked         INTEGER DEFAULT 1,             -- user can mute a product
    search_query    TEXT,                          -- optional manual override for competitor search
    size_hint       TEXT,                          -- size from product attributes when the title has none
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS my_prices (
    product_id      INTEGER NOT NULL,
    crawl_id        INTEGER NOT NULL,
    price           INTEGER,
    regular_price   INTEGER,
    in_stock        INTEGER,
    ts              TEXT NOT NULL,
    PRIMARY KEY (product_id, crawl_id)
);

CREATE TABLE IF NOT EXISTS offers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL,
    site            TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    url             TEXT,
    title           TEXT,
    seller          TEXT,
    image           TEXT,
    score           REAL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- auto | pending | confirmed | rejected
    reasons         TEXT,                             -- JSON: why the score is what it is
    price           INTEGER,
    regular_price   INTEGER,
    in_stock        INTEGER,
    extra           TEXT,                             -- JSON: e.g. list of sellers on marketplaces
    first_seen      TEXT,
    last_seen       TEXT,
    last_crawl_id   INTEGER,
    UNIQUE (product_id, site, external_id)
);
CREATE INDEX IF NOT EXISTS idx_offers_product ON offers(product_id);
CREATE INDEX IF NOT EXISTS idx_offers_site ON offers(site, status);

CREATE TABLE IF NOT EXISTS offer_prices (
    offer_id        INTEGER NOT NULL,
    crawl_id        INTEGER NOT NULL,
    price           INTEGER,
    regular_price   INTEGER,
    in_stock        INTEGER,
    ts              TEXT NOT NULL,
    PRIMARY KEY (offer_id, crawl_id)
);

CREATE TABLE IF NOT EXISTS crawls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,                    -- running | done | failed
    trigger         TEXT,
    stats           TEXT                              -- JSON
);

CREATE TABLE IF NOT EXISTS site_runs (
    crawl_id        INTEGER NOT NULL,
    site            TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    status          TEXT,                             -- running | ok | partial | blocked | failed | skipped
    searched        INTEGER DEFAULT 0,
    found           INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    last_error      TEXT,
    PRIMARY KEY (crawl_id, site)
);

CREATE TABLE IF NOT EXISTS new_products (           -- products you plan to sell: market research for pricing
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    brand           TEXT,
    search_query    TEXT,                             -- optional manual search text
    cost            INTEGER,                          -- your purchase price (Toman)
    target_margin   REAL DEFAULT 25,                  -- minimum profit % of the selling price
    status          TEXT NOT NULL DEFAULT 'running',  -- running | done
    results         TEXT,                             -- JSON list of competitor listings
    site_status     TEXT,                             -- JSON {site: {status, found, error}}
    choices         TEXT,                             -- JSON {site:external_id: true/false} user overrides
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
