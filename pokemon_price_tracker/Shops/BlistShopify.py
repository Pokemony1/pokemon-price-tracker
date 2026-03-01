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