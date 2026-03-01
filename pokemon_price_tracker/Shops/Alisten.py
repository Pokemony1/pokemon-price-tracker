from pokemon_price_tracker.shopify_scraper import scan_shopify_store_json
from pokemon_price_tracker.queries import QUERIES

SHOP_NAME = "A-list"

A_LIST = [
    ("mtgwebshop", "mtgwebshop.dk"),
    ("spilforsyningen", "spilforsyningen.dk"),
    ("matraws", "matraws.dk"),
    ("symbizon", "symbizon.dk"),
    ("shop_adlr", "shop.adlr.dk",),
    ("epicpanda", "epicpanda.dk",),
]


def get_products():
    """
    Scanner alle A-list shops og returnerer samlet liste.
    Vi tilføjer shop_source pr produkt, så main.py kan skrive korrekt shop-navn i Sheet.
    """
    all_products = []

    for shop_name, domain in A_LIST:
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
