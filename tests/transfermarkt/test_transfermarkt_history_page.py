"""
Tests access to Transfermarkt's full club transfer-history page (a
different page type from the squad/homepage tested previously) --
confirms whether the same plain-requests approach works here too, and
inspects real table structure if so. Tests both the .us URL as given
and the .com equivalent, since TLD/region could plausibly affect
bot-protection behavior.
"""

import requests
from bs4 import BeautifulSoup

URLS = {
    "us": "https://www.transfermarkt.us/psv-eindhoven/alletransfers/verein/383",
    "com": "https://www.transfermarkt.com/psv-eindhoven/alletransfers/verein/383",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def main():
    for label, url in URLS.items():
        print(f"\n{'=' * 60}")
        print(f"Testing {label}: {url}")
        print("=" * 60)

        response = requests.get(url, headers=HEADERS, timeout=15)
        print(f"Status: {response.status_code}, {len(response.text)} characters")

        if response.status_code != 200:
            print("Non-200 -- headers below:")
            for key, value in response.headers.items():
                print(f"  {key}: {value}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")
        print(f"Total <table> elements found: {len(tables)}")

        for i, table in enumerate(tables):
            classes = table.get("class")
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            row_count = len(table.find_all("tr"))
            if headers or row_count > 5:  # skip tiny/empty layout tables
                print(f"  Table {i}: class={classes}, rows={row_count}, headers={headers[:10]}")


if __name__ == "__main__":
    main()
