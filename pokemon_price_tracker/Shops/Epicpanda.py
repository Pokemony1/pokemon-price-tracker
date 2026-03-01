import html as html_lib
import re
from urllib.parse import urljoin

import requests

from pokemon_price_tracker.queries import QUERIES
from pokemon_price_tracker.shopify_scraper import looks_like_single_card

SHOP_NAME = "epicpanda"
BASE_URL = "https://epicpanda.dk"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
}

PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*DKK", re.IGNORECASE)

SERIES_PAGES = [
    {
        "series_hint": "Scarlet & Violet 151",
        "url": f"{BASE_URL}/shop/pokemon-serie-scarlet-1198c1.html",
        "query_markers": {
            "pokemon 151",
            "pokémon 151",
            "pokemon151",
            "pokémon151",
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
        },
    },
    {
        "series_hint": "Prismatic Evolutions",
        "url": f"{BASE_URL}/shop/pokemon-serie-scarlet-1341c1.html",
        "query_markers": {
            "prismatic evolution",
            "prismatic evolutions",
        },
    },
    {
        "series_hint": "Mega Evolution - Perfect Order",
        "url": f"{BASE_URL}/shop/pokemon-perfect-order-1406c1.html",
        "query_markers": {
            "perfect order",
        },
    },
    {
        "series_hint": "Mega Evolution - Ascended Heroes",
        "url": f"{BASE_URL}/shop/pokemon-ascended-heroes-1400c1.html",
        "query_markers": {
            "ascended heroes",
        },
    },
    {
        "series_hint": "Mega Evolution - Phantasmal Flames",
        "url": f"{BASE_URL}/shop/phantasmal-flames-1384c1.html",
        "query_markers": {
            "phantasmal flames",
        },
    },
    {
        "series_hint": "Mega Evolution",
        "url": f"{BASE_URL}/shop/pokemon-serie-mega-1378c1.html",
        "query_markers": {
            "mega evolution",
            "mega evolutions",
        },
    },
]

REQUIRED_PRODUCT_WORDS = [
    "booster",
    "box",
    "bundle",
    "collection",
    "elite trainer",
    "etb",
    "tin",
    "blister",
    "display",
    "sticker",
    "poster",
    "figure",
    "pin",
    "premium",
]

BANNED_LANGUAGE_WORDS = [
    "japanese",
    "japansk",
    "korean",
    "koreansk",
    "chinese",
    "kinesisk",
    "german",
    "tysk",
    "french",
    "fransk",
]

BANNED_GRADED_WORDS = ["psa", "bgs", "cgc", "graded", "slab"]


def _normalize(text: str) -> str:
    text = html_lib.unescape((text or "").replace("\xa0", " "))
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"(?is)<script\b.*?</script>", " ", fragment or "")
    fragment = re.sub(r"(?is)<style\b.*?</style>", " ", fragment)
    fragment = re.sub(r"(?is)<[^>]+>", " ", fragment)
    fragment = html_lib.unescape(fragment)
    fragment = fragment.replace("\xa0", " ")
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment


def _parse_price(text: str):
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None


def _clean_product_url(href: str) -> str:
    href = html_lib.unescape((href or "").strip())

    # fix skjulte mellemrum / nbsp i URLs (fx Magneton-linket)
    href = href.replace("\xa0", "")
    href = href.replace("%C2%A0", "")
    href = href.replace("%c2%a0", "")
    href = href.replace(" -", "-")
    href = href.replace("- ", "-")
    href = href.replace(" ", "-")

    full_url = urljoin(BASE_URL, href)

    # ekstra cleanup hvis encoded nbsp stadig er i den fulde URL
    full_url = full_url.replace("%C2%A0", "")
    full_url = full_url.replace("%c2%a0", "")

    return full_url


def _is_valid_title(title: str) -> bool:
    t = _normalize(title)

    if not t:
        return False

    if any(word in t for word in BANNED_LANGUAGE_WORDS):
        return False

    if any(word in t for word in BANNED_GRADED_WORDS):
        return False

    if looks_like_single_card(t):
        return False

    if not any(word in t for word in REQUIRED_PRODUCT_WORDS):
        return False

    return True


def _matched_queries_for_page(page_markers: set[str], queries: list[str]) -> list[str]:
    qset = {(q or "").strip().lower() for q in (queries or []) if q}
    return sorted(qset.intersection({x.lower() for x in page_markers}))


def _extract_products_from_category_html(category_html: str, series_hint: str, matched_queries: list[str]) -> list[dict]:
    products = []
    seen_urls = set()

    # Find kun rigtige produktlinks i /shop/...p.html
    matches = list(
        re.finditer(
            r'''<a\b[^>]*href=["']([^"']*?/shop/[^"']+?p\.html(?:\?[^"']*)?)["'][^>]*>(.*?)</a>''',
            category_html or "",
            re.IGNORECASE | re.DOTALL,
        )
    )

    for i, match in enumerate(matches):
        href = match.group(1)
        inner_html = match.group(2)

        title = _strip_tags(inner_html)
        if not title:
            continue

        if not _is_valid_title(title):
            continue

        product_url = _clean_product_url(href)
        if not product_url or product_url in seen_urls:
            continue

        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(category_html)
        snippet = category_html[match.end():next_start]

        # kig kun lidt frem, så vi holder os til det relevante produktområde
        snippet = snippet[:1500]
        snippet_text = _strip_tags(snippet)
        snippet_norm = _normalize(snippet_text)

        price = _parse_price(snippet_text)
        if price is None or price <= 0:
            continue

        available = True
        if "udsolgt" in snippet_norm or "ikke på lager" in snippet_norm or "sold out" in snippet_norm:
            available = False
        elif "på lager" in snippet_norm or "in stock" in snippet_norm:
            available = True

        products.append(
            {
                "name": title.strip(),
                "price": float(price),
                "available": bool(available),
                "series_hint": series_hint,
                "grouping_text": title.strip(),
                "matched_queries": matched_queries,
                "url": product_url,
                "shop_source": "epicpanda",
            }
        )

        seen_urls.add(product_url)

    return products


def get_products():
    all_products = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in SERIES_PAGES:
        matched_queries = _matched_queries_for_page(page["query_markers"], QUERIES)
        if not matched_queries:
            continue

        category_url = page["url"]
        series_hint = page["series_hint"]

        print(f"\n--- Scanner epicpanda ({series_hint}) ---")

        try:
            resp = session.get(category_url, timeout=30)
            resp.raise_for_status()
            category_html = resp.text
        except Exception as e:
            print(f"Fejl ved hentning af kategori {category_url}: {e}")
            continue

        products = _extract_products_from_category_html(
            category_html=category_html,
            series_hint=series_hint,
            matched_queries=matched_queries,
        )

        print(f"epicpanda: fandt {len(products)} produkter i {series_hint}")
        all_products.extend(products)

    print(f"epicpanda: hentede {len(all_products)} produkter i alt")
    return all_products