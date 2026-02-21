from pokemon_price_tracker.shopify_scraper import scan_shopify_store_json
from pokemon_price_tracker.queries import QUERIES

SHOP_NAME = "pockomonsters"


def get_products():
    print(f"\n--- Scanner pockomonsters (pockomonsters.dk) ---")
    products = scan_shopify_store_json("pockomonsters.dk", QUERIES)
    print(f"pockomonsters: hentede {len(products)} produkter")

    for p in products:
        p["shop_source"] = "pockomonsters"

    return products