"""
Loops extract_all_transfers() + save_to_json() (from
extract_transfermarkt_transfer_history.py) across all 29 clubs that
have played in the Eredivisie since 2010-11, confirmed via manual
Wikipedia season-by-season compilation (2026-08-29).

Dordrecht and Willem II initially had /transfers/ URLs (a different,
shorter page than the other 27 clubs' /alletransfers/) -- corrected to
their real /alletransfers/ URLs (2026-08-29). All 29 clubs now use the
same confirmed page structure.

Each club is scraped and dumped to its own JSON file immediately, so a
failure partway through doesn't require re-scraping clubs already done.
"""

import time

from extract_transfermarkt_transfer_history import extract_all_transfers, save_to_json

# name -> full URL, exactly as confirmed (2026-08-29). All 29 use the
# same /alletransfers/ page structure.
CLUBS = {
    "ado_den_haag": "https://www.transfermarkt.com/ado-den-haag/alletransfers/verein/1268",
    "ajax": "https://www.transfermarkt.us/ajax-amsterdam/alletransfers/verein/610",
    "almere_city": "https://www.transfermarkt.com/almere-city-fc/alletransfers/verein/723",
    "az": "https://www.transfermarkt.us/az-alkmaar/alletransfers/verein/1090",
    "cambuur": "https://www.transfermarkt.com/sc-cambuur-leeuwarden/alletransfers/verein/133",
    "de_graafschap": "https://www.transfermarkt.com/de-graafschap-doetinchem/alletransfers/verein/642",
    "dordrecht": "https://www.transfermarkt.com/fc-dordrecht/alletransfers/verein/1455",
    "emmen": "https://www.transfermarkt.com/fc-emmen/alletransfers/verein/1283",
    "excelsior": "https://www.transfermarkt.com/excelsior-rotterdam/alletransfers/verein/798",
    "feyenoord": "https://www.transfermarkt.com/feyenoord-rotterdam/alletransfers/verein/234",
    "fortuna_sittard": "https://www.transfermarkt.com/fortuna-sittard/alletransfers/verein/385",
    "go_ahead_eagles": "https://www.transfermarkt.com/go-ahead-eagles-deventer/alletransfers/verein/1435",
    "groningen": "https://www.transfermarkt.us/fc-groningen/alletransfers/verein/202",
    "heerenveen": "https://www.transfermarkt.us/sc-heerenveen/alletransfers/verein/306",
    "heracles_almelo": "https://www.transfermarkt.us/heracles-almelo/alletransfers/verein/1304",
    "nac_breda": "https://www.transfermarkt.us/nac-breda/alletransfers/verein/132",
    "nec_nijmegen": "https://www.transfermarkt.com/nec-nijmegen/alletransfers/verein/467",
    "pec_zwolle": "https://www.transfermarkt.us/pec-zwolle/alletransfers/verein/1269",
    "psv": "https://www.transfermarkt.com/psv-eindhoven/alletransfers/verein/383",
    "rkc_waalwijk": "https://www.transfermarkt.us/rkc-waalwijk/alletransfers/verein/235",
    "roda_jc": "https://www.transfermarkt.com/roda-jc-kerkrade/alletransfers/verein/192",
    "sparta": "https://www.transfermarkt.com/sparta-rotterdam/alletransfers/verein/468",
    "telstar": "https://www.transfermarkt.com/sc-telstar/alletransfers/verein/1434",
    "twente": "https://www.transfermarkt.us/fc-twente-enschede/alletransfers/verein/317",
    "utrecht": "https://www.transfermarkt.us/fc-utrecht/alletransfers/verein/200",
    "vitesse": "https://www.transfermarkt.us/vitesse-arnheim/alletransfers/verein/499",
    "volendam": "https://www.transfermarkt.us/fc-volendam/alletransfers/verein/724",
    "vvv_venlo": "https://www.transfermarkt.com/vvv-venlo/alletransfers/verein/1426",
    "willem_ii": "https://www.transfermarkt.com/willem-ii-tilburg/alletransfers/verein/403",
}

# Both previously-flagged clubs (dordrecht, willem_ii) now have confirmed
# real /alletransfers/ URLs as of 2026-08-29 -- no longer flagged.
FLAGGED_CLUBS = set()


def main():
    results = {}
    failures = []

    for name, url in CLUBS.items():
        print(f"\n{'=' * 60}\nScraping {name}...\n{'=' * 60}")

        if name in FLAGGED_CLUBS:
            print(f"  WARNING: {name}'s URL uses /transfers/, not /alletransfers/ -- "
                  f"output may not match the other clubs' structure. Verify before trusting.")

        try:
            transfers = extract_all_transfers(url)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            failures.append(name)
            continue

        print(f"  Extracted {len(transfers)} transfers")
        save_to_json(transfers, f"data/transfermarkt/{name}_transfers.json")
        results[name] = len(transfers)

        # Be polite between requests -- same courtesy used throughout
        # this project's other scrapers.
        time.sleep(3)

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Succeeded: {len(results)}/{len(CLUBS)}")
    for name, count in results.items():
        flag = " (FLAGGED, verify)" if name in FLAGGED_CLUBS else ""
        print(f"  {name}: {count} transfers{flag}")
    if failures:
        print(f"\nFailed: {failures}")


if __name__ == "__main__":
    main()
