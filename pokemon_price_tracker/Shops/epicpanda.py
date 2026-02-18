from pokemon_price_tracker.shopify_scraper import scan_shopify_store_json
from pokemon_price_tracker.queries import QUERIES

SHOP_NAME = "epicpanda"
DOMAIN = "epicpanda.dk"

def get_products():
    return scan_shopify_store_json(DOMAIN, QUERIES)
