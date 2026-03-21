#!/usr/bin/env python3
# page_id_finder_adv.py
import sys
import re
import requests
from bs4 import BeautifulSoup
import time

# Selenium import (sadece gerektiğinde)
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except Exception:
    SELENIUM_AVAILABLE = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

def debug_print(msg):
    print(f"[+] {msg}")

def fetch_requests(url, timeout=10):
    debug_print(f"requests GET -> {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r
    except Exception as e:
        debug_print(f"requests error: {e}")
        return None

def looks_like_html(response):
    if response is None:
        return False
    ct = response.headers.get('Content-Type','').lower()
    text = (response.text or "").strip()[:200].lower()
    # basic checks
    if 'text/html' in ct:
        return True
    if text.startswith('<!doctype html') or '<html' in text:
        return True
    return False

def find_ids_in_html(html):
    ids = set()
    soup = BeautifulSoup(html, 'html.parser')
    # body class içinde page-id
    body = soup.find('body')
    if body and body.get('class'):
        for c in body.get('class'):
            m = re.search(r'page-id-(\d+)', c)
            if m:
                ids.add(m.group(1))
            m2 = re.search(r'postid-(\d+)', c)
            if m2:
                ids.add(m2.group(1))
    # hidden comment_post_ID
    for inp in soup.find_all('input', {'name':'comment_post_ID'}):
        if inp.get('value'):
            ids.add(inp['value'])
    # id="post-42" veya data-post-id
    for tag in soup.find_all(True):
        for attr in ('id','data-post-id','data-id','data-postid'):
            if attr in tag.attrs:
                v = str(tag[attr])
                m = re.search(r'(\d{1,7})', v)
                if m:
                    ids.add(m.group(1))
    return ids

def try_wp_rest(url):
    # build base
    try:
        parts = url.split('/',3)
        base = parts[0] + '//' + parts[2]
    except Exception:
        return None
    slug = url.rstrip('/').split('/')[-1]
    api_urls = [
        f"{base}/wp-json/wp/v2/pages?slug={slug}",
        f"{base}/wp-json/wp/v2/posts?slug={slug}"
    ]
    for api in api_urls:
        debug_print(f"Trying WP REST API -> {api}")
        try:
            r = requests.get(api, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, list) and len(j)>0 and 'id' in j[0]:
                    return str(j[0]['id'])
        except Exception as e:
            debug_print(f"WP REST error: {e}")
    return None

def fetch_with_selenium(url, wait=2):
    if not SELENIUM_AVAILABLE:
        debug_print("Selenium veya webdriver-manager yüklü değil.")
        return None
    debug_print("Launching headless browser (Selenium)...")
    opts = Options()
    # headless yeni mod:
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    # optional: set user-agent
    opts.add_argument(f"user-agent={HEADERS['User-Agent']}")
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.get(url)
        time.sleep(wait)  # basit bekleme; gerekirse arttır
        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        debug_print(f"Selenium error: {e}")
        return None

def main():
    if len(sys.argv) != 2:
        print("Usage: python page_id_finder_adv.py <URL>")
        sys.exit(1)
    url = sys.argv[1]
    # 1) normal requests
    r = fetch_requests(url)
    if r is None:
        debug_print("No response from requests.")
    else:
        debug_print(f"HTTP {r.status_code}  Content-Type: {r.headers.get('Content-Type')}")
    # check WP REST API first (fast)
    wp_id = try_wp_rest(url)
    if wp_id:
        print(f"WP REST API found ID: {wp_id}")
        # still continue to parse HTML too
    # 2) if requests returned HTML-like content, parse
    found_ids = set()
    if looks_like_html(r):
        debug_print("Response looks like HTML. Parsing...")
        found_ids |= find_ids_in_html(r.text)
    else:
        debug_print("Response does NOT look like HTML or is empty/JS-rendered.")
    # 3) if none found, try selenium (JS render)
    if not found_ids and not wp_id:
        debug_print("Trying Selenium fallback (JS-rendered pages)...")
        html2 = fetch_with_selenium(url, wait=3)
        if html2:
            found_ids |= find_ids_in_html(html2)
    # collect results
    results = set(found_ids)
    if wp_id:
        results.add(str(wp_id))
    if results:
        print("Found possible page IDs: " + ", ".join(sorted(results)))
    else:
        print("No page IDs found. Debug info:")
        if r is None:
            print(" - requests returned no response (timeout / network issue).")
        else:
            print(f" - HTTP status: {r.status_code}")
            print(f" - Content-Type: {r.headers.get('Content-Type')}")
            head_snip = (r.text or "")[:500].replace('\n',' ')
            print(f" - Head snippet: {head_snip[:400]}...")
        if not SELENIUM_AVAILABLE:
            print(" - Selenium not available; install selenium + webdriver-manager to try JS-rendered pages.")
        else:
            print(" - Selenium attempted; if still nothing, page likely requires login or blocks bots.")

if __name__ == "__main__":
    main()
