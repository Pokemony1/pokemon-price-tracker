# pokemon_price_tracker/product_grouping.py
import re
from typing import Optional, Tuple

_ws_re = re.compile(r"\s+")
_punct_re = re.compile(r"[^\w\s&x\-\/]+")


def _clean(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    s = s.replace("–", "-").replace("—", "-")
    s = _punct_re.sub(" ", s)
    s = _ws_re.sub(" ", s).strip()
    return s


SERIES_PATTERNS = [
    ("Mega Evolution - Ascended Heroes", [r"\bascended heroes\b"]),
    ("Mega Evolution - Phantasmal Flames", [r"\bphantasmal flames\b"]),
    ("Mega Evolution - Perfect Order", [r"\bperfect order\b"]),
    ("Mega Evolution", [r"\bmega evolution(s)?\b"]),
    ("Crown Zenith", [r"\bcrown zenith\b"]),
    ("Prismatic Evolutions", [r"\bprismatic evolution(s)?\b"]),

    ("Scarlet & Violet 151", [
        r"\b(pokemon|pok[eé]mon)\b.*\b151\b",
        r"\b151\b.*\b(pokemon|pok[eé]mon)\b",
        r"\b(pokemon|pok[eé]mon)\s*151\b",
        r"\bsv\s*:?[\s\-_]*151\b",
        r"\bsv151\b",
        r"\bscarlet\s*&\s*violet\s*:?\s*151\b",
        r"\bscarlet\s*and\s*violet\s*:?\s*151\b",
        r"\bscarlet\s+violet\s*:?\s*151\b",
        r"\bs\s*&\s*v\s*:?[\s\-_]*151\b",
        r"\bs&v\s*:?[\s\-_]*151\b",
        r"\bs\/v\s*151\b",
    ]),
]


def detect_series(text: str) -> str:
    t = _clean(text)
    for series_name, pats in SERIES_PATTERNS:
        for p in pats:
            if re.search(p, t):
                return series_name
    return "Unknown Series"


def detect_count_tag(title: str) -> Optional[str]:
    t = _clean(title)

    m = re.search(r"\b(\d{1,3})\s*x\b", t)
    if m:
        return f"{m.group(1)}x"

    m = re.search(r"\b(\d{1,3})\s*(booster\s*packs|packs)\b", t)
    if m:
        return f"{m.group(1)} packs"

    if "display" in t:
        m = re.search(r"\b(alle|all)\s*(\d{1,3})\b", t)
        if m:
            return f"{m.group(2)}x"
        m = re.search(r"\b(\d{1,3})\s*(mini\s*tins?|tins?)\b", t)
        if m:
            return f"{m.group(1)}x"

    m = re.search(r"\b(pack|case)\s*of\s*(\d{1,3})\b", t)
    if m:
        return f"{m.group(2)}x"

    return None


TYPE_RULES = [
    ("Ultra Premium Collection", [r"\bultra premium collection\b", r"\bupc\b"]),
    ("Pokemon Center ETB Plus", [r"\bpokemon center\b.*\betb\b", r"\betb\b.*\bplus\b"]),
    ("Elite Trainer Box", [r"\belite trainer box\b", r"\betb\b"]),
    ("Booster Box", [r"\bbooster box\b"]),
    ("Booster Bundle", [r"\bbooster bundle\b"]),
    ("Booster Pack", [r"\bbooster pack\b", r"\b1\s*pack\b"]),
    ("Mini Tin Display", [r"\bmini tin\b.*\bdisplay\b", r"\btin\b.*\bdisplay\b"]),
    ("Mini Tin", [r"\bmini tin\b"]),
    ("Tin", [r"\btin\b"]),
    ("Premium Poster Collection", [r"\bpremium poster collection\b"]),
    ("Premium Figure Collection", [r"\bpremium figure collection\b"]),
    ("Special Collection", [r"\bspecial collection\b"]),
    ("Pin Collection Blister", [r"\bpin collection\b.*\bblister\b", r"\bpin collection blister\b"]),
    ("Tech Sticker Collection", [r"\btech sticker collection\b"]),
    ("Sticker Collection", [r"\bsticker collection\b"]),
    ("Blister 3-Pack", [r"\bblister\b.*\b3\s*pack\b", r"\b3\s*pack\b", r"\bblister 3\b"]),
    ("Blister", [r"\bblister\b"]),
    ("Collection", [r"\bcollection\b"]),
    ("Bundle", [r"\bbundle\b"]),
    ("Box", [r"\bbox\b"]),
]


def detect_type(title: str) -> str:
    t = _clean(title)
    for type_name, pats in TYPE_RULES:
        for p in pats:
            if re.search(p, t):
                return type_name
    return "Sealed Product"


THEME_STOPWORDS = {
    "pokemon", "center", "plus", "elite", "trainer", "box", "etb",
    "english", "sealed", "preorder", "pre-order", "pre", "order",
    "edition", "limited", "new", "promo",
    "for", "forudbestil", "forudbestilling", "forudbestilles",
    "mega", "evolution",

    # nye stopwords for at undgå falske ETB-temaer
    "case", "kort", "card", "cards",
    "scarlet", "violet",
    "prismatic", "evolutions", "evolution",
    "pokemonkort", "tcg",
    "inkl", "inklusive", "with",
}


def detect_theme(title: str, ptype: str) -> Optional[str]:
    """
    Udtræk kun tema for ETB'er når det ligner et rigtigt karakter/variant-navn.
    Vi vil IKKE bruge generiske ord som 'Case', 'Kort', 'Scarlet' osv.
    """
    if "ETB" not in (ptype or "") and "Elite Trainer Box" not in (ptype or ""):
        return None

    t = _clean(title)

    # Efter "etb" eller "elite trainer box"
    m = re.search(r"\b(elite trainer box|etb)\b\s*[:\-]?\s*(.+)$", t)
    cand = None
    if m:
        cand = m.group(2)
    else:
        # Parentheser: "... ETB (Glaceon)"
        m2 = re.search(r"\b(etb|elite trainer box)\b.*\(([^)]+)\)", t)
        if m2:
            cand = m2.group(2)

    if not cand:
        return None

    # Hvis halen tydeligt bare beskriver retail-format, så intet tema
    retail_noise_patterns = [
        r"\bcase\b",
        r"\bkort\b",
        r"\bcard(s)?\b",
        r"\b10x\b",
        r"\bscarlet\b",
        r"\bviolet\b",
        r"\bprismatic\b",
        r"\bevolution(s)?\b",
    ]
    if any(re.search(p, cand) for p in retail_noise_patterns):
        return None

    tokens = [tok for tok in re.split(r"[\s\-\/]+", cand.strip()) if tok]
    for tok in tokens:
        if tok.isdigit():
            continue
        if tok in THEME_STOPWORDS:
            continue
        if len(tok) < 3:
            continue

        # undgå rene model/seriekoder
        if re.fullmatch(r"[a-z]{1,3}\d{1,3}", tok):
            continue

        return tok.replace("-", " ").title()

    return None


def build_group_key_and_name(
    product_title: str,
    extra_text: Optional[str] = None,
    series_hint: Optional[str] = None,
) -> Tuple[str, str]:
    if series_hint and series_hint != "Unknown Series":
        series = series_hint
    else:
        series = detect_series(product_title)
        if series == "Unknown Series" and extra_text:
            series = detect_series(extra_text)

    ptype = detect_type(product_title)
    count_tag = detect_count_tag(product_title)
    theme = detect_theme(product_title, ptype)

    canonical = f"{series}: {ptype}"
    if count_tag:
        canonical += f" ({count_tag})"
    if theme:
        canonical += f" - {theme}"

    key_parts = [
        _clean(series),
        _clean(ptype),
        _clean(count_tag or ""),
        _clean(theme or ""),
    ]
    key = "|".join(key_parts)

    return key, canonical