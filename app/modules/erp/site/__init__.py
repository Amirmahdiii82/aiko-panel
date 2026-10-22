"""The shop website (WooCommerce) connection.

    client.py    connection, HTTP client, catalogue, sync log, webhooks
    orders.py    website orders → sales (webhook + polling, idempotent by order id)
    matching.py  which panel product is which site product (SKU first)
    stock.py     the panel keeps stock, the site shows it (+ the background worker)
    history.py   importing every past order once; the nightly check of the last two weeks
"""
