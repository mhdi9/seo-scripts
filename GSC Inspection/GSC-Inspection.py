import json
import time
import pandas as pd
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os

# ================== تنظیمات ==================
CLIENT_SECRET_FILE = r'D:\client_secret04aefc65po.apps.googleusercontent.com.json'

TOKEN_FILE = 'token.json'

SITE_URL = 'https://talasea.ir/'                    # حتماً با / آخر

INPUT_CSV = r'D:\Talasea\urls.csv'

OUTPUT_CSV = r'D:\Talasea\inspection_results.csv'

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
# ============================================

def get_service():
    creds = None
    # اگر قبلاً توکن داریم، ازش استفاده کن
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    # اگر توکن معتبر نبود، لاگین جدید
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)   # مرورگر باز میشه
        
        # ذخیره توکن برای دفعات بعدی
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('searchconsole', 'v1', credentials=creds)

# تابع بررسی تک تک URL
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
        
        index_result = response.get('inspectionResult', {}).get('indexStatusResult', {})
        
        return {
            'url': url,
            'status': index_result.get('verdict', 'ERROR'),
            'coverage_state': index_result.get('coverageState'),
            'last_crawl_time': index_result.get('lastCrawlTime'),
            'page_fetch_state': index_result.get('pageFetchState'),
            'robots_txt_state': index_result.get('robotsTxtState'),
            'error': None
        }
    except Exception as e:
        return {'url': url, 'status': 'ERROR', 'error': str(e)}

# ============== اجرای اصلی ==============
service = get_service()

df = pd.read_csv(INPUT_CSV)
urls = df.iloc[:, 0].astype(str).tolist()

results = []
for i, url in enumerate(urls, 1):
    print(f"[{i}/{len(urls)}] Checking → {url}")
    result = inspect_url(service, url)
    results.append(result)
    
    # رعایت Rate Limit
    time.sleep(0.5)   # تقریبا ۲ درخواست در ثانیه (امن)

# ذخیره نتایج
output_df = pd.DataFrame(results)
output_df.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
print(f"\n✅ تمام شد! نتایج در فایل {OUTPUT_CSV} ذخیره شد.")
