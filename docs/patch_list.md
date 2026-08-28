# Patch List

Fixes to things that were built, ran, and behaved wrong — not a build plan. See `v1_roadmap.md` for what's still unbuilt.

## Open

1. **WhoScored `read_events()` reliability** — has crashed on 3 separate runs now (2026-08-27 morning, 2026-08-27 afternoon, 2026-08-28), always the same `_is_captcha_present()` TypeError on `None` page_source, always self-heals on retry within the same script run. **Likely real cause, per user (2026-08-28): closing/minimizing the automated Chrome tab mid-run.** SeleniumBase's UC mode pops up a real visible browser window during each `read_events()` call — if that tab gets closed or loses focus while the script is still working, the driver loses its window handle, which matches the `window_handles[-1]` IndexError seen once and is consistent with the browser-session-death pattern behind the other two crashes. Not a soccerdata bug — a workflow habit to fix: leave the SeleniumBase-launched Chrome window alone (don't close/minimize it) until the script finishes. Revisit only if it still happens after consistently not touching the window.

2. **Calendar refetch inefficiency** — every `read_events()` call re-fetches the full 10-page season calendar from scratch, even when already cached from an earlier `read_schedule()` call in the same session. Need to confirm reusing one `WhoScored` instance across multiple `read_events()` calls actually avoids this, or find another fix, before batch-scraping many matches.

## Done

- FBref access via `soccerdata` + SeleniumBase UC mode (Cloudflare bypass) — confirmed working, `standard`/`shooting`/`misc`/`playing_time`/`keeper` categories return real data.
- WhoScored access confirmed working for NED-Eredivisie via soccerdata (required a custom `WhoScored` entry in `league_dict.json`, same file as the FBref entry). `read_schedule()` and `read_events()` both tested successfully against real matches.
- **`derive_possession_stats.py` penalty-area mislabeling (2026-08-28)** — script originally computed only one penalty-area zone (x ≤ 17, near the defensive goal line) but labeled it `touches_att_pen_area`. Caught via a goalkeeper sanity check: Stijn van Gassel had by far the most touches in that zone (33), which only makes sense for a defensive box. Fixed by splitting into both `touches_def_pen_area` and `touches_att_pen_area`, computed from opposite ends of the pitch (x≤17 vs x≥83). Re-ran and confirmed: keeper now correctly shows 33 in `touches_def_pen_area`, 0 in `touches_att_pen_area`.

