from pokemon_price_tracker.woocommerce_scraper import scan_woocommerce_store_api
from pokemon_price_tracker.queries import QUERIES

SHOP_NAME = "Woo shops"

WOO_SHOPS = [
    ("andcards", "andcards.dk"),
    ("pocketmonster", "pocketmonster.dk"),
    ("pokemons", "pokemons.dk"),
]


def get_products():
    all_products = []

    for shop_name, domain in WOO_SHOPS:
        print(f"\n--- Scanner {shop_name} ({domain}) [Woo Store API] ---")
        try:
            products = scan_woocommerce_store_api(domain, QUERIES)
            print(f"{shop_name}: hentede {len(products)} produkter")

            for p in products:
                p["shop_source"] = shop_name

            all_products.extend(products)

        except Exception as e:
            print(f"Fejl i {shop_name}: {e}")

    return all_products