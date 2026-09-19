import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re
import time
import os

# Try to import Playwright, fallback to None if not available
try:
    from playwright.sync_api import sync_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser = None
    Page = None


def _is_human_verification_text(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return (
        "verify you are human" in t
        or "human verification" in t
        or "captcha" in t
        or "cloudflare" in t
        or "attention required" in t
    )


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_browser_headers() -> Dict[str, str]:
    """Return realistic browser headers to avoid 403 Forbidden from Medium."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://medium.com/"
    }


def _extract_main_text(html: str) -> str:
    """
    Extract article text from Medium HTML, similar to parse_article.py approach.
    Tries multiple strategies to find the main content.
    """
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = []

    # Strategy 1: Look for <article> tag (Medium's main container)
    article_tag = soup.find("article")
    if article_tag:
        # Find all text elements: p, h2, h3, h4, li, blockquote, pre
        text_elements = article_tag.find_all(["p", "h2", "h3", "h4", "li", "blockquote", "pre"])
        
        for elem in text_elements:
            text = elem.get_text(separator=" ", strip=True)
            # Filter short elements and navigation/menu items
            if text and len(text) > 15:
                text_lower = text.lower()
                # Skip navigation, subscription prompts, etc.
                if not any(word in text_lower[:30] for word in [
                    "follow", "subscribe", "sign up", "member-only", 
                    "written by", "published in", "get started"
                ]):
                    paragraphs.append(text)
        
        if len(paragraphs) >= 5:
            # Remove duplicates while preserving order
            seen = set()
            unique_paragraphs = []
            for p in paragraphs:
                if p not in seen:
                    seen.add(p)
                    unique_paragraphs.append(p)
            return "\n\n".join(unique_paragraphs)

    # Strategy 2: Fallback to <main> tag
    main_tag = soup.find("main")
    if main_tag:
        text_elements = main_tag.find_all(["p", "h2", "h3", "h4"])
        for elem in text_elements:
            text = elem.get_text(separator=" ", strip=True)
            if text and len(text) > 15:
                paragraphs.append(text)
        
        if len(paragraphs) >= 3:
            seen = set()
            unique_paragraphs = []
            for p in paragraphs:
                if p not in seen:
                    seen.add(p)
                    unique_paragraphs.append(p)
            return "\n\n".join(unique_paragraphs)

    # Strategy 3: Extract all paragraphs from body
    all_paragraphs = soup.find_all("p")
    if all_paragraphs:
        text_parts = []
        for p in all_paragraphs:
            text = p.get_text(separator=" ", strip=True)
            if text and len(text) > 30:
                text_lower = text.lower()
                if not any(word in text_lower[:30] for word in [
                    "follow", "subscribe", "sign up", "member-only"
                ]):
                    text_parts.append(text)
        
        if text_parts:
            return "\n\n".join(text_parts)

    # Strategy 4: Get all text and split by lines
    body = soup.find("body")
    if body:
        full_text = body.get_text(separator="\n", strip=True)
        lines = full_text.split("\n")
        text_parts = []
        for line in lines:
            line = line.strip()
            if line and len(line) > 30:
                line = " ".join(line.split())  # Normalize whitespace
                text_parts.append(line)
        
        if text_parts:
            return "\n\n".join(text_parts[:50])  # Limit to first 50 paragraphs

    return "Не удалось извлечь текст статьи"


def _extract_text_with_playwright(page: Page, url: str, debug: bool = False) -> Optional[str]:
    """
    Extract article text using Playwright (similar to parse_article.py).
    """
    try:
        if debug:
            print(f"  → Loading page with Playwright: {url}")

        # Medium держит открытые соединения (аналитика/стримы), поэтому
        # ожидание networkidle почти всегда заканчивается таймаутом.
        # Достаточно дождаться события load и немного подождать динамику.
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(10)  # Additional wait for dynamic content
        
        # Wait for article container to appear
        try:
            page.wait_for_selector('article', timeout=15000)
        except:
            if debug:
                print("  ⚠ Article selector not found, trying alternative selectors...")
        
        # Scroll to trigger lazy loading
        for i in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.5)")
            time.sleep(0.5)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)
        
        paragraphs = []
        
        # Strategy 1: Try to find article element with various selectors
        article_elem = None
        selectors = ['article', '[role="article"]', 'main article', '.postArticle', '[data-testid="post-content"]']
        
        for selector in selectors:
            try:
                article_elem = page.query_selector(selector)
                if article_elem:
                    if debug:
                        print(f"  ✓ Found article with selector: {selector}")
                    break
            except:
                continue
        
        if article_elem:
            # Find all paragraph-like elements
            text_selectors = ['p', 'h2', 'h3', 'h4', 'h5', 'li', 'blockquote', 'pre', 'div[data-testid="paragraph"]']
            text_elements = []
            
            for sel in text_selectors:
                try:
                    elements = article_elem.query_selector_all(sel)
                    text_elements.extend(elements)
                except:
                    continue
            
            if debug:
                print(f"  → Found {len(text_elements)} text elements")
            
            for elem in text_elements:
                try:
                    # Check if element is visible
                    if not elem.is_visible():
                        continue
                    
                    text = elem.inner_text().strip()
                    if not text or len(text) < 20:  # Minimum length for meaningful content
                        continue
                    
                    text_lower = text.lower()
                    
                    # Skip navigation, subscription prompts, etc.
                    skip_patterns = [
                        'follow', 'subscribe', 'sign up', 'member-only',
                        'written by', 'published in', 'get started',
                        'clap', 'responses', 'share', 'more from',
                        'become a member', 'upgrade to medium'
                    ]
                    
                    if any(pattern in text_lower[:50] for pattern in skip_patterns):
                        continue
                    
                    # Skip very short lines that are likely UI elements
                    if len(text) < 20:
                        continue
                    
                    paragraphs.append(text)
                    
                except Exception as e:
                    if debug:
                        print(f"  ⚠ Error processing element: {e}")
                    continue
            
            if len(paragraphs) >= 3:
                # Remove duplicates while preserving order
                seen = set()
                unique_paragraphs = []
                for p in paragraphs:
                    # Normalize text for comparison
                    p_normalized = ' '.join(p.split())
                    if p_normalized not in seen and len(p_normalized) >= 20:
                        seen.add(p_normalized)
                        unique_paragraphs.append(p)
                
                if debug:
                    print(f"  ✓ Extracted {len(unique_paragraphs)} unique paragraphs")
                
                if len(unique_paragraphs) >= 3:
                    return "\n\n".join(unique_paragraphs)
        
        # Strategy 2: Fallback - get all text from article element
        if article_elem:
            try:
                full_text = article_elem.inner_text()
                if full_text and len(full_text) > 200:
                    lines = full_text.split('\n')
                    text_parts = []
                    for line in lines:
                        line = line.strip()
                        if line and len(line) > 30:
                            line_lower = line.lower()
                            # Skip UI elements
                            if not any(pattern in line_lower[:50] for pattern in [
                                'follow', 'subscribe', 'sign up', 'member-only',
                                'clap', 'responses', 'share', 'more from'
                            ]):
                                text_parts.append(' '.join(line.split()))
                    
                    if len(text_parts) >= 3:
                        if debug:
                            print(f"  ✓ Extracted {len(text_parts)} text parts from full text")
                        return "\n\n".join(text_parts[:100])  # Limit to first 100 parts
            except Exception as e:
                if debug:
                    print(f"  ⚠ Error extracting full text: {e}")
        
        # Strategy 3: Try to find main content area
        try:
            main_content = page.query_selector('main, [role="main"], .postArticle-content, [data-testid="post-content"]')
            if main_content:
                full_text = main_content.inner_text()
                if full_text and len(full_text) > 200:
                    lines = full_text.split('\n')
                    text_parts = []
                    for line in lines:
                        line = line.strip()
                        if line and len(line) > 30:
                            text_parts.append(' '.join(line.split()))
                    
                    if len(text_parts) >= 3:
                        if debug:
                            print(f"  ✓ Extracted {len(text_parts)} text parts from main content")
                        return "\n\n".join(text_parts[:100])
        except:
            pass

        # Strategy 4: LAST RESORT — взять полный HTML из отрендеренной страницы
        # и прогнать через существующий парсер _extract_main_text. Это избавляет
        # от привязки к конкретным селекторам Playwright.
        try:
            if debug:
                print("  → Falling back to page.content() + _extract_main_text()")
            html = page.content()
            text = _extract_main_text(html)
            if text and len(text) > 50:
                if debug:
                    print(f"  ✓ Fallback extracted {len(text)} characters")
                return text
        except Exception as e:
            if debug:
                print(f"  ⚠ Fallback HTML parse error: {e}")
        
        if debug:
            print("  ✗ Could not extract meaningful text")
        
        return None
        
    except Exception as e:
        print(f"  ✗ Playwright error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return None


def fetch_articles_content(articles: List[Dict[str, str]], timeout: int = 30, delay: float = 10.0, use_playwright: bool = True, debug: bool = False) -> List[Dict[str, str]]:
    """
    Given a list of {"Title": ..., "Link": ...}, fetch each page and extract main text.
    Uses Playwright if available to avoid 403 Forbidden errors.
    
    Args:
        articles: List of dicts with "Title" and "Link" keys
        timeout: Request timeout in seconds (default: 30)
        delay: Delay between requests in seconds to avoid rate limiting (default: 10.0)
        use_playwright: Use Playwright if available (default: True)
    
    Returns:
        List of dicts with "Title", "Link" and "Text" keys
    """
    results: List[Dict[str, str]] = []
    
    # Filter articles - only process actual article links
    article_links = []
    for item in articles:
        url = item.get("Link", "").strip()
        if url and re.search(r'/@[\w-]+/[\w-]+', url):
            article_links.append(item)
    
    if not article_links:
        return results
    
    total = len(article_links)
    
    # Use Playwright if available and requested
    if use_playwright and PLAYWRIGHT_AVAILABLE:
        print(f"Using Playwright to fetch {total} articles...")
        with sync_playwright() as p:
            # If Medium triggers a human verification challenge, headless browsers often get blocked.
            # Allow running in headed mode once, then persist cookies to storage_state.json.
            headless = _env_bool("PLAYWRIGHT_HEADLESS", True)
            storage_state_path = os.getenv("PLAYWRIGHT_STORAGE_STATE", "storage_state.json")

            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )

            context_kwargs = {
                "locale": "en-US",
                "user_agent": _get_browser_headers().get("User-Agent"),
                "extra_http_headers": _get_browser_headers(),
            }

            if storage_state_path and os.path.exists(storage_state_path):
                if debug:
                    print(f"[DEBUG] Loading Playwright storage state from: {storage_state_path}")
                context_kwargs["storage_state"] = storage_state_path

            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            
            try:
                for idx, item in enumerate(article_links, 1):
                    title = item.get("Title", "").strip()
                    url = item.get("Link", "").strip()
                    
                    print(f"[{idx}/{total}] Fetching: {title[:60]}...")
                    
                    text = _extract_text_with_playwright(page, url, debug=debug)
                    
                    if text and len(text) >= 50:
                        results.append({
                            "Title": title or url,
                            "Link": url,
                            "Text": text
                        })
                        print(f"  ✓ Extracted {len(text)} characters")
                    else:
                        # Detect anti-bot challenge and provide actionable guidance
                        if text and _is_human_verification_text(text):
                            msg = (
                                "[ERROR] Medium requires human verification (anti-bot).\n"
                                "Run once with PLAYWRIGHT_HEADLESS=false to pass the check in a real browser window,\n"
                                "then re-run with PLAYWRIGHT_HEADLESS=true. Cookies will be saved to storage_state.json.\n"
                                f"URL: {url}"
                            )
                            results.append({
                                "Title": title or url,
                                "Link": url,
                                "Text": msg
                            })
                        else:
                            results.append({
                                "Title": title or url,
                                "Link": url,
                                "Text": "[ERROR] Could not extract meaningful text from the page"
                            })
                    
                    # Delay between requests
                    if idx < total and delay > 0:
                        time.sleep(delay)
            
            finally:
                # Persist cookies/state for future runs
                try:
                    if storage_state_path:
                        if debug:
                            print(f"[DEBUG] Saving Playwright storage state to: {storage_state_path}")
                        context.storage_state(path=storage_state_path)
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                browser.close()
    
    else:
        # Fallback to requests
        if use_playwright and not PLAYWRIGHT_AVAILABLE:
            print("Warning: Playwright requested but not available. Falling back to requests.")
            print("Install with: pip install playwright && playwright install chromium")
        
        headers = _get_browser_headers()
        session = requests.Session()
        session.headers.update(headers)
        
        for idx, item in enumerate(article_links, 1):
            title = item.get("Title", "").strip()
            url = item.get("Link", "").strip()
            
            try:
                print(f"[{idx}/{total}] Fetching: {title[:60]}...")
                
                resp = session.get(url, timeout=timeout, allow_redirects=True)
                
                # Check if we got blocked
                if resp.status_code == 403:
                    results.append({
                        "Title": title or url,
                        "Link": url,
                        "Text": f"[ERROR] 403 Forbidden - Medium blocked the request. Install Playwright: pip install playwright && playwright install chromium"
                    })
                    continue
                
                resp.raise_for_status()
                
                # Extract text
                text = _extract_main_text(resp.text)
                
                if not text or len(text) < 50:
                    results.append({
                        "Title": title or url,
                        "Link": url,
                        "Text": "[ERROR] Could not extract meaningful text from the page"
                    })
                else:
                    results.append({
                        "Title": title or url,
                        "Link": url,
                        "Text": text
                    })
                    print(f"  ✓ Extracted {len(text)} characters")
                
            except requests.exceptions.Timeout:
                results.append({
                    "Title": title or url,
                    "Link": url,
                    "Text": f"[ERROR] Request timeout after {timeout} seconds"
                })
            except requests.exceptions.RequestException as exc:
                results.append({
                    "Title": title or url,
                    "Link": url,
                    "Text": f"[ERROR] {type(exc).__name__}: {str(exc)}"
                })
            except Exception as exc:
                results.append({
                    "Title": title or url,
                    "Link": url,
                    "Text": f"[ERROR] Unexpected error: {type(exc).__name__}: {str(exc)}"
                })
            
            # Delay between requests
            if idx < total and delay > 0:
                time.sleep(delay)

    return results
