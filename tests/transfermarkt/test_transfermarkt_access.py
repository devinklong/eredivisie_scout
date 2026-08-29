"""
First access test for Transfermarkt -- entirely unexplored so far this
project. Following the same escalation pattern used for FBref (plain
requests -> headers/session -> cloudscraper -> SeleniumBase UC mode,
only escalating as far as actually needed): try the cheapest approach
first and let the real response tell us what's required, rather than
assuming Transfermarkt is either fully open or fully Cloudflare-hardened
like FBref turned out to be.

Target: a real Eredivisie club's squad page, since that's the shape of
page a scraper would eventually need to work against at scale.
"""

import requests

URL = "https://www.transfermarkt.com/ajax-amsterdam/startseite/verein/610"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def main():
    print(f"Requesting: {URL}")
    response = requests.get(URL, headers=HEADERS, timeout=15)

    print(f"Status code: {response.status_code}")
    print(f"Response length: {len(response.text)} characters")

    if response.status_code == 200:
        print("SUCCESS with plain requests -- no Cloudflare/bot-detection escalation needed (yet).")
        print("\n--- First 500 characters ---")
        print(response.text[:500])
    else:
        print("Non-200 response -- check headers below for clues (Server, Cf-Mitigated, etc.)")
        print("\n--- Response headers ---")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")
        print("\n--- First 500 characters of body ---")
        print(response.text[:500])


if __name__ == "__main__":
    main()
