# Walkthrough: 19 Nov 2026

Keep and show / keep but don't show / remove, feature by feature. Then the design list. Then map the assignment.

## Decisions

| Feature | Decision | Notes |
|---|---|---|
| Sign-in and demo accounts | Keep, don't show | One click on the prefilled demo account; click through in the video without comment |
| Launchers and Gatekeeper step | Keep, don't show | Video opens with the app already running; README lists `python3 start.py` first |
| Install as an app | Keep, cut from video | Saves about 15s |
| Phone layouts | Keep, don't show | Mention only if asked |
| CI and screenshot tool | Keep, one line in README | macOS CI job only runs once the repo is public; say "tested by hand" for Mac |
| Models panel | Keep and show (~10s), add the one-line explainer | Video: demo images with no key, OpenAI with a key, Firefly wired for Adobe |
| Firefly test server and "Test" labels | Keep as is | Labels only appear when the test server is connected |
| OpenAI key in the app | Keep, don't show | Keep the key form off camera; README names `.env` too |
| New, switch, delete campaigns | Keep, don't show | Proves it isn't one hardwired brief; README line with `cli.py path/to/brief.json` |
| Start over | Keep | Resets the demo |
| Suggest (who it's for) | Keep, don't show | Works without a key via the demo provider |
| Describe from photo | Keep, don't show | OpenAI only |
| Market search, Needs setup, request flow | Keep, don't show | All three send options stay; good to talk to live |
| Restricted words and 40-character count | Keep and show | Legal-check bonus; already in the demo at 1:30 |
| Product box and crop guides | Keep and show | Already at 0:50 |
| Editing the prompt | Keep, don't show | Try another makes the point on camera |
| Use my photo / Create one instead | Keep and show | Reuse-or-generate; narrated at 0:22 |
| Translation review in English | Keep and show, highlight #1 | Ask for a change stays out of the video |
| Shared card position across languages | Keep, one README sentence | |
| Size toggle | Keep, don't show | |
| Approve/reject, Approve all, lightbox | Keep; show Approve all and the flagged ad | Highlight #2; shortcuts and single rejects for questions |
| Download and Show folder | Keep and show, add Show folder to the video | Proves folders by product and ratio |
| History drawer | Keep, don't show | report.json covers logging |

Nothing removed. Video target about 2:45.

## Design and build list

Ticked when done.

From the late-night handoff:
- [x] Unchecked surfaces: Models panel (three states), History drawer, Review lightbox, sign-in page (findings below)
- [x] Key visual at 900px tall: measured (findings below)
- [x] `CAMPAIGN` label above vs number labels below: dropped the CAMPAIGN label (C)
- [x] Restart demo: sample only, small modal (Cancel / Restart), lands on the Brief
- [x] New campaign: dropdown with Blank campaign / Duplicate, then one popup (Cancel / Create); no name asked. Duplicate copies brief and photos only
- [x] README screenshots: retaken 19 Nov, sample restarted after
- [ ] Tag `v3` (only when Greg says)

From the walkthrough:
- [x] `docs/DEMO.md`: open with the app already running (drop the Finder and Gatekeeper beat)
- [x] `docs/DEMO.md`: drop the install-as-an-app beat at 2:55
- [x] README: `python3 start.py` first, launchers as the no-terminal option
- [x] README: one line on CI and the screenshot tool, accurate about which systems run in CI
- [x] Models panel: a line under each group, icons and dark headings, no subtitle
- [x] `docs/DEMO.md`: Models beat, one sentence (~10s)
- [x] README: one line that the app takes any brief (New campaign, or `cli.py` with a `brief.json`)
- [x] Test Show folder on Mac: works, Finder opens `outputs/<campaign>/`
- [x] `docs/DEMO.md`: click Show folder in the 2:20 beat
- [x] README: one sentence on the shared card position across languages

From the look-only pass (each needs Greg's call; A/B before any visual change):
- [x] History: times only ("7:15 PM"), no day, while the lightbox says "14 h ago"; yesterday's entries read as today's
- [x] Lightbox: a rejected ad's note is amber ("Rejected by…"), but the tile marks rejects in red
- [x] Models: "For production" badge now neutral grey
- [x] Models: explainer done (line per group)
- [x] Sign-in: subtitle leaves "time." alone on its own line
- [x] README step descriptions are stale after the redesign: Message still says "What it says" and "side by side with a live ad preview"
- [x] README: one line on file size. Ads are lossless PNG, 1.6 to 2.4 MB each; JPEG at quality 85 is about 200 KB (8 to 10× smaller). Not building it, just saying it was considered

Checked, no change needed:
- Sign-in page, Models connect forms (OpenAI and Firefly), History layout, lightbox checks list
- Key visual at 1440×900: the first product's image ends at 893px, just above the fold; the card's bottom edge is 16px below it. The prompt sits below the fold
- The red 4px line along the bottom of every screen is the intended Adobe accent (`body::after`)

## The assignment, ask by ask

Source: `FDE Take Home Lite.pdf`. ✓ met · ◐ met with a caveat · ✗ not met.

| Ask | | Where it's met |
|---|---|---|
| Brief in JSON/YAML with 2+ products, market, audience, message | ✓ | `samples/long-light/brief.json`; Brief step; `cli.py path/to/brief.json`. JSON only (reason in `studio/brief.py`) |
| Accept input assets and reuse them | ✓ | Daylight Mist's photo is reused ("Your photo"); photos can be dropped in on the Brief |
| Generate missing assets with a GenAI image model | ✓ | After-Sun Gel generated by OpenAI; Firefly adapter written to Adobe's docs; demo images with no key |
| At least three aspect ratios | ✓ | 1:1, 9:16, 16:9 |
| Campaign message on the final posts; localized a plus | ✓ | English and Japanese, set in real fonts on every ad |
| Run locally | ✓ | `python3 start.py` (app) and `cli.py` (command line) |
| Outputs organized by product and aspect ratio | ✓ | `outputs/<campaign>/<product>/<ratio>/`; Show folder |
| README: how to run, example in/out, design decisions, assumptions | ✓ | All four sections exist |
| Bonus: brand checks (logo, colors) | ✓ | Logo and brand-color checks on every ad |
| Bonus: legal checks (prohibited words) | ✓ | Restricted words per language, live on the Brief and blocking approval |
| Bonus: logging or reporting | ✓ | `report.json` and History |
| Storage (Azure, AWS or Dropbox) | ◐ | Local folder; README names it as a limitation |
| Video, 2–3 minutes, helps interviewers set up and run it | ✓ | Script is about 2:55, with a 10s terminal setup beat |
| Public GitHub repository | ✗ | Private until Greg says |
| Business goals 4–5 (CTR, conversions, insights) | ◐ | Not built; README says so; report.json gives each ad a stable id |

README now opens with this map as *The assignment, ask by ask* (19 Nov).
