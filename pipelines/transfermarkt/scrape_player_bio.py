"""
Scrapes height and preferred foot from Transfermarkt player profile
pages using SeleniumBase UC mode -- NOT plain requests.

WHY UC MODE: a first version of this script used plain requests
(matching this project's README note that "plain requests works -- no
Cloudflare bypass needed" for Transfermarkt) and got a 405 Not Allowed
error on EVERY request, starting from the very first one, including a
manual retest of the exact URL already confirmed working in a real
browser (frenkie-de-jong/profil/spieler/326330). That confirms the
405 wasn't a URL-format problem -- it's Transfermarkt actively
rejecting the request. The README's "plain requests works" note was
confirmed specifically for the bulk transfer-history pages, NOT
individual player profile pages -- this project's own experience now
shows those need the same Cloudflare/anti-bot bypass approach already
used for FBref/WhoScored (SeleniumBase UC mode), not the lighter
approach that worked for transfer-history scraping.

IMPORTANT, UNTESTED CAVEAT: unlike FBref/WhoScored (where soccerdata
handles UC mode internally), this project has never directly written
its own SeleniumBase code before -- the exact API calls below
(Driver(uc=True), driver.get(), etc.) are based on SeleniumBase's
public documentation/general usage patterns, NOT verified against a
real run in this project. RUN test_single_player() FIRST and confirm
it actually returns real data before trusting this at any scale.

Per patch_list.md's established habit (confirmed cause of past WhoScored
crashes): SeleniumBase UC mode opens a REAL, VISIBLE Chrome window.
Leave it alone -- don't close or minimize it -- until the script
finishes, even during the single-player test.

Player IDs come from eredivisie_transfers.player_id, same as the
requests-based version this replaces.
"""

import re
import time

import psycopg2
from bs4 import BeautifulSoup
from seleniumbase import Driver

BASE_URL = "https://www.transfermarkt.com/-/profil/spieler/{player_id}"
PAGE_LOAD_WAIT_SECONDS = 3   # time to let the page fully render after driver.get()
REQUEST_DELAY_SECONDS = 3    # politeness delay between players, same convention as the WhoScored batch script


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def get_distinct_player_ids(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT player_id FROM eredivisie_transfers "
            "WHERE player_id IS NOT NULL "
            "AND player_id NOT IN (SELECT player_id FROM eredivisie_transfermarkt_player_bio) "
            "ORDER BY player_id"
        )
        return [row[0] for row in cur.fetchall()]


def parse_height_cm(text):
    """'1,81 m' -> 181. Returns None if no height pattern is found --
    a real, expected gap for some players, not a parsing failure."""
    match = re.search(r"(\d+)[,.](\d+)\s*m", text)
    if not match:
        return None
    meters, centimeters_fraction = match.groups()
    height_str = f"{meters}.{centimeters_fraction}"
    return round(float(height_str) * 100)


def parse_foot(text):
    """Returns the foot value lowercase, exactly as Transfermarkt
    displays it ('right', 'left', 'both'), or None if not found."""
    match = re.search(r"foot:?\s*(right|left|both)", text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower()


def scrape_player_bio(driver, player_id):
    """Fetches one player's profile page via the shared driver session
    and extracts height/foot. Returns (height_cm, foot) -- either or
    both may be None if Transfermarkt doesn't have that field for this
    player (a real, expected gap, not necessarily a scraping failure --
    see module docstring for how to tell the two apart).

    UPDATED: uses uc_open_with_reconnect() + uc_gui_click_captcha()
    instead of plain driver.get() -- confirmed necessary after a real
    run hit a Cloudflare-style "verify you are human" challenge
    (2026-09-07), the same class of anti-bot check already documented
    for WhoScored in patch_list.md. uc_open_with_reconnect() is
    SeleniumBase's own documented approach for this exact situation:
    it loads the page, then briefly disconnects/reconnects Chrome's
    devtools protocol in a way that's less detectable as automation.
    uc_gui_click_captcha() attempts to click through a Cloudflare
    Turnstile-style checkbox if one appears. NEITHER of these has been
    verified against a real Transfermarkt run yet -- test_single_player()
    below still needs to be run and its output checked before trusting
    this at scale."""
    url = BASE_URL.format(player_id=player_id)
    driver.uc_open_with_reconnect(url, reconnect_time=4)
    driver.uc_gui_click_captcha()
    time.sleep(PAGE_LOAD_WAIT_SECONDS)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    page_text = soup.get_text(separator="\n")

    height_cm = parse_height_cm(page_text)
    foot = parse_foot(page_text)

    return height_cm, foot


def test_single_player(player_id=326330):
    """RUN THIS FIRST. player_id 326330 = Frenkie de Jong, manually
    confirmed on a real page (2026-09-07): Height 1,81 m, Foot right.
    Print output and check it matches before trusting this at scale.

    Leave the Chrome window UC mode opens alone while this runs -- do
    not close or minimize it, per patch_list.md's established habit."""
    driver = Driver(uc=True)
    try:
        height_cm, foot = scrape_player_bio(driver, player_id)
        print(f"player_id={player_id}: height_cm={height_cm}, foot={foot!r}")
        print("Expected: height_cm=181, foot='right' -- confirm this matches "
              "before running main().")
    finally:
        driver.quit()


UPSERT_SQL = """
    INSERT INTO eredivisie_transfermarkt_player_bio (player_id, height_cm, foot, scraped_at)
    VALUES (%s, %s, %s, now())
    ON CONFLICT (player_id) DO UPDATE SET
        height_cm = EXCLUDED.height_cm,
        foot = EXCLUDED.foot,
        scraped_at = EXCLUDED.scraped_at
"""


def main():
    conn = get_connection()
    player_ids = get_distinct_player_ids(conn)
    print(f"Found {len(player_ids)} distinct player_ids in eredivisie_transfers.")

    succeeded = 0
    failed = []

    driver = Driver(uc=True)
    try:
        with conn.cursor() as cur:
            for i, player_id in enumerate(player_ids, start=1):
                print(f"[{i}/{len(player_ids)}] player_id={player_id}...", end=" ")
                try:
                    height_cm, foot = scrape_player_bio(driver, player_id)
                    cur.execute(UPSERT_SQL, (player_id, height_cm, foot))
                    conn.commit()
                    print(f"OK -- height_cm={height_cm}, foot={foot!r}")
                    succeeded += 1
                except Exception as e:
                    error_name = type(e).__name__
                    print(f"FAILED -- {error_name}: {e}")
                    failed.append(player_id)

                    # The Chrome window itself died (crash, unexpected
                    # close) -- confirmed real occurrence (2026-09-07,
                    # crashed around player 288/3092), not hypothetical.
                    # Without recreating the driver, EVERY remaining
                    # player in the batch would fail identically for
                    # the rest of the run, since there's no window left
                    # to control. Recreate it and keep going instead of
                    # requiring a manual restart.
                    if "no such window" in str(e).lower() or "NoSuchWindowException" in error_name:
                        print("  Chrome window died -- recreating driver and continuing...")
                        try:
                            driver.quit()
                        except Exception:
                            pass  # already dead, nothing to clean up
                        driver = Driver(uc=True)

                time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        driver.quit()

    print(f"\n{succeeded}/{len(player_ids)} succeeded")
    if failed:
        print(f"Failed player_ids: {failed}")

    conn.close()


if __name__ == "__main__":
    # RUN THIS FIRST -- comment out once confirmed working:
    # test_single_player()

    # Uncomment once test_single_player() output is confirmed correct:
    main()
