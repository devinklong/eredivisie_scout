"""
Diagnostic: checks what's actually in the page after SeleniumBase UC mode
loads one of the league-level FBref stat pages -- confirms whether
Cloudflare's challenge actually cleared, and what table-related class
names really exist on this page type (may differ from the team-level
squad page our original logic was built against).
"""

from bs4 import BeautifulSoup, Comment
from seleniumbase import SB

URL = "https://fbref.com/en/comps/23/passing/Eredivisie-Stats"


def main():
    with SB(uc=True, test=True) as sb:
        sb.uc_open_with_reconnect(URL, reconnect_time=8)
        html = sb.get_page_source()

    print(f"Page source length: {len(html)} characters")

    if "Just a moment" in html or "cf-browser-verification" in html:
        print("STILL ON CLOUDFLARE CHALLENGE PAGE -- did not clear.")
    else:
        print("No Cloudflare challenge text detected -- likely real content.")

    print("\n--- First 500 characters ---")
    print(html[:500])

    soup = BeautifulSoup(html, "html.parser")

    # Find every div whose class contains "table_container", regardless
    # of the exact full class string, to see what's really on this page.
    print("\n--- Divs with 'table_container' in class (direct HTML) ---")
    direct_matches = soup.find_all("div", class_=lambda c: c and "table_container" in c)
    for d in direct_matches:
        print(f"  class={d.get('class')}, id={d.get('id')}")

    print(f"\nTotal direct matches: {len(direct_matches)}")

    # Also check inside comments
    print("\n--- Checking inside HTML comments ---")
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    print(f"Total comments on page: {len(comments)}")
    comment_table_count = 0
    for comment in comments:
        if "table_container" in comment:
            comment_table_count += 1
    print(f"Comments containing 'table_container': {comment_table_count}")

    # List all <table> ids on the page directly, comments included --
    # this is often the fastest way to find the real target.
    print("\n--- All <table id=...> found anywhere (including in comments) ---")
    for comment in comments:
        if "<table" in comment:
            comment_soup = BeautifulSoup(comment, "html.parser")
            for t in comment_soup.find_all("table"):
                print(f"  (in comment) table id={t.get('id')}")
    for t in soup.find_all("table"):
        print(f"  (direct) table id={t.get('id')}")


if __name__ == "__main__":
    main()
