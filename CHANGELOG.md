# Changelog

## v3: Firefly adapter

- **An Adobe Firefly adapter.** Written to Adobe's published API (sign in, start a job, wait, download) and not yet run against a live account, which the code, the Models panel and README all say. Every request and every error message is proven against a stand-in server, offline, on every push (`tools/fake_firefly.py`, `tools/test_firefly.py`).
- **Images and translation are chosen separately.** The Models panel has two groups, Images (Demo, OpenAI, Adobe Firefly) and Translation (Demo, OpenAI), because Firefly doesn't translate. Campaigns saved before the split keep their choice for both. The command line gains `--images` and `--translation`; `--provider` still sets both.
- **Connect Firefly in the app.** Paste the client ID and secret under Models; they're checked with Adobe's sign-in and saved to `.env`. Firefly is never picked automatically.
- **Nothing is called Firefly unless Adobe made it.** Pointed at the stand-in server, the app records images as `firefly-test` in the history and `report.json`, and the Models panel says it's pointing at a test server.
- **`report.json` records who translated each line,** next to who made each image.
- **A thinner header, and New campaign moved into it.** A dark bar runs across the top: the app on the left; New campaign, Models, History and your account on the right. Starting a campaign lives there, away from the campaign you're working on. Below it, on the page colour, sit the campaign's name (click it to switch) and its numbers, then the four steps.
- **White means you can use it.** Forms, steps, buttons and menus sit on white; summaries, numbers and empty states sit on the page colour.
- **Blue for "do this".** Main buttons and chosen options are blue instead of black. Black is only ever text.
- **Steps look clickable.** Every step has the same thin outline that fills on hover; the current step is white, and a step you can't reach yet is faded. Step numbers are plain numerals; a finished step shows a green check. Red is no longer used for the current step, where it read as an error.
- **Adobe red, kept to the brand.** The app mark keeps its red tile, and a thin red line runs along the bottom of the window, always in view.
- **The main button never moves.** On every step it sits in a grey panel at the top of the right-hand column, with what's done so far. The bar along the bottom of the screen is gone.
- **Delete a campaign.** In the campaign menu, every campaign except the sample has a delete button that asks once before removing the campaign and its ads.
- **Every command sets itself up.** `cli.py`, the Firefly tests and the stand-in server now set up and use the app's private Python environment the way `start.py` does, so they run with plain `python3` on a fresh computer.
- **README screenshots retaken** for the new look.
- **Works on a phone.** The bar, steps, headings and the Key visual and Message steps fit a 375px-wide screen.

## After v2

- **New-market requests in one click.** The five-item checklist becomes one action: email the request, or post it to Slack when IT has connected a channel, or copy it for Teams or a ticket. The details fold away under "What's involved", and the market shows as Requested afterwards.

## v2: polish

- **Adobe branding, kept out of the work.** Adobe red is the single accent in the app chrome: the app mark, the current step, and a thin line across the top. The header says "Built for Adobe Firefly Services", and Settings marks Firefly as the production option. No Adobe logos are used. The ads themselves are never touched by app colour.
- **New app mark.** It shows one frame becoming many sizes. The old mark looked too much like the sample brand's sun.
- **Install as an app.** Chrome and Edge can install Campaign Studio in its own window, with a dock or taskbar icon.
- **Launching in a new market.** "Add market" separates ready markets from ones new to the brand. A new market opens a who-does-what checklist: typeface, native reviewer, restricted words, local ad rules and local assets. A copy button puts it in an email or ticket.
- **Proof it runs on Windows.** A GitHub workflow installs and runs the app from scratch on Windows, macOS and Linux on every push, walks the whole flow, and saves a screenshot from each machine (`tools/smoke_test.py`).

## v1: first complete build

The four-step app (Brief, Key visual, Message, Review and export), the pipeline and CLI, demo and OpenAI generators, eight automatic checks, `report.json` with approvals, a one-command setup, and the README.

The v1 snapshot also includes three fixes made right after the first review:
- Menus close on an outside click or Escape.
- The launcher and server are hardened for Windows.
- Briefs that ask for an unsupported language get a plain message.
