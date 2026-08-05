import os
import time
import pandas as pd
import requests

from bs4 import BeautifulSoup
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


# ================== تنظیمات ==================
CLIENT_SECRET_FILE = r'D:\Talasea\client_secret_1077579720671-tntvk1tgc25iv1js2v3acg04aefc65po.apps.googleusercontent.com.json'

TOKEN_FILE = 'token.json'

SITE_URL = 'https://talasea.ir/'  # حتماً با / آخر

INPUT_CSV = r'D:\Talasea\urls.csv'

OUTPUT_CSV = r'D:\Talasea\inspection_results.csv'

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
# ============================================


GOOGLEBOT_UA = (
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/41.0.2272.96 Mobile Safari/537.36 "
    "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)


def get_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE,
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('searchconsole', 'v1', credentials=creds)


def inspect_url(service, url):
    try:
        request_body = {
            "inspectionUrl": url,
            "siteUrl": SITE_URL,
            "languageCode": "en"
        }

        response = service.urlInspection().index().inspect(
            body=request_body
        ).execute()

        inspection_result = response.get('inspectionResult', {})
        index_result = inspection_result.get('indexStatusResult', {})

        return {
            'url': url,
            'gsc_verdict': index_result.get('verdict'),
            'coverage_state': index_result.get('coverageState'),
            'indexing_state': index_result.get('indexingState'),
            'last_crawl_time': index_result.get('lastCrawlTime'),
            'page_fetch_state': index_result.get('pageFetchState'),
            'robots_txt_state': index_result.get('robotsTxtState'),
            'crawled_as': index_result.get('crawledAs'),
            'google_canonical': index_result.get('googleCanonical'),
            'user_canonical': index_result.get('userCanonical'),
            'inspection_link': inspection_result.get('inspectionResultLink'),
            'gsc_error': None
        }

    except Exception as e:
        return {
            'url': url,
            'gsc_verdict': 'ERROR',
            'coverage_state': None,
            'indexing_state': None,
            'last_crawl_time': None,
            'page_fetch_state': None,
            'robots_txt_state': None,
            'crawled_as': None,
            'google_canonical': None,
            'user_canonical': None,
            'inspection_link': None,
            'gsc_error': str(e)
        }


def live_check_url(url):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": GOOGLEBOT_UA},
            timeout=20,
            allow_redirects=True
        )

        soup = BeautifulSoup(response.text, "html.parser")

        meta_robots_content = ""
        meta_googlebot_content = ""

        meta_robots = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "robots"})
        meta_googlebot = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "googlebot"})

        if meta_robots:
            meta_robots_content = meta_robots.get("content", "").lower()

        if meta_googlebot:
            meta_googlebot_content = meta_googlebot.get("content", "").lower()

        x_robots_tag = response.headers.get("X-Robots-Tag", "").lower()

        robots_text = f"{meta_robots_content} {meta_googlebot_content} {x_robots_tag}"

        noindex = "noindex" in robots_text
        nofollow = "nofollow" in robots_text

        live_available = (
            response.status_code == 200
            and not noindex
        )

        return {
            'live_http_status': response.status_code,
            'live_final_url': response.url,
            'live_available': live_available,
            'live_noindex': noindex,
            'live_nofollow': nofollow,
            'live_meta_robots': meta_robots_content,
            'live_meta_googlebot': meta_googlebot_content,
            'live_x_robots_tag': x_robots_tag,
            'live_error': None
        }

    except Exception as e:
        return {
            'live_http_status': None,
            'live_final_url': None,
            'live_available': False,
            'live_noindex': None,
            'live_nofollow': None,
            'live_meta_robots': None,
            'live_meta_googlebot': None,
            'live_x_robots_tag': None,
            'live_error': str(e)
        }


def final_status(row):
    if row.get('gsc_error'):
        return 'GSC_API_ERROR'

    if row.get('live_error'):
        return 'LIVE_CHECK_ERROR'

    if row.get('live_http_status') != 200:
        return 'URL_NOT_AVAILABLE_LIVE'

    if row.get('live_noindex') is True:
        return 'NOINDEX_LIVE'

    if row.get('robots_txt_state') == 'DISALLOWED':
        return 'BLOCKED_BY_ROBOTS_TXT_GSC'

    if row.get('page_fetch_state') not in ['SUCCESSFUL', None]:
        return 'PAGE_FETCH_PROBLEM_GSC'

    if row.get('gsc_verdict') != 'PASS':
        return 'GSC_INDEXING_ISSUE'

    return 'OK'


# ============== اجرای اصلی ==============
service = get_service()

df = pd.read_csv(INPUT_CSV)
urls = df.iloc[:, 0].dropna().astype(str).tolist()

results = []

for i, url in enumerate(urls, 1):
    print(f"[{i}/{len(urls)}] Checking → {url}")

    gsc_result = inspect_url(service, url)
    live_result = live_check_url(url)

    result = {**gsc_result, **live_result}
    results.append(result)

    time.sleep(0.5)

output_df = pd.DataFrame(results)
output_df['final_status'] = output_df.apply(final_status, axis=1)

output_df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

print(f"\n✅ تمام شد! نتایج در فایل زیر ذخیره شد:")
print(OUTPUT_CSV)