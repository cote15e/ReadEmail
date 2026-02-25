"""
Модуль для чтения PDF-файлов Medium с Google Диска.

Функции:
- Авторизация в Google Drive (OAuth2, только чтение).
- Поиск директории по имени.
- Чтение PDF-файлов из этой директории.
- Извлечение текста из PDF и преобразование в формат статей.

Требуемые переменные окружения (.env):
- GDRIVE_FOLDER_NAME  — имя папки на Google Диске, из которой брать PDF.
- GOOGLE_DRIVE_CREDENTIALS_FILE — путь к client_secret / credentials JSON (по умолчанию: credentials.json).
- GOOGLE_DRIVE_TOKEN_FILE       — путь к token.json для сохранения токена (по умолчанию: token.json).
"""

import io
import os
import re
from typing import List, Dict, Optional, Tuple

from dotenv import load_dotenv

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
except ImportError as e:  # pragma: no cover - зависимость может быть не установлена
    build = None  # type: ignore
    MediaIoBaseDownload = None  # type: ignore
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    Request = None  # type: ignore

try:
    import PyPDF2
except ImportError:  # pragma: no cover
    PyPDF2 = None  # type: ignore


SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _ensure_deps() -> None:
    """Проверяет наличие обязательных зависимостей для работы с Google Drive и PDF."""
    missing = []
    if build is None:
        missing.append("google-api-python-client, google-auth-httplib2, google-auth-oauthlib")
    if PyPDF2 is None:
        missing.append("PyPDF2")
    if missing:
        raise ImportError(
            "Missing required dependencies: "
            + "; ".join(missing)
            + ". Install them, for example:\n"
            "pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib PyPDF2"
        )


def _get_drive_service(
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
):
    """
    Возвращает авторизованный клиент Google Drive API.

    credentials_path: путь к client_secret / credentials JSON.
    token_path: путь к token.json (создаётся автоматически при первом запуске).
    """
    _ensure_deps()

    credentials_path = credentials_path or os.getenv("GOOGLE_DRIVE_CREDENTIALS_FILE", "credentials.json")
    token_path = token_path or os.getenv("GOOGLE_DRIVE_TOKEN_FILE", "token.json")

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Google Drive credentials file not found: {credentials_path}. "
            "Скачайте credentials JSON из Google Cloud Console и укажите путь в GOOGLE_DRIVE_CREDENTIALS_FILE."
        )

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)  # type: ignore[arg-type]

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore[call-arg]
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)  # type: ignore[arg-type]
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    service = build("drive", "v3", credentials=creds)  # type: ignore[arg-type]
    return service


def _find_folder_id(service, folder_name: str) -> str:
    """Находит ID папки по имени (берётся первая найденная)."""
    query = (
        f"name = '{folder_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "trashed = false"
    )
    resp = service.files().list(q=query, spaces="drive", fields="files(id, name)", pageSize=10).execute()
    files = resp.get("files", [])
    if not files:
        raise ValueError(f"Google Drive folder not found: {folder_name}")
    return files[0]["id"]


def _list_pdfs_in_folder(service, folder_id: str) -> List[Dict[str, str]]:
    """Возвращает список PDF-файлов (id, name) внутри указанной папки."""
    query = (
        f"'{folder_id}' in parents and "
        "mimeType = 'application/pdf' and "
        "trashed = false"
    )
    results: List[Dict[str, str]] = []
    page_token: Optional[str] = None

    while True:
        resp = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            )
            .execute()
        )
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def _download_pdf_bytes(service, file_id: str) -> bytes:
    """Скачивает файл PDF по file_id и возвращает содержимое в байтах."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)  # type: ignore[arg-type]

    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    return fh.read()


def _extract_text_from_pdf(data: bytes) -> Tuple[str, str]:
    """
    Извлекает текст из PDF.

    Возвращает:
    - full_text: текст всего документа;
    - first_page_text: текст только первой страницы.
    """
    if PyPDF2 is None:  # pragma: no cover
        raise ImportError("PyPDF2 is not installed")

    reader = PyPDF2.PdfReader(io.BytesIO(data))
    full_text_parts: List[str] = []
    first_page_text = ""

    for idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if idx == 0:
            first_page_text = text
        full_text_parts.append(text)

    full_text = "\n".join(full_text_parts)
    return full_text, first_page_text


# Строки, которые являются служебными элементами Medium PDF, а не заголовком статьи
_SKIP_TITLE_PATTERNS = [
    "member-only story",
    "open in app",
    "sign up",
    "sign in",
    "get started",
    "listen",
    "share",
    "follow",
    "published in",
    "written by",
    "responses",
    "more from",
    "medium.com",
    "https://",
    "http://",
]


def _is_url(text: str) -> bool:
    """Проверяет, является ли строка URL."""
    return bool(re.match(r"https?://", text, re.IGNORECASE))


def _is_skip_line(text: str) -> bool:
    """Проверяет, является ли строка служебной (не заголовком)."""
    t = text.lower().strip()
    if len(t) < 5:
        return True
    for pattern in _SKIP_TITLE_PATTERNS:
        if t.startswith(pattern) or t == pattern:
            return True
    return False


def _extract_link_from_text(text: str) -> str:
    """
    Ищет первый URL (https://...) во всём тексте.
    Приоритет: ссылки с medium.com, затем любая https:// ссылка.
    """
    # Ищем все URL в тексте
    urls = re.findall(r"https?://[^\s\)\]\}>\"']+", text)
    if not urls:
        return ""

    # Приоритет: medium.com ссылки
    for url in urls:
        if "medium.com" in url.lower():
            return url.rstrip(".,;:!?")

    # Иначе первый найденный URL
    return urls[0].rstrip(".,;:!?")


def _extract_title_from_lines(lines: List[str]) -> str:
    """
    Ищет настоящий заголовок статьи среди строк первой страницы PDF.
    Пропускает URL, служебные строки Medium и короткие фрагменты.
    Заголовок — первая значимая строка длиной >= 10 символов.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_url(stripped):
            continue
        if _is_skip_line(stripped):
            continue
        if len(stripped) >= 10:
            return stripped
    return ""


def _parse_article_from_pdf_text(
    full_text: str,
    first_page_text: str,
    fallback_title: str,
) -> Dict[str, str]:
    """
    Строит структуру статьи из текста PDF (Medium, сохранённый через Ctrl+P).

    - Ссылка: первый URL (https://...) найденный на первой странице,
      приоритет у ссылок с medium.com.
    - Заголовок: первая значимая строка первой страницы (не URL, не служебная).
    - Text: весь извлечённый текст.
    """
    first_lines = [line.strip() for line in first_page_text.splitlines() if line.strip()]

    link = _extract_link_from_text(first_page_text)
    title = _extract_title_from_lines(first_lines) or fallback_title

    text = full_text.strip()
    return {
        "Title": title,
        "Link": link,
        "Text": text,
    }


def fetch_medium_pdfs_from_gdrive(
    folder_name: Optional[str] = None,
    debug: bool = False,
) -> List[Dict[str, str]]:
    """
    Читает PDF-файлы из директории Google Drive и возвращает статьи
    в формате [{"Title", "Link", "Text"}, ...], совместимом с остальной логикой.

    folder_name: имя папки на Google Диске; если не указано, берётся из GDRIVE_FOLDER_NAME.
    """
    load_dotenv()

    folder_name = (folder_name or os.getenv("GDRIVE_FOLDER_NAME") or "").strip()
    if not folder_name:
        raise ValueError("GDRIVE_FOLDER_NAME is not set in environment or argument")

    if debug:
        print(f"[DEBUG] Using Google Drive folder: {folder_name}")

    service = _get_drive_service()
    folder_id = _find_folder_id(service, folder_name)

    if debug:
        print(f"[DEBUG] Found folder ID: {folder_id}")

    pdf_files = _list_pdfs_in_folder(service, folder_id)
    if debug:
        print(f"[DEBUG] Found {len(pdf_files)} PDF file(s) in folder")

    articles: List[Dict[str, str]] = []

    for idx, f in enumerate(pdf_files, start=1):
        file_id = f["id"]
        name = f.get("name") or f"file_{idx}.pdf"

        if debug:
            print(f"[DEBUG] Downloading PDF {idx}/{len(pdf_files)}: {name} ({file_id})")

        data = _download_pdf_bytes(service, file_id)
        full_text, first_page_text = _extract_text_from_pdf(data)

        article = _parse_article_from_pdf_text(
            full_text=full_text,
            first_page_text=first_page_text,
            fallback_title=name,
        )
        articles.append(article)

        if debug:
            print(
                f"[DEBUG] Parsed article from '{name}': "
                f"Title='{article['Title'][:60]}', Link='{article['Link']}'"
            )

    return articles

