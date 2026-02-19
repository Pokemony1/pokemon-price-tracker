import re
import requests


# -------- Singles (kort) indikatorer --------
RARITY_WORDS = [
    "common", "uncommon", "rare", "double rare",
    "ultra rare", "secret rare", "illustration rare", "art rare",
    "holo", "reverse holo", "reverse-holo", "reverseholo",
]

CONDITION_WORDS = [
    "near mint", "nm", "lp", "mp", "hp", "played", "damaged",
    "english / near mint", "reverse-holo normal",
]

# Kortnummer i [MEG-098], [SV1-123] osv.
CARD_NO_BRACKET_RE = re.compile(r"\[[a-z0-9\-]{2,}\]", re.IGNORECASE)

# "English / Near Mint / ..." mønster
SLASHY_CONDITION_RE = re.compile(r"\b(english|near mint|reverse|holo)\b.*\/", re.IGNORECASE)


def looks_like_single_card(title_or_text: str) -> bool:
    t = (title_or_text or "").lower()

    if CARD_NO_BRACKET_RE.search(t):
        return True

    if SLASHY_CONDITION_RE.search(t):
        return True

    if any(w in t for w in RARITY_WORDS):
        return True

    if any(w in t for w in CONDITION_WORDS):
        return True

    # Mange singles har mønstre som "(Uncommon)" eller "(Common)"
    if re.search(r"\((common|uncommon|rare)\)", t):
        return True

    return False


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

    banned_language_words = [
        "japanese", "japansk", "korean", "koreansk", "chinese", "kinesisk",
        "german", "tysk", "french", "fransk",
    ]

    banned_graded_words = [
        "psa", "bgs", "cgc", "graded", "slab",
    ]

    # Vi KRÆVER sealed produkt
    required_product_words = [
        "booster", "box", "bundle", "collection",
        "elite trainer", "etb", "tin", "blister",
        "display",  # display er stadig sealed, men håndteres i grouping (8x osv.)
        "sticker", "poster", "figure", "pin",
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
            title_raw = (product.get("title") or "")
            body_raw = (product.get("body_html") or "")
            ptype_raw = (product.get("product_type") or "")

            full_text = (title_raw + " " + body_raw + " " + ptype_raw).lower()
            title = title_raw.lower()

            # Matcher queries?
            if not any(q in full_text for q in queries_l):
                continue

            # ---- Hårde udelukkelser ----
            if any(word in title for word in banned_language_words):
                continue

            if any(word in title for word in banned_graded_words):
                continue

            # Singles check (kort)
            if looks_like_single_card(title_raw) or looks_like_single_card(full_text):
                continue

            # Kræv sealed (titel)
            if not any(word in title for word in required_product_words):
                continue
            # ----------------------------

            for variant in product.get("variants", []):
                try:
                    price = float(variant["price"])
                except Exception:
                    continue

                variant_title = variant.get("title", "")
                variant_name = "" if variant_title == "Default Title" else variant_title

                full_name = f"{title_raw.strip()} {variant_name}".strip()

                # variant kan også indeholde singles/condition ting
                if looks_like_single_card(full_name):
                    continue

                products.append(
                    {
                        "name": full_name,
                        "price": price,
                        "available": bool(variant.get("available", False)),
                    }
                )

        page += 1

    return products
