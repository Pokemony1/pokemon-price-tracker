from pokemon_price_tracker.shopify_scraper import scan_shopify_store_json

SHOP_NAME = "mtgwebshop"
DOMAIN = "mtgwebshop.dk"
QUERIES = ["crown zenith", "prismatic evolution"]


def get_products():
    return scan_shopify_store_json(DOMAIN, QUERIES)
