import re
import requests
from pokemon_price_tracker.product_grouping import detect_series


RARITY_WORDS = [
    "common", "uncommon", "rare", "double rare",
    "ultra rare", "secret rare", "illustration rare", "art rare",
    "holo", "reverse holo", "reverse-holo", "reverseholo",
]

CONDITION_WORDS = [
    "near mint", "nm", "lp", "mp", "hp", "played", "damaged",
    "reverse-holo normal",
]

CARD_NO_BRACKET_RE = re.compile(r"\[[a-z0-9\-]{2,}\]", re.IGNORECASE)
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
    if re.search(r"\((common|uncommon|rare)\)", t):
        return True

    return False


def _series_hint_from_queries(full_text_lower: str) -> str:
    """
    LØS 151:
      - hvis der står 151 som helt tal, så tag det som SV151
    """
    t = full_text_lower or ""

    # Mega Evolution sub-sets
    if "ascended heroes" in t:
        return "Mega Evolution - Ascended Heroes"
    if "phantasmal flames" in t:
        return "Mega Evolution - Phantasmal Flames"
    if "perfect order" in t:
        return "Mega Evolution - Perfect Order"

    # Mega Evolution generic
    if "mega evolution" in t or "mega evolutions" in t:
        return "Mega Evolution"

    # SV151 (LØS)
    if re.search(r"\b151\b", t):
        return "Scarlet & Violet 151"

    # Crown Zenith / Prismatic
    if "crown zenith" in t:
        return "Crown Zenith"
    if "prismatic evolution" in t or "prismatic evolutions" in t:
        return "Prismatic Evolutions"

    return "Unknown Series"


def scan_shopify_store_json(domain: str, queries: list[str]) -> list[dict]:
    page = 1
    products = []
    queries_l = [q.lower() for q in queries]

    banned_language_words = [
        "japanese", "japansk", "korean", "koreansk", "chinese", "kinesisk",
        "german", "tysk", "french", "fransk",
    ]

    banned_graded_words = ["psa", "bgs", "cgc", "graded", "slab"]

    required_product_words = [
        "booster", "box", "bundle", "collection",
        "elite trainer", "etb", "tin", "blister",
        "display", "sticker", "poster", "figure", "pin",
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

            full_text = f"{title_raw} {body_raw} {ptype_raw}"
            full_text_l = full_text.lower()
            title_l = title_raw.lower()

            # Matcher queries?
            if not any(q in full_text_l for q in queries_l):
                continue

            # Udeluk
            if any(word in title_l for word in banned_language_words):
                continue
            if any(word in title_l for word in banned_graded_words):
                continue
            if looks_like_single_card(title_raw) or looks_like_single_card(full_text):
                continue

            # Kræv sealed
            if not any(word in title_l for word in required_product_words):
                continue

            # Hint + fallback detektion
            series_hint = _series_hint_from_queries(full_text_l)
            if series_hint == "Unknown Series":
                series_hint = detect_series(full_text)

            for variant in product.get("variants", []):
                try:
                    price = float(variant["price"])
                except Exception:
                    continue

                variant_title = variant.get("title", "")
                variant_name = "" if variant_title == "Default Title" else variant_title
                full_name = f"{title_raw.strip()} {variant_name}".strip()

                if looks_like_single_card(full_name):
                    continue

                products.append(
                    {
                        "name": full_name,
                        "price": price,
                        "available": bool(variant.get("available", False)),
                        "series_hint": series_hint,
                        "grouping_text": full_text,
                    }
                )

        page += 1

    return products
