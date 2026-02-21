import requests
from pokemon_price_tracker.product_grouping import detect_series
from pokemon_price_tracker.shopify_scraper import looks_like_single_card, _series_hint_from_matches


def _wc_price_to_float(prices_obj: dict) -> float | None:
    """
    Woo Store API: prices.price er ofte i minor units (fx '49900' med minor=2)
    """
    if not isinstance(prices_obj, dict):
        return None

    raw = prices_obj.get("price") or prices_obj.get("regular_price") or prices_obj.get("sale_price")
    if raw is None:
        return None

    try:
        minor = int(prices_obj.get("currency_minor_unit", 2))
    except Exception:
        minor = 2

    s = str(raw).strip()
    if not s:
        return None

    if s.isdigit():
        return int(s) / (10 ** minor)

    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def scan_woocommerce_store_api(domain: str, queries: list[str]) -> list[dict]:
    """
    Returnerer samme dict-format som shopify_scraper:
      name, price, available, series_hint, grouping_text, matched_queries, url
    """
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

    bases = [f"https://{domain}", f"https://www.{domain}"]
    endpoints = [
        "/wp-json/wc/store/products",
        "/?rest_route=/wc/store/products",
    ]

    products: list[dict] = []

    for base in bases:
        for ep in endpoints:
            page = 1
            any_ok = False

            while True:
                url = f"{base}{ep}?per_page=100&page={page}"
                print(f"Henter Woo JSON: {url}")

                try:
                    r = requests.get(url, timeout=30)
                    if r.status_code >= 400:
                        break
                    data = r.json()
                except Exception:
                    break

                if not isinstance(data, list):
                    break

                any_ok = True
                if not data:
                    break

                for p in data:
                    title_raw = (p.get("name") or "")
                    if not title_raw:
                        continue

                    desc_raw = (p.get("description") or "") + " " + (p.get("short_description") or "")
                    cats = p.get("categories") or []
                    cat_text = " ".join([(c.get("name") or "") for c in cats if isinstance(c, dict)])

                    full_text = f"{title_raw} {desc_raw} {cat_text}"
                    full_text_l = full_text.lower()
                    title_l = title_raw.lower()

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

                    prices_obj = p.get("prices") or {}
                    price = _wc_price_to_float(prices_obj)
                    if price is None:
                        continue

                    series_hint = _series_hint_from_matches(full_text_l, matched)
                    if series_hint == "Unknown Series":
                        series_hint = detect_series(full_text)

                    products.append(
                        {
                            "name": title_raw.strip(),
                            "price": float(price),
                            "available": bool(p.get("is_in_stock", False)),
                            "series_hint": series_hint,
                            "grouping_text": full_text,
                            "matched_queries": matched,
                            "url": (p.get("permalink") or "").strip() or base,
                        }
                    )

                page += 1
                if page > 60:  # safety stop (~6000 produkter)
                    break

            if any_ok:
                return products

    return products