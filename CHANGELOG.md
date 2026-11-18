# Changelog

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
