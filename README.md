# Gmail Medium Digest Reader

This simple CLI tool connects to your Gmail account, finds Medium digest emails (by default **"Medium Weekly Digest"**), and extracts the article titles, links and full text into a JSON format.

## Requirements

- Python >= 3.10
- A Gmail account with **2-Step Verification** enabled.
- An **App Password** for the script (do not use your regular password).

## Installation

1.  Clone this repository or download the files.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  Create a `.env` file in the same directory as `main.py`.
2.  Choose data source and add credentials:

    - **Option A — Gmail Medium Digest (как раньше)**:

      ```env
      EMAIL_USER=your_email@gmail.com
      EMAIL_PASS=your_app_password
      # Тема рассылки (подстрока). Несколько значений через запятую.
      EMAIL_DIGEST_SUBJECT=Medium Weekly Digest
      ```

      > **Note:** To generate an App Password, go to your Google Account > Security > 2-Step Verification > App passwords.

    - **Option B — PDF на Google Drive** (тексты статей Medium, сохранённые через Ctrl+P в PDF):

      ```env
      # Имя папки на Google Диске, откуда брать PDF
      GDRIVE_FOLDER_NAME=MediumArticles

      # Файлы для OAuth-авторизации Google Drive
      GOOGLE_DRIVE_CREDENTIALS_FILE=credentials.json
      GOOGLE_DRIVE_TOKEN_FILE=token.json
      ```

3.  (Optional) Add AI & Google Sheets configuration for analysis:

    ```env
    # Провайдер: openai | openrouter | routerai
    AI_PROVIDER=openai
    SEND_TO_GPT=false
    AI_MODEL=gpt-4o
    OPENAI_API_KEY=sk-...
    # OPENROUTER_API_KEY=sk-or-...
    # ROUTERAI_API_KEY=sk-...

    # Google Sheets (для сохранения результатов)
    G_SHEETS_SPREADSHEET_NAME=Medium_Digest
    GOOGLE_SHEETS_TOKEN_FILE=token_sheets.json
    ```

## Usage

Run the script:

```bash
python main.py
```

The output will be a JSON list of articles found in your recent Medium digest emails.

```json
[
    {
        "Title": "Заголовок статьи",
        "Link": "https://medium.com/...",
        "Text": "Текст статьи"
    },
    ...
]
```

### Анализ статей через AI и сохранение в Google Sheets

- Модуль `openai_gpts.py` отправляет **одну статью за раз** (только `Title` и `Text`) в AI и получает краткую аннотацию на русском.
- Провайдер задаётся через `AI_PROVIDER`:
  - `openai` — api.openai.com
  - `openrouter` — openrouter.ai
  - `routerai` — routerai.ru
- Ключ: `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ROUTERAI_API_KEY` (или общий `AI_API_KEY`).
- Модель: `AI_MODEL` (для openrouter/routerai обычно вида `openai/gpt-4o`).
- Модуль `google_sheets_writer.py` записывает результат в таблицу Google Sheets:
  - Имя таблицы по умолчанию: `Medium_Digest`
  - Столбцы: `Date`, `Title`, `Summaries`, `Tag`, `Link`
- Скрипт проходит циклом по всем статьям (из Gmail или PDF на Google Drive) и для каждой:
  1. Получает summary от выбранного AI-провайдера
  2. Добавляет строку в Google Sheets с датой, заголовком, аннотацией, пустым Tag и ссылкой на статью

---

## Развёртывание в Docker

### Предварительные требования

- Docker и Docker Compose установлены на сервере.
- Google OAuth токены (`token.json`, `token_sheets.json`) **сгенерированы заранее** на локальной машине (где есть браузер), т.к. Docker-контейнер работает headless и не может открыть окно авторизации Google.

### 1. Подготовка токенов (однократно, на локальной машине)

Запустите скрипт локально хотя бы один раз:

```bash
python main.py
```

При первом запуске откроется браузер для авторизации в Google (Drive и Sheets).
После этого в директории проекта появятся файлы:

- `token.json` — токен Google Drive
- `token_sheets.json` — токен Google Sheets

### 2. Подготовка файлов на сервере

```bash
# Клонируйте/скопируйте проект на сервер
scp -r ReadEmail/ user@server:/opt/medium-digest/

# Создайте папку для секретов
mkdir -p /opt/medium-digest/secrets

# Скопируйте секретные файлы (с локальной машины)
scp credentials.json  user@server:/opt/medium-digest/secrets/
scp token.json        user@server:/opt/medium-digest/secrets/
scp token_sheets.json user@server:/opt/medium-digest/secrets/
```

### 3. Настройка `.env`

Скопируйте `.env.example` в `.env` и заполните:

```bash
cp .env.example .env
nano .env
```

Убедитесь, что пути к файлам указывают внутрь контейнера:

```env
GOOGLE_DRIVE_CREDENTIALS_FILE=/app/secrets/credentials.json
GOOGLE_DRIVE_TOKEN_FILE=/app/secrets/token.json
GOOGLE_SHEETS_TOKEN_FILE=/app/secrets/token_sheets.json
```

### 4. Сборка и запуск

```bash
# Сборка образа
docker compose build

# Однократный запуск
docker compose up

# Или в фоне
docker compose up -d
```

### 5. Запуск по расписанию (cron)

Отредактируйте `docker-compose.yml` — замените `command`:

```yaml
command: cron
environment:
  - CRON_SCHEDULE=0 8 * * *    # каждый день в 08:00 UTC
```

Затем:

```bash
docker compose up -d
```

Логи можно смотреть:

```bash
# Логи контейнера
docker compose logs -f

# Или подключиться к контейнеру
docker exec -it medium-digest tail -f /var/log/medium_digest.log
```

### 6. Полезные команды

```bash
# Пересборка после изменений кода
docker compose build --no-cache && docker compose up -d

# Остановка
docker compose down

# Ручной запуск внутри работающего контейнера
docker exec -it medium-digest python main.py

# Просмотр логов
docker compose logs -f --tail=50
```

### Структура файлов на сервере

```
/opt/medium-digest/
├── .env                  # конфигурация (не попадает в образ)
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── secrets/              # монтируется как volume
│   ├── credentials.json  # OAuth credentials Google
│   ├── token.json        # токен Google Drive
│   └── token_sheets.json # токен Google Sheets
├── main.py
├── gmail_auth.py
├── digest_reader.py
├── article_scraper.py
├── openai_gpts.py
├── gdrive_reader.py
├── google_sheets_writer.py
└── requirements.txt
```
