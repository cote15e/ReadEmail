"""
Модуль для записи результатов анализа статей в Google Sheets.

Таблица:
- Имя: Medium_Digest (переменная G_SHEETS_SPREADSHEET_NAME)
- Или прямой ID: G_SHEETS_SPREADSHEET_ID (приоритетнее имени)
- Столбцы: Date, Title, Summaries, Tag, Link

Использует те же credentials, что и Google Drive:
    - GOOGLE_DRIVE_CREDENTIALS_FILE (credentials.json)
    - GOOGLE_SHEETS_TOKEN_FILE (по умолчанию: token_sheets.json)
"""

import os
from datetime import date
from typing import Optional, List

from dotenv import load_dotenv

try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
except ImportError:
    build = None  # type: ignore
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    Request = None  # type: ignore


# Широкий scope: полный доступ к Sheets + полный доступ к Drive (чтение/поиск файлов)
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _ensure_sheets_deps() -> None:
    if build is None or Credentials is None or InstalledAppFlow is None or Request is None:
        raise ImportError(
            "Missing Google Sheets dependencies. Install:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )


def _get_sheets_service(
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
):
    """Возвращает авторизованный клиент Google Sheets API и Drive API."""
    _ensure_sheets_deps()
    load_dotenv()

    credentials_path = credentials_path or os.getenv("GOOGLE_DRIVE_CREDENTIALS_FILE", "credentials.json")
    token_path = token_path or os.getenv("GOOGLE_SHEETS_TOKEN_FILE", "token_sheets.json")

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Google credentials file not found: {credentials_path}. "
            "Укажите путь в GOOGLE_DRIVE_CREDENTIALS_FILE."
        )

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SHEETS_SCOPES)  # type: ignore[arg-type]

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore[call-arg]
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SHEETS_SCOPES)  # type: ignore[arg-type]
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    service = build("sheets", "v4", credentials=creds)  # type: ignore[arg-type]
    drive_service = build("drive", "v3", credentials=creds)  # type: ignore[arg-type]
    return service, drive_service


def _find_spreadsheet_by_name(drive_service, spreadsheet_name: str) -> Optional[str]:
    """Ищет Google Sheets по имени через Drive API. Возвращает ID или None."""
    query = (
        f"name = '{spreadsheet_name}' and "
        "mimeType = 'application/vnd.google-apps.spreadsheet' and "
        "trashed = false"
    )
    resp = drive_service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=5).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    return None


def _create_spreadsheet(service, spreadsheet_name: str) -> str:
    """Создаёт новую Google Sheets-таблицу и возвращает spreadsheetId."""
    spreadsheet_body = {
        "properties": {"title": spreadsheet_name},
        "sheets": [
            {
                "properties": {
                    "title": "Sheet1",
                }
            }
        ],
    }
    result = service.spreadsheets().create(body=spreadsheet_body, fields="spreadsheetId").execute()
    spreadsheet_id = result["spreadsheetId"]

    # Добавляем заголовки
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Sheet1!A1:E1",
        valueInputOption="RAW",
        body={"values": [["Date", "Title", "Summaries", "Tag", "Link"]]},
    ).execute()

    return spreadsheet_id


def _resolve_spreadsheet_id(service, drive_service) -> str:
    """
    Определяет ID таблицы.
    Приоритеты:
    1. G_SHEETS_SPREADSHEET_ID — если указан напрямую, используем без поиска.
    2. G_SHEETS_SPREADSHEET_NAME — ищем по имени через Drive API.
    3. Создаём новую таблицу Medium_Digest.
    """
    # Приоритет 1: прямой ID
    direct_id = (os.getenv("G_SHEETS_SPREADSHEET_ID") or "").strip()
    if direct_id:
        return direct_id

    # Приоритет 2: поиск по имени
    spreadsheet_name = (os.getenv("G_SHEETS_SPREADSHEET_NAME") or "Medium_Digest").strip()
    found_id = _find_spreadsheet_by_name(drive_service, spreadsheet_name)
    if found_id:
        return found_id

    # Приоритет 3: создаём новую
    return _create_spreadsheet(service, spreadsheet_name)


def append_summary_row(
    title: str,
    summary: str,
    link: str,
) -> None:
    """
    Добавляет строку в таблицу: Date, Title, Summaries, Tag, Link.
    Date — текущая дата в формате дд-мм-гггг; Tag оставляется пустым.
    """
    service, drive_service = _get_sheets_service()
    spreadsheet_id = _resolve_spreadsheet_id(service, drive_service)

    # Определяем фактическое имя первого листа
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title))").execute()
    sheets = meta.get("sheets", [])
    if not sheets:
        raise RuntimeError(f"No sheets found in spreadsheet {spreadsheet_id}")
    sheet_title = sheets[0]["properties"]["title"]

    date_str = date.today().strftime("%d-%m-%Y")
    values: List[List[str]] = [[date_str, title, summary, "", link]]
    body = {"values": values}

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_title}!A:E",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()
