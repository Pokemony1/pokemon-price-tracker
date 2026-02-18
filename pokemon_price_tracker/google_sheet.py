import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def connect_google_sheet(sheet_name: str):
    """
    Connect to Google Sheets using JSON credentials stored in env var:
    GOOGLE_SERVICE_ACCOUNT_JSON
    """
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]

    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError("Mangler GOOGLE_SERVICE_ACCOUNT_JSON i GitHub Secrets (Actions).")

    sa_info = json.loads(sa_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(sa_info, scope)
    client = gspread.authorize(creds)

    # Åbn eksisterende sheet (du opretter det manuelt)
    sh = client.open(sheet_name)
    ws = sh.sheet1
    return ws
