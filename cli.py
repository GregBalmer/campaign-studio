"""Command-line run of the whole pipeline, with no approvals in between.

    python3 cli.py                       # the sample campaign, demo images
    python3 cli.py long-light --provider openai
    python3 cli.py path/to/brief.json --provider mock

It uses the same functions as the app. Approvals are recorded as "cli", so the
report shows clearly that no person reviewed these frames.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from studio import brief as brief_mod  # noqa: E402
from studio import config, pipeline, providers  # noqa: E402


def main() -> int:
    # Windows consoles and redirected output may not be UTF-8; never crash on
    # printing a Japanese line.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    config.load_env()
    ap = argparse.ArgumentParser(description="Generate campaign creatives from a brief.")
    ap.add_argument("campaign", nargs="?", default="long-light",
                    help="a campaign id in workspace/ (default: long-light), or a path to brief.json")
    ap.add_argument("--provider", choices=["mock", "openai"], default=None,
                    help="image and translation provider (default: openai if a key is set, else mock)")
    args = ap.parse_args()

    pipeline.ensure_samples()
    target = Path(args.campaign)
    if target.suffix == ".json":
        try:
            b = brief_mod.load(target)
        except brief_mod.BriefError as e:
            print("The brief needs fixing:\n  - " + "\n  - ".join(e.problems))
            return 2
        cid = pipeline.slug(b["campaign"])
        dest = config.WORKSPACE / cid
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(target.parent, dest)
        if target.name != "brief.json":
            shutil.copy(target, dest / "brief.json")
    else:
        cid = args.campaign

    provider = args.provider or providers.default_name()
    by = "cli"
    try:
        pipeline.with_campaign(cid, lambda c: c.set_provider(provider))
        c = pipeline.Campaign(cid)
        print(f"Campaign: {c.brief['campaign']}  ·  provider: {provider}")
        for p in c.brief["products"]:
            ps = pipeline.generate_master(cid, p["id"], by)
            how = "reused the supplied photo" if ps["origin"] == "supplied" else f"generated in {ps.get('seconds')}s"
            print(f"  master  {p['name']}: {how}")
            pipeline.with_campaign(cid, lambda c, pid=p["id"]: c.approve_master(pid, by))
        copy = pipeline.translate_all(cid, by)
        for lang, entry in copy.items():
            print(f"  words   {lang}: {entry['text']}")
            pipeline.with_campaign(cid, lambda c, lang=lang: c.approve_copy(lang, by))
        frames = pipeline.with_campaign(cid, lambda c: c.fan_out(by))
    except (pipeline.StudioError, providers.ProviderError) as e:
        print(f"\nStopped: {e}")
        return 1

    out = config.OUTPUTS / cid
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    s = report["summary"]
    print(f"\n{s['frames']} frames in {out.relative_to(ROOT)}/")
    print(f"Checks: {s['checks_passed']}/{s['checks_total']} passed · "
          f"{s['frames_with_warnings']} with warnings · {s['frames_with_failures']} with failures")
    for f in frames.values():
        flagged = [c for c in f["checks"] if c["status"] != "pass"]
        for chk in flagged:
            print(f"  {chk['status'].upper():4}  {f['path']}: {chk['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
