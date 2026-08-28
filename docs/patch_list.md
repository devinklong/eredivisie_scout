# Patch List

Fixes to things that were built, ran, and behaved wrong — not a build plan. See `v1_roadmap.md` for what's still unbuilt.

## Open

1. **WhoScored `read_events()` reliability** — crashed once this morning (`_is_captcha_present()` TypeError on `None` page_source after browser session died), succeeded on retry after a clean process restart. Root cause not fully confirmed — possibly leftover Chrome processes, possibly a genuine soccerdata bug. Not yet stress-tested across many matches in one run.

2. **Calendar refetch inefficiency** — every `read_events()` call re-fetches the full 10-page season calendar from scratch, even when already cached from an earlier `read_schedule()` call in the same session. Need to confirm reusing one `WhoScored` instance across multiple `read_events()` calls actually avoids this, or find another fix, before batch-scraping many matches.

## Done

- FBref access via `soccerdata` + SeleniumBase UC mode (Cloudflare bypass) — confirmed working, `standard`/`shooting`/`misc`/`playing_time`/`keeper` categories return real data.
- WhoScored access confirmed working for NED-Eredivisie via soccerdata (required a custom `WhoScored` entry in `league_dict.json`, same file as the FBref entry). `read_schedule()` and `read_events()` both tested successfully against real matches.

