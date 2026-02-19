import re
import requests
from pokemon_price_tracker.product_grouping import detect_series


# -------- Singles (kort) indikatorer --------
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


# alle de 151-queries vi betragter som “sikker 151”
_151_QUERY_MARKERS = {
    "151",
    "pokemon 151",
    "sv 151",
    "sv: 151",
    "sv-151",
    "sv_151",
    "sv151",
    "s&v 151",
    "s&v: 151",
    "s&v-151",
    "s&v151",
    "s/v 151",
    "scarlet & violet 151",
    "scarlet and violet 151",
    "scarlet violet 151",
}


def _series_hint_from_matches(full_text_lower: str, matched_queries: list[str]) -> str:
    """
    Mere “åben” serie-detektion:
      - Hvis en 151-query matchede -> 151
      - Ellers hvis teksten har 151 som helt tal -> 151
      - Ellers de andre serier som før
    """
    t = full_text_lower or ""
    mq = set((q or "").strip().lower() for q in matched_queries or [])

    # Mega Evolution sub-sets
    if "ascended heroes" in t or "ascended heroes" in mq:
        return "Mega Evolution - Ascended Heroes"
    if "phantasmal flames" in t or "phantasmal flames" in mq:
        return "Mega Evolution - Phantasmal Flames"
    if "perfect order" in t or "perfect order" in mq:
        return "Mega Evolution - Perfect Order"

    # Mega Evolution generic
    if ("mega evolution" in t) or ("mega evolutions" in t) or ("mega evolution" in mq) or ("mega evolutions" in mq):
        return "Mega Evolution"

    # SV151 (åben)
    if mq.intersection(_151_QUERY_MARKERS):
        return "Scarlet & Violet 151"
    if re.search(r"\b151\b", t):
        return "Scarlet & Violet 151"

    # Crown Zenith / Prismatic
    if "crown zenith" in t or "crown zenith" in mq:
        return "Crown Zenith"
    if ("prismatic evolution" in t) or ("prismatic evolutions" in t) or ("prismatic evolution" in mq) or ("prismatic evolutions" in mq):
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

            # hvilke queries matchede?
            matched = [q for q in queries_l if q and (q in full_text_l)]
            if not matched:
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
            series_hint = _series_hint_from_matches(full_text_l, matched)
            if series_hint == "Unknown Series":
                # fallback: prøv serie på full_text (title+body+product_type)
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
                        "matched_queries": matched,
                    }
                )

        page += 1

    return products
