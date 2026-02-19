import os
import datetime
import numpy as np
import importlib
import pkgutil
import gspread

from pokemon_price_tracker.google_sheet import connect_google_sheet
from pokemon_price_tracker.push_notification import send_push
from pokemon_price_tracker.product_grouping import build_group_key_and_name


SHEET_SUMMARY_TITLE = "Sheet1"
SHEET_IN_STOCK_TITLE = "Billigste in stock"
SHEET_RAW_TITLE = "RawOffers"

MIN_HISTORY_FOR_PUSH = 5
DISCOUNT_PCT = 0.15
MAX_PUSH_LINES = 20


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


def parse_float(x):
    try:
        return float(x)
    except Exception:
        return None


def ensure_headers(ws, today_str):
    header = ws.row_values(1)

    if len(header) < 1 or header[0] != "Product":
        ws.update_cell(1, 1, "Product")
    if len(header) < 2 or header[1] != "Median":
        ws.update_cell(1, 2, "Median")

    header = ws.row_values(1)

    price_header = f"{today_str} Price"
    shop_header = f"{today_str} Shop"
    stock_header = f"{today_str} Stock"

    if price_header in header:
        price_col = header.index(price_header) + 1
        shop_col = price_col + 1
        stock_col = price_col + 2

        if len(header) < shop_col or header[shop_col - 1] != shop_header:
            ws.update_cell(1, shop_col, shop_header)
        if len(header) < stock_col or header[stock_col - 1] != stock_header:
            ws.update_cell(1, stock_col, stock_header)

        return price_col, shop_col, stock_col

    price_col = len(header) + 1
    shop_col = price_col + 1
    stock_col = price_col + 2

    ws.update_cell(1, price_col, price_header)
    ws.update_cell(1, shop_col, shop_header)
    ws.update_cell(1, stock_col, stock_header)

    return price_col, shop_col, stock_col


def ensure_raw_headers(raw_ws):
    wanted = ["Timestamp", "Date", "Product", "Price", "Shop", "Available"]
    header = raw_ws.row_values(1)
    if header != wanted:
        raw_ws.update("A1:F1", [wanted])


def append_raw_offers(raw_ws, today_str, offers_by_group, group_name_map):
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for gkey, offers in offers_by_group.items():
        canonical_name = group_name_map.get(gkey, gkey)
        for price, shop, available in offers:
            rows.append([now_ts, today_str, canonical_name, str(price), shop, "TRUE" if available else "FALSE"])

    if rows:
        raw_ws.append_rows(rows, value_input_option="USER_ENTERED")


def get_product_row_map(ws):
    col = ws.col_values(1)
    mapping = {}
    for idx, name in enumerate(col[1:], start=2):
        if name:
            mapping[name] = idx
    return mapping


def choose_cheapest_overall(offers):
    avail_offers = [o for o in offers if o[2] is True]
    use = avail_offers if avail_offers else offers
    return min(use, key=lambda t: t[0])


def choose_cheapest_in_stock_else_fallback(offers):
    sorted_offers = sorted(offers, key=lambda t: t[0])
    for o in sorted_offers:
        if o[2] is True:
            return o
    return sorted_offers[0]


def update_price_sheet(ws, today_str, chosen_today, do_sort_alpha=True):
    today_price_col, today_shop_col, today_stock_col = ensure_headers(ws, today_str)

    row_map = get_product_row_map(ws)
    all_names = list(chosen_today.keys())

    new_names = [n for n in all_names if n not in row_map]
    if new_names:
        ws.append_rows([[n] for n in new_names], value_input_option="USER_ENTERED")
        row_map = get_product_row_map(ws)

    all_values = ws.get_all_values()
    max_row = max(row_map.values()) if row_map else 1
    max_col = max(today_stock_col, 2)

    while len(all_values) < max_row:
        all_values.append([])
    for r_i in range(len(all_values)):
        if len(all_values[r_i]) < max_col:
            all_values[r_i].extend([""] * (max_col - len(all_values[r_i])))

    header = all_values[0] if all_values else []

    price_cols = []
    for c in range(3, len(header) + 1, 3):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

    updates_count = 0
    push_candidates = []

    for name, (price, shop_label, available) in chosen_today.items():
        r = row_map.get(name)
        if not r:
            continue

        all_values[r - 1][today_price_col - 1] = str(price)
        all_values[r - 1][today_shop_col - 1] = str(shop_label)
        all_values[r - 1][today_stock_col - 1] = "IN_STOCK" if available else "OUT_OF_STOCK"

        hist_prices = []
        for c in price_cols:
            if c == today_price_col:
                continue
            v = all_values[r - 1][c - 1] if (c - 1) < len(all_values[r - 1]) else ""
            try:
                fv = float(v) if v != "" else None
            except Exception:
                fv = None
            if fv is not None:
                hist_prices.append(fv)

        prices_for_median = hist_prices + [float(price)]
        median_price = float(np.median(prices_for_median)) if prices_for_median else float(price)

        all_values[r - 1][1] = f"{median_price:.6g}"
        updates_count += 1
        push_candidates.append((name, float(price), shop_label, float(median_price), len(hist_prices)))

    range_name = f"A1:{gspread.utils.rowcol_to_a1(max_row, max_col)}"
    ws.update(values=all_values[:max_row], range_name=range_name)

    if do_sort_alpha:
        try:
            ws.sort((1, "asc"), range=f"A2:{gspread.utils.rowcol_to_a1(max_row, max_col)}")
        except Exception:
            pass

    return {
        "max_row": max_row,
        "max_col": max_col,
        "updates_count": updates_count,
        "push_candidates": push_candidates,
    }


def main():
    print("STARTER SCRIPT")

    push_user_key = os.getenv("PUSH_USER_KEY", "")
    push_app_token = os.getenv("PUSH_APP_TOKEN", "")
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
        ws_instock = sh.add_worksheet(title=SHEET_IN_STOCK_TITLE, rows=5000, cols=50)

    try:
        ws_raw = sh.worksheet(SHEET_RAW_TITLE)
    except Exception:
        ws_raw = sh.add_worksheet(title=SHEET_RAW_TITLE, rows=5000, cols=10)

    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    offers_by_group = {}
    group_name_map = {}

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

            # NYT: brug hints + full_text (grouping_text)
            group_key, canonical_name = build_group_key_and_name(
                raw_name,
                extra_text=p.get("grouping_text"),
                series_hint=p.get("series_hint"),
            )

            group_name_map[group_key] = canonical_name
            offers_by_group.setdefault(group_key, []).append((price, real_shop, available))

    print("TOTAL grupper fundet:", len(offers_by_group))

    ensure_raw_headers(ws_raw)
    append_raw_offers(ws_raw, today_str, offers_by_group, group_name_map)
    print("RAW OFFERS appended")

    chosen_summary = {}
    chosen_instock = {}

    for gkey, offers in offers_by_group.items():
        canonical_name = group_name_map.get(gkey, gkey)
        chosen_summary[canonical_name] = choose_cheapest_overall(offers)
        chosen_instock[canonical_name] = choose_cheapest_in_stock_else_fallback(offers)

    info_summary = update_price_sheet(ws_summary, today_str, chosen_summary, do_sort_alpha=True)
    print(f"SUMMARY updated rows: {info_summary['updates_count']}")

    info_instock = update_price_sheet(ws_instock, today_str, chosen_instock, do_sort_alpha=True)
    print(f"IN_STOCK updated rows: {info_instock['updates_count']}")

    push_messages = []
    for (name, price, shop, median, hist_count) in info_instock["push_candidates"]:
        if hist_count >= MIN_HISTORY_FOR_PUSH:
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
