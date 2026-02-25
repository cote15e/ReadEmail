import os
import json
from dotenv import load_dotenv
from gmail_auth import connect_imap
from digest_reader import fetch_medium_digest_articles, fetch_medium_subscription_articles
from article_scraper import fetch_articles_content
from gdrive_reader import fetch_medium_pdfs_from_gdrive
from openai_gpts import summarize_article
from google_sheets_writer import append_summary_row


def main():
    # Load environment variables
    load_dotenv()

    email_user = os.getenv("EMAIL_USER")
    email_pass = os.getenv("EMAIL_PASS")
    debug_mode = os.getenv("DEBUG", "false").lower() == "true"
    gdrive_folder = (os.getenv("GDRIVE_FOLDER_NAME") or "").strip()

    mail = None
    full_articles = []

    try:
        if gdrive_folder:
            # Режим: читать статьи из PDF на Google Диске
            if debug_mode:
                print(f"[DEBUG] Using Google Drive folder: {gdrive_folder}")
            full_articles = fetch_medium_pdfs_from_gdrive(gdrive_folder, debug=debug_mode)
        else:
            # Режим: читать статьи из Gmail
            if not email_user or not email_pass:
                print("Error: EMAIL_USER and EMAIL_PASS environment variables must be set.")
                return

            # Connect and fetch unread Medium digest messages
            if debug_mode:
                print("[DEBUG] Connecting to IMAP server...")
            mail = connect_imap(email_user, email_pass)
            if debug_mode:
                print("[DEBUG] Connected successfully!")

            # Step 1a: получить ссылки из дайджеста (noreply@medium.com)
            link_articles = fetch_medium_digest_articles(mail, debug=debug_mode)

            # Step 1b: получить ссылки из подписок (subscriptions@medium.com)
            subscription_articles = fetch_medium_subscription_articles(mail, debug=debug_mode)
            link_articles.extend(subscription_articles)

            if debug_mode:
                print(f"[DEBUG] Total articles to fetch: {len(link_articles)} "
                      f"(digest: {len(link_articles) - len(subscription_articles)}, "
                      f"subscriptions: {len(subscription_articles)})")

            # Step 2: скачать текст статей по ссылкам
            full_articles = fetch_articles_content(link_articles, debug=debug_mode)

        # Output JSON: список статей с полем Title, Link и Text
        print(json.dumps(full_articles, indent=4, ensure_ascii=False))

        # Step 3 (опционально): отправить статьи на анализ в OpenAI GPTs и записать в Google Sheets
        send_to_gpts = os.getenv("SEND_TO_GPT", "false").lower() in ("1", "true", "yes")
        if send_to_gpts and full_articles:
            model = os.getenv("OPENAI_MODEL", "gpt-4o")
            for idx, article in enumerate(full_articles, start=1):
                title = (article.get("Title") or "").strip()
                text = (article.get("Text") or "").strip()
                link = (article.get("Link") or "").strip()

                if not text:
                    if debug_mode:
                        print(f"[DEBUG] Skip article {idx}: empty text")
                    continue

                if debug_mode:
                    print(f"[DEBUG] Summarizing article {idx}: {title[:80]}")

                summary_result = summarize_article(
                    title=title,
                    text=text,
                    model=model,
                )

                if "error" in summary_result:
                    print(f"[GPTs] Error for article {idx}: {summary_result['error']}")
                    continue

                summary = summary_result.get("summary", "")
                if debug_mode:
                    print(f"[DEBUG] Summary length for article {idx}: {len(summary)} chars")

                try:
                    append_summary_row(title=title, summary=summary, link=link)
                except Exception as se:
                    print(f"[Sheets] Error writing article {idx} to Google Sheets: {se}")

    except Exception as e:
        print(f"An error occurred: {e}")
        if debug_mode:
            import traceback
            traceback.print_exc()
    finally:
        if mail is not None:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass


if __name__ == "__main__":
    main()
