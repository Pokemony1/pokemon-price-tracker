import os
import datetime
import numpy as np
import importlib
import pkgutil
import gspread

from pokemon_price_tracker.google_sheet import connect_google_sheet
from pokemon_price_tracker.push_notification import send_push


# ---------- KONFIG ----------
RAW_SHEET_TITLE = "RawOffers"   # fanen med alle fund pr. shop pr. dag
SUMMARY_SHEET_TITLE = "Sheet1"  # fanen med billigste pr. dag + median

# Tilbudslogik (valgfrit)
MIN_HISTORY_FOR_PUSH = 5        # kræv mindst 5 historiske datapunkter før push
DISCOUNT_PCT = 0.15             # 15% under median => push
# ---------------------------


def load_shops():
    """
    Loader alle shops fra pokemon_price_tracker/Shops/ der har funktionen get_products().
    Returnerer liste af tuples: (shop_label, module)
    """
    shops = []
    package_path = os.path.join(os.path.dirname(__file__), "Shops")
    package_name = "pokemon_price_tracker.Shops"

    for _, module_name, _ in pkgutil.iter_modules([package_path]):
        module = importlib.import_module(f"{package_name}.{module_name}")
        if hasattr(module, "get_products"):
            shop_label = getattr(module, "SHOP_NAME", module_name)
            shops.append((shop_label, module))
    return shops


def ensure_summary_headers(ws, today_str):
    """
    Summary headers:
      A1 = Product
      B1 = Median
      For dagens dato 3 kolonner:
        "<date> Price"
        "<date> Shop"
        "<date> Stock"
    Returnerer (today_price_col, today_shop_col, today_stock_col)
    """
    header = ws.row_values(1)

    # Sørg for Product og Median
    if len(header) < 1 or header[0] != "Product":
        ws.update_cell(1, 1, "Product")
    if len(header) < 2 or header[1] != "Median":
        ws.update_cell(1, 2, "Median")

    header = ws.row_values(1)

    price_header = f"{today_str} Price"
    shop_header = f"{today_str} Shop"
    stock_header = f"{today_str} Stock"

    # Hvis dagens price header allerede findes
    if price_header in header:
        price_col = header.index(price_header) + 1
        shop_col = price_col + 1
        stock_col = price_col + 2

        # Fix hvis shop/stock headers mangler
        if len(header) < shop_col or header[shop_col - 1] != shop_header:
            ws.update_cell(1, shop_col, shop_header)
        if len(header) < stock_col or header[stock_col - 1] != stock_header:
            ws.update_cell(1, stock_col, stock_header)

        return price_col, shop_col, stock_col

    # Ellers tilføj 3 nye kolonner i slutningen
    price_col = len(header) + 1
    shop_col = price_col + 1
    stock_col = price_col + 2

    ws.update_cell(1, price_col, price_header)
    ws.update_cell(1, shop_col, shop_header)
    ws.update_cell(1, stock_col, stock_header)

    return price_col, shop_col, stock_col


def get_product_row_map(ws):
    """
    Læser kolonne A og returnerer dict: product_name -> row_index
    """
    col = ws.col_values(1)
    mapping = {}
    for idx, name in enumerate(col[1:], start=2):  # skip header
        if name:
            mapping[name] = idx
    return mapping


def parse_float(x):
    try:
        return float(x)
    except Exception:
        return None


def ensure_raw_headers(raw_ws):
    wanted = ["Timestamp", "Date", "Product", "Price", "Shop", "Available"]
    header = raw_ws.row_values(1)
    if header != wanted:
        raw_ws.update("A1:F1", [wanted])


def append_raw_offers(raw_ws, today_str, offers_by_product):
    """
    offers_by_product: dict[name] -> list of (price, shop_label, available)
    Skriver ALLE fund (ikke kun billigste) i RawOffers med append_rows (1 API-call).
    """
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for name, offers in offers_by_product.items():
        for price, shop, available in offers:
            rows.append([now_ts, today_str, name, str(price), shop, "TRUE" if available else "FALSE"])

    if rows:
        raw_ws.append_rows(rows, value_input_option="USER_ENTERED")


def main():
    print("STARTER SCRIPT")

    # GitHub Secrets / env
    push_user_key = os.getenv("PUSH_USER_KEY", "")
    push_app_token = os.getenv("PUSH_APP_TOKEN", "")

    # Dato
    today_str = datetime.datetime.now().strftime("%d-%m-%Y")

    # Connect til spreadsheet
    sh = connect_google_sheet()
    print("CONNECTED TO GOOGLE SHEET OK")

    # Åbn faner
    summary_ws = sh.worksheet(SUMMARY_SHEET_TITLE)
    try:
        raw_ws = sh.worksheet(RAW_SHEET_TITLE)
    except Exception:
        # Hvis den ikke findes, opret den
        raw_ws = sh.add_worksheet(title=RAW_SHEET_TITLE, rows=5000, cols=10)

    # (Valgfrit) debug-bevis i arket - slå fra ved at sætte env DEBUG_HELLO=0
    if os.getenv("DEBUG_HELLO", "1") == "1":
        summary_ws.update_cell(1, 1, "Product")  # sørg for ikke at ødelægge header
        # vi skriver ikke HELLO længere, så du ikke mister rigtige headers

    # Summary headers for i dag
    today_price_col, today_shop_col, today_stock_col = ensure_summary_headers(summary_ws, today_str)
    print("SUMMARY HEADERS OK:", today_price_col, today_shop_col, today_stock_col)

    # Load shops
    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    # Saml alle offers fra shops:
    # all_offers[name] = list of (price, shop_label, available)
    all_offers = {}

    for shop_label, shop_module in shops:
        try:
            products = shop_module.get_products()
            print(f"{shop_label}: hentede {len(products)} produkter")
        except Exception as e:
            print(f"Fejl i shop {shop_label}: {e}")
            continue

        for p in products:
            name = (p.get("name") or "").strip()
            if not name:
                continue

            price = parse_float(p.get("price"))
            if price is None:
                continue

            available = bool(p.get("available", True))
            all_offers.setdefault(name, []).append((price, shop_label, available))

    print("TOTAL unikke produkter fundet:", len(all_offers))

    # ---- RAW OFFERS: skriv alt (inkl. lagerstatus) ----
    ensure_raw_headers(raw_ws)
    append_raw_offers(raw_ws, today_str, all_offers)
    print("RAW OFFERS appended")

    # Vælg billigste pr. produkt (prioritér available=True)
    cheapest_today = {}
    for name, offers in all_offers.items():
        avail_offers = [o for o in offers if o[2] is True]
        use = avail_offers if avail_offers else offers
        cheapest = min(use, key=lambda t: t[0])  # (price, shop_label, available)
        cheapest_today[name] = cheapest

    # Find eksisterende rækker i summary
    row_map = get_product_row_map(summary_ws)

    # Tilføj nye produkter i bunden (append_rows = færre writes)
    new_names = [name for name in cheapest_today.keys() if name not in row_map]
    if new_names:
        summary_ws.append_rows([[n] for n in new_names], value_input_option="USER_ENTERED")
        row_map = get_product_row_map(summary_ws)
        print("Tilføjede nye produkter:", len(new_names))

    # Batch: hent hele arket som matrix, opdater lokalt, skriv tilbage i ét kald
    all_values = summary_ws.get_all_values()

    max_row = max(row_map.values()) if row_map else 1
    max_col = max(today_stock_col, 2)

    # Sørg for nok rækker/kolonner i matrixen
    while len(all_values) < max_row:
        all_values.append([])
    for r_i in range(len(all_values)):
        if len(all_values[r_i]) < max_col:
            all_values[r_i].extend([""] * (max_col - len(all_values[r_i])))

    header = all_values[0] if all_values else []

    # Price-kolonner ligger nu i mønster: col 3,6,9,... (step 3)
    price_cols = []
    for c in range(3, len(header) + 1, 3):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

    push_messages = []
    updates_count = 0

    for name, (price, shop_label, available) in cheapest_today.items():
        r = row_map.get(name)
        if not r:
            continue

        # Skriv dagens data (billigste)
        all_values[r - 1][today_price_col - 1] = str(price)
        all_values[r - 1][today_shop_col - 1] = str(shop_label)
        all_values[r - 1][today_stock_col - 1] = "IN_STOCK" if available else "OUT_OF_STOCK"

        # Historiske priser (uden dagens)
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

        # Skriv median i kolonne B
        all_values[r - 1][1] = f"{median_price:.6g}"
        updates_count += 1

        # Push-logik: kræv historik + procent under median
        if len(hist_prices) >= MIN_HISTORY_FOR_PUSH:
            threshold = median_price * (1 - DISCOUNT_PCT)
            if float(price) <= threshold:
                push_messages.append(
                    f"Tilbud ({DISCOUNT_PCT*100:.0f}%): {name} → {price} kr ({shop_label}) | median: {median_price:.0f}"
                )

    # Skriv hele området tilbage i ÉT kald
    range_name = f"A1:{gspread.utils.rowcol_to_a1(max_row, max_col)}"
    summary_ws.update(values=all_values[:max_row], range_name=range_name)
    print(f"SUMMARY updated rows: {updates_count} | range: {range_name}")

    # Send push (samlet)
    if push_messages:
        msg = "\n".join(push_messages[:20])  # max 20 linjer, så beskeden ikke bliver for lang
        if len(push_messages) > 20:
            msg += f"\n(+{len(push_messages) - 20} flere tilbud)"
        send_push(msg, push_user_key, push_app_token)
        print("PUSH SENT:", len(push_messages))
    else:
        print("NO PUSH OFFERS")


if __name__ == "__main__":
    main()
