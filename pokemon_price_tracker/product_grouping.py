import re
from typing import Optional, Tuple


# ----------------------------
# Helpers: normalisering
# ----------------------------
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
# (kun for dine queries – kan udvides)
# ----------------------------
SERIES_PATTERNS = [
    ("Mega Evolution", [r"\bmega evolution(s)?\b"]),
    ("Crown Zenith", [r"\bcrown zenith\b"]),
    ("Prismatic Evolutions", [r"\bprismatic evolution(s)?\b"]),
    ("Scarlet & Violet 151", [r"\bscarlet\s*&\s*violet\s*151\b", r"\bsv\s*151\b", r"\bpokemon\s*151\b"]),
]

def detect_series(title: str) -> str:
    t = _clean(title)
    for series_name, pats in SERIES_PATTERNS:
        for p in pats:
            if re.search(p, t):
                return series_name
    # fallback: ukendt serie – men stadig track hvis sealed
    return "Unknown Series"


# ----------------------------
# Multi/Count detektion (må ikke blandes)
# ----------------------------
def detect_count_tag(title: str) -> Optional[str]:
    """
    Returnerer noget som '8x', '3x', '36 packs', '6 packs' osv.
    Formål: sørg for at display/multi ikke blandes med single.
    """
    t = _clean(title)

    # "display", "tin display", "mini tin display" osv.
    # Hvis der står display OG en x-count, behold count.
    m = re.search(r"\b(\d{1,3})\s*x\b", t)
    if m:
        return f"{m.group(1)}x"

    # "36 booster packs", "6 booster packs", "2 booster packs" osv.
    m = re.search(r"\b(\d{1,3})\s*(booster\s*packs|packs)\b", t)
    if m:
        return f"{m.group(1)} packs"

    # "case of 6", "pack of 3" etc. (sjældnere DK, men safe)
    m = re.search(r"\b(pack|case)\s*of\s*(\d{1,3})\b", t)
    if m:
        return f"{m.group(2)}x"

    return None


# ----------------------------
# Produkttype detektion
# ----------------------------
TYPE_RULES = [
    ("Elite Trainer Box", [r"\belite trainer box\b", r"\betb\b"]),
    ("Pokemon Center ETB Plus", [r"\bpokemon center\b.*\betb\b", r"\betb\b.*\bplus\b"]),
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
    """
    Returnerer:
      group_key: stabil nøgle til gruppering (serie|type|count)
      canonical_name: pænt navn til Sheets, uden variant-navne
    """
    series = detect_series(product_title)
    ptype = detect_type(product_title)
    count_tag = detect_count_tag(product_title)

    # count_tag skal KUN sættes når det giver mening at skille dem ad
    # fx "Mini Tin Display (8x tins)" => 8x
    # fx "Pin Collection Blister 3x ..." => 3x
    # fx "Booster Box ... 36 Booster Packs" => 36 packs
    key = f"{series}|{ptype}|{count_tag or ''}"

    # Pænt navn
    if count_tag:
        canonical = f"{series}: {ptype} ({count_tag})"
    else:
        canonical = f"{series}: {ptype}"

    return key, canonical
