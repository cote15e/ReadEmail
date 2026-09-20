import email
from email.header import decode_header
from email.message import Message
from typing import Iterable, List, Dict

from bs4 import BeautifulSoup


def clean_text(text: str) -> str:
    return text.strip() if text else ""


def _decode_mime_header(value: str) -> str:
    """Decode RFC 2047 encoded-words in Subject/From headers into a readable string."""
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(enc or "utf-8", errors="replace"))
            except Exception:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def parse_digest_subjects(raw: str | None) -> List[str]:
    """
    Parse digest subject filter from settings.
    Comma-separated list, e.g. "Medium Weekly Digest,Medium Daily Digest".
    Empty / None means no subject filter (match all from the sender).
    """
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _subject_matches_any(subj: str, subjects: List[str]) -> bool:
    subj_lower = (subj or "").lower()
    return any(needle.lower() in subj_lower for needle in subjects)


def _matches_medium_digest(msg: Message, from_addr: str, subjects: List[str] | None = None) -> bool:
    """
    Check if email is a Medium digest from the expected sender.
    If subjects is non-empty, the Subject header must contain one of them
    (substring, case-insensitive).
    """
    from_h = _decode_mime_header(msg.get("From", ""))
    if from_addr.lower() not in from_h.lower():
        return False
    if subjects:
        subj_h = _decode_mime_header(msg.get("Subject", ""))
        return _subject_matches_any(subj_h, subjects)
    return True


def _iter_html_parts(msg: Message) -> Iterable[str]:
    """Yield HTML payloads from the email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in content_disposition:
                continue
            if content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                try:
                    yield payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    # Fallback to utf-8 replace if charset was invalid
                    yield payload.decode("utf-8", errors="replace")
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload is not None:
                yield payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _looks_like_article_link(href: str, text: str) -> bool:
    """Basic heuristic to keep Medium article links."""
    href_lower = href.lower()
    if not href_lower.startswith("http"):
        return False
    # Keep links that reference Medium domains; adjust as needed if Medium uses redirects.
    return "medium.com" in href_lower or "link.medium.com" in href_lower or "reader.medium.com" in href_lower


def _extract_articles_from_html(html: str, debug: bool = False) -> List[Dict[str, str]]:
    """
    Extract article titles and links from Medium digest HTML.
    
    Medium digest structure:
    - Articles are typically in <h2> tags with links inside
    - Links to articles contain medium.com/@username/article-slug pattern
    - We prioritize h2 > a structure, then fall back to any article links
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()

    if debug:
        print(f"[DEBUG] Parsing HTML, length: {len(html)}")

    # Strategy 1: Look for h2 tags containing article links (Medium digest structure)
    h2_tags = soup.find_all("h2")
    if debug:
        print(f"[DEBUG] Found {len(h2_tags)} h2 tags")
    
    for h2 in h2_tags:
        # Find the main article link inside h2 (usually the first <a>)
        link = h2.find("a", href=True)
        if link:
            title = clean_text(h2.get_text())
            href = link["href"].strip()
            if title and href and len(title) >= 10:  # Article titles are usually longer
                if _looks_like_article_link(href, title):
                    key = (title, href)
                    if key not in seen:
                        seen.add(key)
                        results.append({"Title": title, "Link": href})
                        if debug:
                            print(f"[DEBUG] Found article via h2: {title[:50]}...")

    # Strategy 2: Fallback - find all article links that weren't captured above
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not _looks_like_article_link(href, ""):
            continue
        
        # Skip if this link was already found via h2
        title = clean_text(a.get_text())
        if not title or len(title) < 10:
            continue
        
        # Skip navigation/footer links (common patterns)
        if any(skip in href.lower() for skip in ["/me/", "/plans", "/jobs", "/help", "/policy", "twitter.com", "itunes.apple.com", "play.google.com"]):
            continue
        
        key = (title, href)
        if key not in seen:
            seen.add(key)
            results.append({"Title": title, "Link": href})
            if debug:
                print(f"[DEBUG] Found article via fallback: {title[:50]}...")

    if debug:
        print(f"[DEBUG] Total articles extracted: {len(results)}")
    
    return results


def _extract_continue_reading_link(html: str, debug: bool = False) -> str:
    """
    Извлекает ссылку из кнопки "Continue reading" в письме от subscriptions@medium.com.
    Ищет тег <a> с текстом содержащим "Continue reading" / "Read more" / "Read the story".
    """
    soup = BeautifulSoup(html, "html.parser")

    button_texts = ["continue reading", "read more", "read the story"]
    for a in soup.find_all("a", href=True):
        link_text = (a.get_text() or "").strip().lower()
        if any(bt in link_text for bt in button_texts):
            href = a["href"].strip()
            if href.startswith("http"):
                if debug:
                    print(f"[DEBUG] Found 'Continue reading' link: {href[:120]}")
                return href

    # Fallback: ищем любую ссылку на medium.com, которая выглядит как статья
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "medium.com" in href.lower() and "/" in href.split("medium.com")[-1]:
            link_text = (a.get_text() or "").strip()
            if len(link_text) > 20:
                if debug:
                    print(f"[DEBUG] Fallback article link: {href[:120]}")
                return href

    return ""


def fetch_medium_subscription_articles(
    mail,
    mailbox: str = "inbox",
    digest_subjects: List[str] | None = None,
    debug: bool = False,
) -> List[Dict[str, str]]:
    """
    Обрабатывает письма от subscriptions@medium.com (отдельные статьи по подписке).
    Извлекает ссылку на статью из кнопки "Continue reading".
    Помечает обработанные письма как прочитанные.

    Returns:
        Список [{"Title": ..., "Link": ...}, ...]
    """
    from_addr = "subscriptions@medium.com"

    if debug:
        print(f"\n[DEBUG] === Processing subscription emails from {from_addr} ===")

    status, _ = mail.select(mailbox)
    if status != "OK":
        if debug:
            print(f"[DEBUG] Failed to select mailbox: {status}")
        return []

    criteria = f'(UNSEEN FROM "{from_addr}")'
    if debug:
        print(f"[DEBUG] Searching with criteria: {criteria}")

    status, messages = mail.search(None, criteria)
    if status != "OK":
        if debug:
            print(f"[DEBUG] Search failed: {status}")
        return []

    email_ids = messages[0].split()
    if debug:
        print(f"[DEBUG] Found {len(email_ids)} unread subscription email(s)")

    if not email_ids:
        return []

    results: List[Dict[str, str]] = []

    for idx, e_id in enumerate(email_ids, 1):
        if debug:
            print(f"\n[DEBUG] Subscription email {idx}/{len(email_ids)}: ID {e_id.decode() if isinstance(e_id, bytes) else e_id}")

        res, msg_data = mail.fetch(e_id, "(RFC822)")
        if res != "OK":
            if debug:
                print(f"[DEBUG] Failed to fetch message: {res}")
            continue

        for response_part in msg_data:
            if not isinstance(response_part, tuple):
                continue

            msg = email.message_from_bytes(response_part[1])
            subj = _decode_mime_header(msg.get("Subject", ""))

            if debug:
                print(f"[DEBUG] Subject: {subj}")

            # Пропускаем дайджест — его обрабатывает fetch_medium_digest_articles
            skip_subjects = digest_subjects or ["medium weekly digest", "medium daily digest"]
            if _subject_matches_any(subj, skip_subjects):
                if debug:
                    print("[DEBUG] Skipping: this is a digest email")
                continue

            # Извлекаем ссылку из HTML
            link = ""
            for html in _iter_html_parts(msg):
                link = _extract_continue_reading_link(html, debug=debug)
                if link:
                    break

            if not link:
                if debug:
                    print("[DEBUG] No article link found in email, skipping")
                mail.store(e_id, "+FLAGS", "\\Seen")
                continue

            title = subj.strip() if subj.strip() else "Untitled"
            results.append({"Title": title, "Link": link})

            if debug:
                print(f"[DEBUG] Extracted subscription article: {title[:60]} -> {link[:80]}")

            mail.store(e_id, "+FLAGS", "\\Seen")

    if debug:
        print(f"\n[DEBUG] Total subscription articles extracted: {len(results)}")

    return results


def fetch_medium_digest_articles(
    mail,
    mailbox: str = "inbox",
    from_addr: str = "noreply@medium.com",
    subjects: List[str] | None = None,
    debug: bool = False,
) -> List[Dict[str, str]]:
    """
    Fetch unread Medium digest emails, extract article titles/links, mark them as read.
    Returns a list of dicts: {"Title": ..., "Link": ...}

    Args:
        mail: IMAP connection object
        mailbox: Mailbox name (default: "inbox")
        from_addr: Sender email address (default: "noreply@medium.com")
        subjects: Subject substrings to match (from EMAIL_DIGEST_SUBJECT).
                  Empty/None matches all unread mail from the sender.
        debug: Enable debug output (default: False)
    """
    subjects = subjects or []
    if debug:
        print(f"[DEBUG] Step 1: Selecting mailbox '{mailbox}'")
        print(f"[DEBUG] Digest subject filter: {subjects or '(none — all from sender)'}")
    
    status, _ = mail.select(mailbox)
    if status != "OK":
        if debug:
            print(f"[DEBUG] Failed to select mailbox: {status}")
        return []

    # Search for UNSEEN emails from Medium (not all emails, only unread ones)
    criteria = f'(UNSEEN FROM "{from_addr}")'
    if debug:
        print(f"[DEBUG] Step 2: Searching with criteria: {criteria}")
    
    status, messages = mail.search(None, criteria)
    if status != "OK":
        if debug:
            print(f"[DEBUG] Search failed: {status}")
        return []

    email_ids = messages[0].split()
    if debug:
        print(f"[DEBUG] Step 3: Found {len(email_ids)} unread email(s) from {from_addr}")
    
    if not email_ids:
        if debug:
            print("[DEBUG] No unread emails found")
        return []

    results: List[Dict[str, str]] = []

    for idx, e_id in enumerate(email_ids, 1):
        if debug:
            print(f"\n[DEBUG] Step 4.{idx}: Processing email ID: {e_id.decode() if isinstance(e_id, bytes) else e_id}")
        
        # Step 1: fetch only minimal headers to avoid downloading large messages up front.
        res, hdr_data = mail.fetch(e_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        if res != "OK":
            if debug:
                print(f"[DEBUG] Failed to fetch headers: {res}")
            continue

        header_msg = None
        for response_part in hdr_data:
            if isinstance(response_part, tuple):
                header_msg = email.message_from_bytes(response_part[1])
                break

        if header_msg is None:
            if debug:
                print("[DEBUG] Could not parse header message")
            continue

        from_h = _decode_mime_header(header_msg.get("From", ""))
        subj_h = _decode_mime_header(header_msg.get("Subject", ""))
        
        if debug:
            print(f"[DEBUG] From: {from_h}")
            print(f"[DEBUG] Subject: {subj_h}")

        if not _matches_medium_digest(header_msg, from_addr=from_addr, subjects=subjects):
            if debug:
                print("[DEBUG] Email does not match Medium digest criteria, skipping")
            continue

        if debug:
            print("[DEBUG] Email matches! Fetching full message...")

        # Step 2: now fetch the full message only for matching digests.
        res, msg_data = mail.fetch(e_id, "(RFC822)")
        if res != "OK":
            if debug:
                print(f"[DEBUG] Failed to fetch full message: {res}")
            continue

        parsed_any = False
        for response_part in msg_data:
            if not isinstance(response_part, tuple):
                continue
            msg = email.message_from_bytes(response_part[1])
            
            html_count = 0
            for html in _iter_html_parts(msg):
                html_count += 1
                if debug:
                    print(f"[DEBUG] Found HTML part #{html_count}, length: {len(html)}")
                
                articles = _extract_articles_from_html(html, debug=debug)
                if articles:
                    parsed_any = True
                    if debug:
                        print(f"[DEBUG] Extracted {len(articles)} articles from HTML part #{html_count}")
                results.extend(articles)

        if parsed_any:
            if debug:
                print(f"[DEBUG] Marking email {e_id.decode() if isinstance(e_id, bytes) else e_id} as read")
            # Mark as read after successfully processing the digest email.
            mail.store(e_id, "+FLAGS", "\\Seen")
        else:
            if debug:
                print("[DEBUG] No articles extracted, but marking as read anyway to avoid reprocessing")

    if debug:
        print(f"\n[DEBUG] Step 5: Total articles extracted: {len(results)}")
    
    return results

