import requests


def scan_shopify_store_json(domain: str, queries: list[str]) -> list[dict]:
    """
    Scanner Shopify /products.json (offentlig endpoint) og finder varianter hvor
    tekst matcher queries.

    Returnerer liste af:
      {
        "name": str,
        "price": float,
        "available": bool
      }
    """

    page = 1
    products = []
    queries_l = [q.lower() for q in queries]

    # Ord vi IKKE vil have
    banned_language_words = [
        "japanese",
        "japansk",
        "korean",
        "koreansk",
        "chinese",
        "kinesisk",
    ]

    banned_graded_words = [
        "psa",
        "bgs",
        "cgc",
        "graded",
    ]

    banned_single_card_indicators = [
        "#",  # kortnummer
        "art rare",
        "illustration rare",
        "secret rare",
        "ultra rare",
        "single card",
        "holo",
        "reverse holo",
    ]

    # Vi KRÆVER at det er sealed produkt
    required_product_words = [
        "booster",
        "box",
        "bundle",
        "collection",
        "elite trainer",
        "etb",
        "tin",
    ]

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

            title = (product.get("title") or "").lower()

            # Matcher vores søgninger?
            if not any(q in full_text for q in queries_l):
                continue

            # ----------- FILTRERING -----------

            # Fjern sprog vi ikke vil have
            if any(word in title for word in banned_language_words):
                continue

            # Fjern graded / PSA
            if any(word in title for word in banned_graded_words):
                continue

            # Fjern enkeltkort
            if any(word in title for word in banned_single_card_indicators):
                continue

            # Kræv sealed produkt
            if not any(word in title for word in required_product_words):
                continue

            # ----------------------------------

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
