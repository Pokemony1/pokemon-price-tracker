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


def _extract_product_urls(category_html: str) -> list[str]:
    urls = []
    seen = set()

    for match in re.finditer(
        r'''href=["']([^"']*?/shop/[^"']+?p\.html(?:\?[^"']*)?)["']''',
        category_html or "",
        re.IGNORECASE,
    ):
        href = html_lib.unescape((match.group(1) or "").strip())
        full_url = urljoin(BASE_URL, href)

        if not re.search(r"/shop/.+p\.html(?:\?.*)?$", full_url, re.IGNORECASE):
            continue

        if full_url in seen:
            continue

        seen.add(full_url)
        urls.append(full_url)

    return urls


def _extract_title(product_html: str) -> str:
    # og:title er ofte mest stabil
    m = re.search(
        r'''<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']''',
        product_html or "",
        re.IGNORECASE,
    )
    if m:
        title = html_lib.unescape(m.group(1)).strip()
        if title:
            return title

    # fallback: <h1>
    m = re.search(r"(?is)<h1\b[^>]*>(.*?)</h1>", product_html or "")
    if m:
        title = _strip_tags(m.group(1))
        if title:
            return title

    # fallback: <title>
    m = re.search(r"(?is)<title\b[^>]*>(.*?)</title>", product_html or "")
    if m:
        title = _strip_tags(m.group(1))
        if title:
            return title

    return ""


def _extract_price(product_html: str):
    # prøv først at finde pris tæt på ordet "Pris"
    m = re.search(
        r"(?is)pris.{0,200}?(\d{1,3}(?:\.\d{3})*,\d{2})\s*DKK",
        product_html or "",
    )
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except Exception:
            pass

    # fallback: første pris på siden
    text = _strip_tags(product_html)
    return _parse_price(text)


def _extract_available(product_html: str) -> bool:
    t = _normalize(_strip_tags(product_html))

    sold_out_markers = [
        "udsolgt",
        "ikke på lager",
        "not available",
        "sold out",
        "ikke tilgængelig",
    ]
    in_stock_markers = [
        "på lager",
        "in stock",
        "lagerstatus på lager",
    ]

    if any(marker in t for marker in sold_out_markers):
        return False

    if any(marker in t for marker in in_stock_markers):
        return True

    # Hvis markup ændrer sig, så mister vi ikke produktet
    return True


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

        product_urls = _extract_product_urls(category_html)
        print(f"epicpanda: fandt {len(product_urls)} produktlinks i {series_hint}")

        seen_urls = set()

        for product_url in product_urls:
            if product_url in seen_urls:
                continue
            seen_urls.add(product_url)

            try:
                resp = session.get(product_url, timeout=30)
                resp.raise_for_status()
                product_html = resp.text
            except Exception as e:
                print(f"Fejl ved hentning af produkt {product_url}: {e}")
                continue

            title = _extract_title(product_html)
            if not title:
                continue

            if not _is_valid_title(title):
                continue

            price = _extract_price(product_html)
            if price is None or price <= 0:
                continue

            available = _extract_available(product_html)

            all_products.append(
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

    print(f"epicpanda: hentede {len(all_products)} produkter i alt")
    return all_products