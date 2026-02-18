import requests


def scan_shopify_store_json(domain: str, queries: list[str]) -> list[dict]:
    """
    Scanner Shopify /products.json (offentlig endpoint) og finder varianter hvor
    tekst matcher queries. Returnerer liste af:
      {"name": str, "price": float, "available": bool}
    """
    page = 1
    products = []
    queries_l = [q.lower() for q in queries]

    while True:
        url = f"https://{domain}/products.json?limit=250&page={page}"
        print(f"Henter JSON: {url}")

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Fejl ved hentning: {e}")
            break

        if not data.get("products"):
            break

        for product in data["products"]:
            full_text = (
                (product.get("title") or "")
                + (product.get("body_html") or "")
                + (product.get("product_type") or "")
            ).lower()

            if any(q in full_text for q in queries_l):
                for variant in product.get("variants", []):
                    try:
                        price = float(variant["price"])
                    except Exception:
                        continue

                    variant_title = variant.get("title", "")
                    variant_name = "" if variant_title == "Default Title" else variant_title
                    full_name = f"{product.get('title','').strip()} {variant_name}".strip()

                    products.append(
                        {
                            "name": full_name,
                            "price": price,
                            "available": bool(variant.get("available", False)),
                        }
                    )

        page += 1

    return products
