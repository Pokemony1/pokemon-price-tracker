from pokemon_price_tracker.shopify_scraper import scan_shopify_store_json
from pokemon_price_tracker.queries import QUERIES

SHOP_NAME = "B-list Shopify"

B_LIST_SHOPIFY = [
    ("fun_shop", "fun-shop.dk"),
    ("musenogslottet", "musenogslottet.dk"),
    ("rogerz", "rogerz.dk"),
    ("epicpanda", "epicpanda.dk",),
]


def get_products():
    all_products = []

    for shop_name, domain in B_LIST_SHOPIFY:
        print(f"\n--- Scanner {shop_name} ({domain}) ---")
        try:
            products = scan_shopify_store_json(domain, QUERIES)
            print(f"{shop_name}: hentede {len(products)} produkter")

            for p in products:
                p["shop_source"] = shop_name

            all_products.extend(products)

        except Exception as e:
            print(f"Fejl i {shop_name}: {e}")

    return all_products