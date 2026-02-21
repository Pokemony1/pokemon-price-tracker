import os
import datetime
import statistics
import importlib
import pkgutil
from typing import Optional, Dict, Tuple, List

import gspread

from pokemon_price_tracker.google_sheet import connect_google_sheet
from pokemon_price_tracker.push_notification import send_push
from pokemon_price_tracker.product_grouping import build_group_key_and_name


# ----------------- KONFIG -----------------
SHEET_SUMMARY_TITLE = "Sheet1"
SHEET_IN_STOCK_TITLE = "Billigste in stock"
SHEET_RAW_TITLE = "RawOffers"

MIN_HISTORY_FOR_PUSH = 5
DISCOUNT_PCT = 0.15
MAX_PUSH_LINES = 20

SNAPSHOT_HEADERS = ["Product", "Median", "Price", "Prev Price", "Δ", "Δ%", "Shop", "Stock", "Updated"]
# ------------------------------------------


def load_shops():
    shops = []
    package_path = os.path.join(os.path.dirname(__file__), "Shops")
    package_name = "pokemon_price_tracker.Shops"

    for _, module_name, _ in pkgutil.iter_modules([package_path]):
        module = importlib.import_module(f"{package_name}.{module_name}")
        if hasattr(module, "get_products"):
            shop_label = getattr(module, "SHOP_NAME", module_name)
            shops.append((shop_label, module))
    return shops


def parse_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def make_shop_cell(shop_label: str, url: str) -> str:
    """
    Returner en klikbar HYPERLINK-formel hvis url findes,
    ellers bare shop_label.
    """
    if not url:
        return str(shop_label)

    safe_url = str(url).replace('"', "%22")
    safe_text = str(shop_label).replace('"', "'") or "link"
    return f'=HYPERLINK("{safe_url}","{safe_text}")'


def ensure_raw_headers(raw_ws):
    wanted = ["Timestamp", "Date", "Product", "Price", "Shop", "URL", "Available"]
    header = raw_ws.row_values(1)
    if header != wanted:
        raw_ws.update("A1:G1", [wanted])


def append_raw_offers(raw_ws, today_str: str, offers_by_group: Dict[str, list], group_name_map: Dict[str, str]):
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for gkey, offers in offers_by_group.items():
        canonical_name = group_name_map.get(gkey, gkey)
        for price, shop, available, url in offers:
            rows.append([
                now_ts,
                today_str,
                canonical_name,
                str(price),
                shop,
                url or "",
                "TRUE" if available else "FALSE",
            ])

    if rows:
        raw_ws.append_rows(rows, value_input_option="USER_ENTERED")


def _bool_from_raw(s: str) -> bool:
    s = (s or "").strip().upper()
    return s in ("TRUE", "1", "YES", "IN_STOCK")


# ----------------- VÆLG BILLIGSTE -----------------
def choose_cheapest_overall(offers: List[Tuple[float, str, bool, str]]):
    # 100% billigste uanset lager
    return min(offers, key=lambda t: t[0])


def choose_cheapest_in_stock(offers: List[Tuple[float, str, bool, str]]):
    # Kun in-stock. Returnér None hvis intet er på lager (så produktet ikke kommer med).
    in_stock = [o for o in offers if o[2] is True]
    if not in_stock:
        return None
    return min(in_stock, key=lambda t: t[0])


# ----------------- SNAPSHOT HELPERS -----------------
def get_prev_price_map(ws) -> Dict[str, float]:
    """
    Læs forrige snapshot (kolonne A=Product, C=Price).
    Hvis arket stadig er i gammelt "dato-kolonne"-format, returnér {}.
    """
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return {}

    header = values[0]
    if len(header) < 3:
        return {}

    if header[0].strip().lower() != "product" or header[2].strip().lower() != "price":
        return {}

    out: Dict[str, float] = {}
    for row in values[1:]:
        if len(row) < 3:
            continue
        name = (row[0] or "").strip()
        if not name:
            continue
        p = parse_float(row[2])
        if p is None:
            continue
        out[name] = float(p)
    return out


def build_daily_medians_from_raw(raw_ws, mode: str) -> Tuple[Dict[str, float], Dict[str, int]]:
    """
    mode = "overall"  -> daily min uanset lager
    mode = "in_stock" -> daily min kun Available=TRUE
    Median = median af daily minima (1 tal pr dag).
    hist_days = antal dage med data.
    """
    values = raw_ws.get_all_values()
    if not values or len(values) < 2:
        return {}, {}

    header = values[0]
    idx = {h.strip(): i for i, h in enumerate(header)}

    needed = {"Date", "Product", "Price", "Available"}
    if not needed.issubset(idx):
        return {}, {}

    daily_min: Dict[Tuple[str, str], float] = {}

    for row in values[1:]:
        try:
            date = (row[idx["Date"]] or "").strip()
            product = (row[idx["Product"]] or "").strip()
            price = parse_float(row[idx["Price"]] if idx["Price"] < len(row) else "")
            available = _bool_from_raw(row[idx["Available"]] if idx["Available"] < len(row) else "")
        except Exception:
            continue

        if not date or not product or price is None:
            continue

        if mode == "in_stock" and not available:
            continue

        key = (product, date)
        fp = float(price)
        if key not in daily_min or fp < daily_min[key]:
            daily_min[key] = fp

    by_product: Dict[str, List[float]] = {}
    for (product, _date), p in daily_min.items():
        by_product.setdefault(product, []).append(p)

    median_map: Dict[str, float] = {}
    hist_days_map: Dict[str, int] = {}
    for product, prices in by_product.items():
        median_map[product] = float(statistics.median(prices))
        hist_days_map[product] = len(prices)

    return median_map, hist_days_map


def _apply_snapshot_formatting(ws, delta_col_index_1based: int = 5):
    """
    - Freeze header
    - Bold header
    - Conditional formatting på Δ:
        grøn (<0), gul (=0), rød (>0)
    """
    try:
        sh = ws.spreadsheet
        sheet_id = ws._properties["sheetId"]

        meta = sh.fetch_sheet_metadata()
        conditional_rules = []
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            if props.get("sheetId") == sheet_id:
                conditional_rules = s.get("conditionalFormatRules", []) or []
                break

        requests = []

        # Freeze 1. række
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # Bold header
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        })

        # Slet gamle conditional rules (så vi ikke stapler nye på hver dag)
        for i in range(len(conditional_rules) - 1, -1, -1):
            requests.append({"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}})

        # Range: Δ-kolonnen (E) fra række 2 og ned
        start_col = delta_col_index_1based - 1
        rng = {
            "sheetId": sheet_id,
            "startRowIndex": 1,  # skip header
            "startColumnIndex": start_col,
            "endColumnIndex": start_col + 1,
        }

        def add_rule(cond_type: str, value: str, rgb: Tuple[float, float, float]):
            r, g, b = rgb
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [rng],
                        "booleanRule": {
                            "condition": {
                                "type": cond_type,
                                "values": [{"userEnteredValue": value}],
                            },
                            "format": {
                                "backgroundColor": {"red": r, "green": g, "blue": b}
                            },
                        },
                    },
                    "index": 0,
                }
            })

        # Grøn: fald
        add_rule("NUMBER_LESS", "0", (0.80, 0.94, 0.80))
        # Gul: uændret
        add_rule("NUMBER_EQ", "0", (1.00, 0.96, 0.70))
        # Rød: steget
        add_rule("NUMBER_GREATER", "0", (0.98, 0.80, 0.80))

        sh.batch_update({"requests": requests})
    except Exception:
        # Hvis formatting fejler, skal scriptet stadig virke
        pass


def update_snapshot_sheet(
    ws,
    chosen_today: Dict[str, Tuple[float, str, bool, str]],
    prev_price_map: Dict[str, float],
    median_map: Dict[str, float],
    hist_days_map: Dict[str, int],
    updated_ts: str,
    sheet_kind: str,
):
    rows = []
    push_candidates = []

    for name in sorted(chosen_today.keys()):
        offer = chosen_today[name]
        if offer is None:
            continue

        price, shop_label, available, url = offer
        price = float(price)

        prev = prev_price_map.get(name)
        delta = (price - prev) if prev is not None else ""
        delta_pct = ((price - prev) / prev) if (prev is not None and prev != 0) else ""

        median = float(median_map.get(name, price))
        hist_days = int(hist_days_map.get(name, 0))

        rows.append([
            name,
            f"{median:.6g}",
            price,
            (prev if prev is not None else ""),
            delta,
            delta_pct,
            make_shop_cell(shop_label, url),
            ("IN_STOCK" if available else "OUT_OF_STOCK"),
            updated_ts,
        ])

        if sheet_kind == "in_stock" and available:
            push_candidates.append((name, price, shop_label, median, hist_days))

    ws.clear()
    ws.resize(rows=max(1000, len(rows) + 50), cols=len(SNAPSHOT_HEADERS))
    ws.update("A1", [SNAPSHOT_HEADERS] + rows, value_input_option="USER_ENTERED")

    _apply_snapshot_formatting(ws, delta_col_index_1based=5)

    # Sortér alfabetisk på Product (kolonne A)
    try:
        ws.sort((1, "asc"), range=f"A2:I{len(rows) + 1}")
    except Exception:
        pass

    return {
        "updates_count": len(rows),
        "push_candidates": push_candidates,
    }


def main():
    print("STARTER SCRIPT")

    push_user_key = os.getenv("PUSH_USER_KEY", "").strip()
    push_app_token = os.getenv("PUSH_APP_TOKEN", "").strip()

    # behold din dag-streng (du bruger den allerede i RawOffers)
    today_str = datetime.datetime.now().strftime("%d-%m-%Y")

    sh = connect_google_sheet()
    print("CONNECTED TO GOOGLE SHEET OK")

    try:
        ws_summary = sh.worksheet(SHEET_SUMMARY_TITLE)
    except Exception:
        ws_summary = sh.sheet1

    try:
        ws_instock = sh.worksheet(SHEET_IN_STOCK_TITLE)
    except Exception:
        ws_instock = sh.add_worksheet(title=SHEET_IN_STOCK_TITLE, rows=5000, cols=20)

    try:
        ws_raw = sh.worksheet(SHEET_RAW_TITLE)
    except Exception:
        ws_raw = sh.add_worksheet(title=SHEET_RAW_TITLE, rows=5000, cols=10)

    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    offers_by_group: Dict[str, list] = {}
    group_name_map: Dict[str, str] = {}

    for shop_label, shop_module in shops:
        try:
            products = shop_module.get_products()
            print(f"{shop_label}: hentede {len(products)} produkter")
        except Exception as e:
            print(f"Fejl i shop {shop_label}: {e}")
            continue

        for p in products:
            raw_name = (p.get("name") or "").strip()
            if not raw_name:
                continue

            price = parse_float(p.get("price"))
            if price is None:
                continue

            available = bool(p.get("available", True))
            real_shop = (p.get("shop_source") or shop_label)
            url = (p.get("url") or "").strip()

            group_key, canonical_name = build_group_key_and_name(
                raw_name,
                extra_text=p.get("grouping_text"),
                series_hint=p.get("series_hint"),
            )

            group_name_map[group_key] = canonical_name
            offers_by_group.setdefault(group_key, []).append((float(price), real_shop, available, url))

    print("TOTAL grupper fundet:", len(offers_by_group))

    # Raw history (append)
    ensure_raw_headers(ws_raw)
    append_raw_offers(ws_raw, today_str, offers_by_group, group_name_map)
    print("RAW OFFERS appended")

    # Vælg billigste pr gruppe
    chosen_summary: Dict[str, Tuple[float, str, bool, str]] = {}
    chosen_instock: Dict[str, Tuple[float, str, bool, str]] = {}

    for gkey, offers in offers_by_group.items():
        canonical_name = group_name_map.get(gkey, gkey)

        chosen_summary[canonical_name] = choose_cheapest_overall(offers)

        best_instock = choose_cheapest_in_stock(offers)
        if best_instock is not None:
            chosen_instock[canonical_name] = best_instock

    # Medianer fra RawOffers (daily minima)
    median_overall, hist_days_overall = build_daily_medians_from_raw(ws_raw, mode="overall")
    median_instock, hist_days_instock = build_daily_medians_from_raw(ws_raw, mode="in_stock")

    # Pris i går fra snapshot-ark (nyt format)
    prev_summary = get_prev_price_map(ws_summary)
    prev_instock = get_prev_price_map(ws_instock)

    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    info_summary = update_snapshot_sheet(
        ws_summary,
        chosen_summary,
        prev_summary,
        median_overall,
        hist_days_overall,
        now_ts,
        sheet_kind="overall",
    )
    print(f"SUMMARY updated rows: {info_summary['updates_count']}")

    info_instock = update_snapshot_sheet(
        ws_instock,
        chosen_instock,
        prev_instock,
        median_instock,
        hist_days_instock,
        now_ts,
        sheet_kind="in_stock",
    )
    print(f"IN_STOCK updated rows: {info_instock['updates_count']}")

    # Push (kun in-stock ark)
    push_messages = []
    for (name, price, shop, median, hist_days) in info_instock["push_candidates"]:
        if hist_days >= MIN_HISTORY_FOR_PUSH:
            threshold = median * (1 - DISCOUNT_PCT)
            if price <= threshold:
                push_messages.append(
                    f"Tilbud ({DISCOUNT_PCT*100:.0f}%): {name} → {price:g} kr ({shop}) | median: {median:.0f}"
                )

    if push_messages:
        msg = "\n".join(push_messages[:MAX_PUSH_LINES])
        if len(push_messages) > MAX_PUSH_LINES:
            msg += f"\n(+{len(push_messages) - MAX_PUSH_LINES} flere tilbud)"
        send_push(msg, push_user_key, push_app_token)
        print("PUSH SENT:", len(push_messages))
    else:
        print("NO PUSH OFFERS")


if __name__ == "__main__":
    main()