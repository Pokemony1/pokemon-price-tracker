import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def connect_google_sheet():
    """
    Returnerer hele Spreadsheet-objektet (ikke kun Sheet1),
    så vi kan bruge både Sheet1 (Summary), Billigste in stock og RawOffers.
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("Mangler GOOGLE_SERVICE_ACCOUNT_JSON i GitHub Secrets")

    sheet_id = os.getenv("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("Mangler SHEET_ID i GitHub Secrets")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(sa_json), scope)
    client = gspread.authorize(creds)

    sh = client.open_by_key(sheet_id)
    return sh
