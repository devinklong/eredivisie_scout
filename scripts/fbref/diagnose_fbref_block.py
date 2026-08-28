"""
Diagnostic script: inspects the actual 403 response from FBref instead of
just catching the exception, so we know what kind of block we're dealing
with before choosing the next tool.
"""

import cloudscraper

URL = "https://fbref.com/en/squads/19c3f8c4/2026-2027/c23/Ajax-Stats-Eredivisie"

scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "darwin", "mobile": False}
)

response = scraper.get(URL, timeout=15)

print(f"Status code: {response.status_code}")
print(f"Response headers:")
for key, value in response.headers.items():
    print(f"  {key}: {value}")

print("\n--- First 1500 characters of response body ---")
print(response.text[:1500])
