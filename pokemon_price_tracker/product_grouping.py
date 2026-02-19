import re
from typing import Optional, Tuple

_ws_re = re.compile(r"\s+")
_punct_re = re.compile(r"[^\w\s&x\-]+")

def _clean(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    s = s.replace("–", "-").replace("—", "-")
    s = _punct_re.sub(" ", s)
    s = _ws_re.sub(" ", s).strip()
    return s


# ----------------------------
# Serie / Set detektion
# (bemærk: specifikke Mega Evolution "sub-sets" skal matche før generic)
# ----------------------------
SERIES_PATTERNS = [
    # Mega Evolution sub-sets (eksempler du nævnte)
    ("Mega Evolution - Ascended Heroes", [r"\bascended heroes\b"]),
    ("Mega Evolution - Phantasmal Flames", [r"\bphantasmal flames\b"]),
    ("Mega Evolution - Perfect Order", [r"\bperfect order\b"]),

    # Generel Mega Evolution (fallback)
    ("Mega Evolution", [r"\bmega evolution(s)?\b"]),

    # Crown Zenith
    ("Crown Zenith", [r"\bcrown zenith\b"]),

    # Prismatic
    ("Prismatic Evolutions", [r"\bprismatic evolution(s)?\b"]),

    # SV 151 (flere stavemåder)
    ("Scarlet & Violet 151", [
        r"\bscarlet\s*&\s*violet\s*:?\s*151\b",
        r"\bscarlet\s*and\s*violet\s*:?\s*151\b",
        r"\bsv\s*151\b",
        r"\bpokemon\s*151\b",
    ]),
]

def detect_series(title: str) -> str:
    t = _clean(title)
    for series_name, pats in SERIES_PATTERNS:
        for p in pats:
            if re.search(p, t):
                return series_name
    return "Unknown Series"


# ----------------------------
# Multi/Count detektion (må ikke blandes)
# ----------------------------
def detect_count_tag(title: str) -> Optional[str]:
    t = _clean(title)

    # 8x, 3x osv.
    m = re.search(r"\b(\d{1,3})\s*x\b", t)
    if m:
        return f"{m.group(1)}x"

    # 36 booster packs / 6 booster packs / 2 booster packs osv.
    m = re.search(r"\b(\d{1,3})\s*(booster\s*packs|packs)\b", t)
    if m:
        return f"{m.group(1)} packs"

    # pack/case of N
    m = re.search(r"\b(pack|case)\s*of\s*(\d{1,3})\b", t)
    if m:
        return f"{m.group(2)}x"

    return None


# ----------------------------
# Produkttype detektion
# ----------------------------
TYPE_RULES = [
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


def build_group_key_and_name(product_title: str) -> Tuple[str, str]:
    series = detect_series(product_title)
    ptype = detect_type(product_title)
    count_tag = detect_count_tag(product_title)

    key = f"{series}|{ptype}|{count_tag or ''}"

    if count_tag:
        canonical = f"{series}: {ptype} ({count_tag})"
    else:
        canonical = f"{series}: {ptype}"

    return key, canonical
