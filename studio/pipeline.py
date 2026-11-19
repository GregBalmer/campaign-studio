"""The campaign workflow: set up -> approve the master -> approve the words ->
fan out and review.

The UI and the CLI both call these functions, so they always behave the same.
State for each campaign lives in `workspace/<id>/state.json`; finished creatives
and `report.json` go to `outputs/<id>/`.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import brief as brief_mod
from . import checks as checks_mod
from . import config, imaging, providers
from .providers import ProviderError

def _same_pixels(path: Path, img: Image.Image) -> bool:
    try:
        with Image.open(path) as old:
            return old.size == img.size and old.convert("RGB").tobytes() == img.convert("RGB").tobytes()
    except Exception:
        return False


MASTER_SIZE = 1536  # square; large enough to crop 9:16 and 16:9 from
_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StudioError(ValueError):
    """A problem the person can fix; message is already plain English."""


# ---------------------------------------------------------------- campaigns

def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "campaign"


def ensure_samples() -> None:
    """Copy each sample into the workspace the first time, so the app always
    opens on something ready to try."""
    config.WORKSPACE.mkdir(exist_ok=True)
    for src in sorted(config.SAMPLES.iterdir()) if config.SAMPLES.exists() else []:
        if (src / "brief.json").exists() and not (config.WORKSPACE / src.name).exists():
            shutil.copytree(src, config.WORKSPACE / src.name)


def reset_sample(cid: str) -> None:
    src = config.SAMPLES / cid
    if not src.exists():
        raise StudioError("Only sample campaigns can be reset.")
    with _lock:
        shutil.rmtree(config.WORKSPACE / cid, ignore_errors=True)
        shutil.rmtree(config.OUTPUTS / cid, ignore_errors=True)
        shutil.copytree(src, config.WORKSPACE / cid)


def start_over(cid: str, by: str | None = None) -> None:
    """Go back to step 1. A sample returns to how it shipped. A campaign someone
    made keeps its brief and photos; its key visuals, translations, ads and
    decisions are cleared."""
    if (config.SAMPLES / cid).exists():
        reset_sample(cid)
        return
    with _lock:
        c = Campaign(cid)
        for key in ("products", "copy", "frames"):
            c.state[key] = {}
        shutil.rmtree(c.dir / "masters", ignore_errors=True)
        shutil.rmtree(config.OUTPUTS / cid, ignore_errors=True)
        c.log(by, "campaign.restarted")
        c.save()


def delete_campaign(cid: str) -> None:
    """Remove a campaign someone made, and its finished ads. Samples can only be started over."""
    if (config.SAMPLES / cid).exists():
        raise StudioError("The sample can't be deleted. Start it over instead.")
    with _lock:
        c = Campaign(cid)  # checks the id and that the campaign exists
        shutil.rmtree(c.dir, ignore_errors=True)
        shutil.rmtree(config.OUTPUTS / cid, ignore_errors=True)


def list_campaigns() -> list[dict]:
    ensure_samples()
    out = []
    for d in sorted(config.WORKSPACE.iterdir()):
        if (d / "brief.json").exists():
            c = Campaign(d.name)
            out.append({"id": d.name, "name": c.brief.get("campaign", d.name),
                        "stage": c.stage(), "sample": (config.SAMPLES / d.name).exists(),
                        "updated": c.state.get("updated")})
    return out


def create_campaign(name: str) -> str:
    """Start a new campaign from the first sample's structure, blanked out."""
    ensure_samples()
    cid = slug(name)
    n = 2
    while (config.WORKSPACE / cid).exists():
        cid = f"{slug(name)}-{n}"
        n += 1
    d = config.WORKSPACE / cid
    (d / "assets").mkdir(parents=True)
    template = json.loads(next(config.SAMPLES.glob("*/brief.json")).read_text(encoding="utf-8"))
    new = {
        "campaign": name.strip() or "New campaign",
        "brand": template["brand"],
        "message": "",
        "message_language": "en",
        "audience": "",
        "markets": [{"region": "US", "name": "United States", "language": "en"}],
        "products": [
            {"id": "product-1", "name": "", "description": ""},
            {"id": "product-2", "name": "", "description": ""},
        ],
        "mood": "",
        "banned_words": template.get("banned_words", {}),
    }
    # Carry the brand logo over so a new campaign starts on-brand.
    logo = config.SAMPLES / next(config.SAMPLES.glob("*/brief.json")).parent.name / template["brand"]["logo"]
    if logo.exists():
        shutil.copy(logo, d / "assets" / logo.name)
    (d / "brief.json").write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
    return cid


class Campaign:
    def __init__(self, cid: str):
        if not re.fullmatch(r"[a-z0-9-]+", cid or ""):
            raise StudioError("That campaign doesn't exist.")
        self.id = cid
        self.dir = config.WORKSPACE / cid
        if not (self.dir / "brief.json").exists():
            raise StudioError("That campaign doesn't exist.")
        self.brief = json.loads((self.dir / "brief.json").read_text(encoding="utf-8"))
        sp = self.dir / "state.json"
        self.state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        self.state.setdefault("products", {})
        self.state.setdefault("copy", {})
        self.state.setdefault("frames", {})
        self.state.setdefault("log", [])
        # One service makes the images and one translates. A campaign saved before
        # they were split has a single "provider", which fills both.
        old = self.state.pop("provider", None)
        for kind in providers.KINDS:
            key = f"{kind}_provider"
            name = providers.resolve(kind, self.state.get(key) or old or providers.default_name(kind))
            if name not in [p["id"] for p in providers.available()[kind]]:
                name = providers.default_name(kind)
            self.state[key] = name
        # Ads built under different inputs or older layout rules are out of date, so the
        # review screen rebuilds them (keeping decisions on any that come out identical).
        for f in self.state["frames"].values():
            try:
                if f.get("signature") != self._signature(f["product"], f["format"], f["language"]):
                    f["stale"] = True
            except Exception:
                f["stale"] = True

    # ------------------------------------------------------------ storage
    def save(self) -> None:
        self.state["updated"] = now()
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def save_brief(self) -> None:
        (self.dir / "brief.json").write_text(json.dumps(self.brief, indent=2, ensure_ascii=False),
                                             encoding="utf-8")

    def log(self, by: str | None, event: str, detail: str = "") -> None:
        self.state["log"].append({"at": now(), "by": by or "someone", "event": event, "detail": detail})

    def out_dir(self) -> Path:
        return config.OUTPUTS / self.id

    def logo_path(self) -> Path | None:
        rel = self.brief.get("brand", {}).get("logo")
        return self.dir / rel if rel else None

    def product(self, pid: str) -> dict:
        for p in self.brief["products"]:
            if p["id"] == pid:
                return p
        raise StudioError("That product isn't in this campaign.")

    def pstate(self, pid: str) -> dict:
        return self.state["products"].setdefault(pid, {"attempt": 0, "history": []})

    # ------------------------------------------------------------ stage
    def stage(self) -> str:
        pids = [p["id"] for p in self.brief.get("products", [])]
        if not all(self.state["products"].get(p, {}).get("approved") for p in pids):
            return "master" if any(self.state["products"].get(p, {}).get("master") for p in pids) else "setup"
        langs = brief_mod.languages(self.brief)
        if not all(self.state["copy"].get(lang, {}).get("approved") for lang in langs):
            return "words"
        return "review"

    # ------------------------------------------------------------ step 1: set up
    def update_brief(self, patch: dict) -> list[str]:
        """Apply edits from the set-up screen. Returns problems still to fix
        (empty when the brief is complete) rather than raising, so the form can
        save drafts."""
        allowed = {"campaign", "message", "audience", "mood", "markets", "products", "brand"}
        old_message = self.brief.get("message")
        old_products = {p["id"]: dict(p) for p in self.brief.get("products", [])}
        for k, v in patch.items():
            if k in allowed:
                if k == "brand":
                    self.brief["brand"].update({kk: vv for kk, vv in v.items() if kk in ("name", "colors", "voice")})
                else:
                    self.brief[k] = v
        # Changing the message means every translation must be redone.
        if self.brief.get("message") != old_message:
            self.state["copy"] = {}
            self._stale_frames()
        # Changing what a product is makes its master out of date.
        for p in self.brief.get("products", []):
            before = old_products.get(p["id"])
            if before and (before.get("description") != p.get("description") or before.get("name") != p.get("name")):
                ps = self.pstate(p["id"])
                if ps.get("origin") == "generated":
                    ps["approved"] = None
        self.save_brief()
        self.save()
        try:
            brief_mod.validate(self.brief)
            return []
        except brief_mod.BriefError as e:
            return e.problems

    def save_upload(self, target: str, data: bytes, filename: str) -> str:
        """Store an uploaded product photo or logo. `target` is a product id or 'logo'."""
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception:
            raise StudioError("That file isn't an image we can read. Use PNG or JPG.") from None
        if min(img.size) < 400:
            raise StudioError(f"That image is only {img.size[0]}×{img.size[1]}. Use one at least 1000 pixels across.")
        (self.dir / "assets").mkdir(exist_ok=True)
        if target == "logo":
            name = "logo.png"
            img.convert("RGBA").save(self.dir / "assets" / name)
            self.brief["brand"]["logo"] = f"assets/{name}"
            self._stale_frames()
        else:
            p = self.product(target)
            name = f"{p['id']}-photo.png"
            img.convert("RGB").save(self.dir / "assets" / name)
            p["photo"] = f"assets/{name}"
            ps = self.pstate(p["id"])
            ps.update({"master": None, "approved": None, "origin": None})
        self.save_brief()
        self.save()
        return f"assets/{name}"

    def remove_photo(self, pid: str) -> None:
        p = self.product(pid)
        p.pop("photo", None)
        self.pstate(pid).update({"master": None, "approved": None, "origin": None})
        self.save_brief()
        self.save()

    # ------------------------------------------------------------ step 2: master
    def prompt_for(self, pid: str) -> str:
        p = self.product(pid)
        b = self.brief
        c = b["brand"]["colors"]
        return (
            f"Photorealistic advertising photograph for a social media campaign. "
            f"Hero product: {p['name']}. {p.get('description', '')} "
            f"Mood and setting: {b.get('mood', '')} "
            f"Audience: {b.get('audience', '')} "
            f"Let the palette lean toward the brand colors {c['primary']} and {c['accent']} without forcing them. "
            "Composition: a wide shot. The product is the clear hero, sharp and fully in frame, standing "
            "near the centre and a little below the middle, but small in the frame: no more than a quarter "
            "of the image height. Lots of calm, uncluttered space above and around it so the picture can be "
            "cropped to square, tall and wide formats and carry a headline. "
            "No text, no words, no extra logos, no watermarks, no people's faces."
        )

    def make_master(self, pid: str, by: str | None = None) -> dict:
        p = self.product(pid)
        ps = self.pstate(pid)
        if p.get("photo") and not ps.get("force_generate"):
            path = self.dir / p["photo"]
            img = Image.open(path).convert("RGB")
            name = f"masters/{pid}-supplied.png"
            (self.dir / "masters").mkdir(exist_ok=True)
            img.save(self.dir / name)
            ps.update({"master": name, "origin": "supplied", "provider": None, "prompt": None,
                       "zone": ps.get("zone") or p.get("photo_zone") or list(imaging.ZONE),
                       "focal": ps.get("focal") or p.get("photo_focal") or list(imaging.estimate_focal(img)),
                       "approved": None,
                       "size": list(img.size)})
            self.log(by, "master.supplied", p["name"])
            self.save()
            return ps

        raise StudioError("Use generate_master() for generated images.")

    def use_photo_or_generate(self, pid: str, generate: bool) -> None:
        self.pstate(pid)["force_generate"] = generate
        self.save()

    def set_focal(self, pid: str, x: float, y: float, w: float | None = None, h: float | None = None) -> dict:
        """Place the product box: centre (x, y) and, optionally, half-width and
        half-height, all as shares of the image."""
        ps = self.pstate(pid)
        if not ps.get("master"):
            raise StudioError("Make the master image first.")
        ps["focal"] = [round(min(max(x, 0.0), 1.0), 4), round(min(max(y, 0.0), 1.0), 4)]
        if w is not None and h is not None:
            ps["zone"] = [round(min(max(w, 0.02), 0.5), 4), round(min(max(h, 0.02), 0.5), 4)]
        self._stale_frames(pid)
        self.save()
        return ps

    def approve_master(self, pid: str, by: str) -> dict:
        ps = self.pstate(pid)
        if not ps.get("master"):
            raise StudioError("There's no master to approve yet.")
        ps["approved"] = {"by": by, "at": now()}
        self.log(by, "master.approved", self.product(pid)["name"])
        self.save()
        return ps

    def reopen_master(self, pid: str, by: str | None = None) -> None:
        self.pstate(pid)["approved"] = None
        self.log(by, "master.reopened", self.product(pid)["name"])
        self.save()

    def master_image(self, pid: str) -> Image.Image:
        ps = self.pstate(pid)
        if not ps.get("master"):
            raise StudioError("Make the master image first.")
        return Image.open(self.dir / ps["master"]).convert("RGB")

    # ------------------------------------------------------------ step 3: words
    def edit_copy(self, lang: str, text: str, by: str | None = None) -> dict:
        cur = self.state["copy"].get(lang)
        if cur is None:
            raise StudioError("Translate the message first.")
        text = text.strip()
        if not text:
            raise StudioError("The message can't be empty.")
        if text != cur["text"]:
            cur.update({"text": text, "origin": "edited" if cur["origin"] != "source" else "source",
                        "approved": None})
            if cur["origin"] == "edited":
                # The English meaning and the notes described the machine's line, not this one.
                cur.update({"back_translation": "", "note": "", "drift": ""})
            if lang == brief_mod.source_language(self.brief):
                # New source wording: every translation is now out of date.
                self.brief["message"] = text
                self.save_brief()
                for other in list(self.state["copy"]):
                    if other != lang:
                        del self.state["copy"][other]
            self.log(by, "copy.edited", lang)
            self._stale_frames()
            self.save()
        return cur

    def approve_copy(self, lang: str, by: str) -> dict:
        cur = self.state["copy"].get(lang)
        if cur is None:
            raise StudioError("Translate the message first.")
        hits = checks_mod.banned_hits(cur["text"], lang, self.brief)
        if hits:
            raise StudioError(f"Legal restricts {', '.join(hits)}. Change the wording before approving.")
        cur["approved"] = {"by": by, "at": now()}
        self.log(by, "copy.approved", lang)
        self.save()
        return cur

    def reopen_copy(self, lang: str, by: str | None = None) -> dict:
        cur = self.state["copy"].get(lang)
        if cur is None:
            raise StudioError("Translate the message first.")
        cur["approved"] = None
        self.log(by, "copy.reopened", lang)
        self.save()
        return cur

    # ------------------------------------------------------------ rendering
    def render(self, pid: str, fmt: str, lang: str, text: str | None = None) -> dict:
        if fmt not in config.FORMATS:
            raise StudioError("Unknown format.")
        ps = self.pstate(pid)
        master = self.master_image(pid)
        copy = text if text is not None else self._copy_text(lang)
        focal = tuple(ps.get("focal") or (0.5, 0.5))
        zone = tuple(ps.get("zone") or imaging.ZONE)
        # Every language's ad for this product and size puts the card in the same place.
        texts = [(copy if other == lang else self._copy_text(other), other) for other in brief_mod.languages(self.brief)]
        side = imaging.shared_side(master, fmt, focal, texts, self.brief["brand"], self.logo_path(), zone)
        layout = imaging.render(master, fmt, focal, copy, lang, self.brief["brand"], self.logo_path(), zone, side=side)
        layout["checks"] = checks_mod.run(layout, copy, lang, self.brief)
        layout["text"] = copy
        return layout

    def _copy_text(self, lang: str) -> str:
        return self.state["copy"].get(lang, {}).get("text") or self.brief["message"]

    def preview_png(self, pid: str, fmt: str, lang: str, text: str | None = None, width: int = 720) -> tuple[bytes, list]:
        layout = self.render(pid, fmt, lang, text)
        img = layout["image"]
        h = int(img.height * width / img.width)
        buf = io.BytesIO()
        img.resize((width, h), Image.LANCZOS).save(buf, "JPEG", quality=86)
        return buf.getvalue(), layout["checks"]

    # ------------------------------------------------------------ step 4: fan out
    def frame_key(self, pid: str, fmt: str, region: str) -> str:
        return f"{pid}/{fmt}/{region}"

    def _signature(self, pid: str, fmt: str, lang: str) -> str:
        ps = self.pstate(pid)
        # Every language's words, not just this one's: they share the card's position.
        words = [self._copy_text(other) for other in brief_mod.languages(self.brief)]
        parts = [ps.get("master"), str(ps.get("focal")), str(ps.get("zone")), lang, json.dumps(words, ensure_ascii=False),
                 json.dumps(self.brief["brand"], sort_keys=True), fmt,
                 imaging.LAYOUT_VERSION]
        return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]

    def _stale_frames(self, pid: str | None = None) -> None:
        for k, f in self.state["frames"].items():
            if pid is None or f["product"] == pid:
                f["stale"] = True

    def fan_out(self, by: str | None = None) -> dict:
        if self.stage() != "review":
            raise StudioError("Approve every master and every translation first.")
        out = self.out_dir()
        t0 = time.time()
        rendered = 0
        for p in self.brief["products"]:
            for fmt, spec in config.FORMATS.items():
                for m in self.brief["markets"]:
                    lang = m["language"]
                    key = self.frame_key(p["id"], fmt, m["region"])
                    sig = self._signature(p["id"], fmt, lang)
                    prev = self.state["frames"].get(key)
                    rel = f"{p['id']}/{spec['ratio'].replace(':', 'x')}/{m['region']}-{lang}.png"
                    if prev and prev.get("signature") == sig and (out / rel).exists():
                        prev["stale"] = False
                        continue
                    layout = self.render(p["id"], fmt, lang)
                    (out / rel).parent.mkdir(parents=True, exist_ok=True)
                    status = checks_mod.summary(layout["checks"])
                    # A decision stands only for the exact ad that was approved or rejected.
                    # If the rebuild is pixel-for-pixel the same (say, a layout rule changed
                    # that doesn't touch this ad), keep it; otherwise it's a new ad to review.
                    same = (prev and (out / rel).exists() and prev.get("status") == status
                            and _same_pixels(out / rel, layout["image"]))
                    if not same:
                        layout["image"].save(out / rel, optimize=True)
                        rendered += 1
                    self.state["frames"][key] = {
                        "product": p["id"], "format": fmt, "region": m["region"], "language": lang,
                        "path": rel, "checks": layout["checks"], "status": status,
                        "signature": sig, "stale": False,
                        "rendered_at": prev["rendered_at"] if same else now(),
                        "decision": prev.get("decision") if same else None,
                    }
        # Drop frames for products/markets no longer in the brief.
        valid = {self.frame_key(p["id"], f, m["region"]) for p in self.brief["products"]
                 for f in config.FORMATS for m in self.brief["markets"]}
        for k in list(self.state["frames"]):
            if k not in valid:
                del self.state["frames"][k]
        if rendered:
            self.log(by, "frames.rendered", f"{rendered} ad{'s' if rendered != 1 else ''}, new or changed, in {time.time() - t0:.1f}s")
        self.save()
        self.write_report()
        return self.state["frames"]

    def decide(self, key: str, decision: str | None, by: str, note: str = "") -> dict:
        f = self.state["frames"].get(key)
        if not f:
            raise StudioError("That frame doesn't exist. Run the fan-out again.")
        if decision not in ("approved", "rejected", None):
            raise StudioError("Decision must be approve or reject.")
        if decision == "approved" and f["status"] == checks_mod.FAIL:
            raise StudioError("This frame fails a check. Fix it before approving.")
        f["decision"] = {"value": decision, "by": by, "at": now(), "note": note} if decision else None
        self.log(by, f"frame.{decision or 'cleared'}", key + (f": {note}" if note else ""))
        self.save()
        self.write_report()
        return f

    # ------------------------------------------------------------ report
    def write_report(self) -> dict:
        frames = list(self.state["frames"].values())
        decided = [f for f in frames if f.get("decision")]
        report = {
            "campaign": self.brief["campaign"],
            "generated_at": now(),
            "brief": {k: self.brief.get(k) for k in ("message", "audience", "markets", "mood")},
            "products": [
                {
                    "id": p["id"], "name": p["name"],
                    "master_origin": self.pstate(p["id"]).get("origin"),
                    "provider": self.pstate(p["id"]).get("provider"),
                    "model": self.pstate(p["id"]).get("model"),
                    "attempts": self.pstate(p["id"]).get("attempt", 0),
                    "focal_point": self.pstate(p["id"]).get("focal"),
                    "prompt": self.pstate(p["id"]).get("prompt"),
                    "approved": self.pstate(p["id"]).get("approved"),
                } for p in self.brief["products"]
            ],
            "copy": self.state["copy"],
            "summary": {
                "frames": len(frames),
                "checks_passed": sum(1 for f in frames for c in f["checks"] if c["status"] == "pass"),
                "checks_total": sum(len(f["checks"]) for f in frames),
                "frames_with_failures": sum(1 for f in frames if f["status"] == "fail"),
                "frames_with_warnings": sum(1 for f in frames if f["status"] == "warn"),
                "approved": sum(1 for f in decided if f["decision"]["value"] == "approved"),
                "rejected": sum(1 for f in decided if f["decision"]["value"] == "rejected"),
                "awaiting_review": len(frames) - len(decided),
            },
            "frames": [{k: f[k] for k in ("path", "product", "format", "region", "language",
                                            "status", "checks", "decision", "rendered_at")} for f in frames],
            "activity": self.state["log"],
        }
        out = self.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    # ------------------------------------------------------------ view
    def view(self) -> dict:
        """Everything the UI needs, in one object."""
        try:
            brief_mod.validate(self.brief)
            problems: list[str] = []
        except brief_mod.BriefError as e:
            problems = e.problems
        return {
            "id": self.id,
            "brief": self.brief,
            "problems": problems,
            "stage": self.stage(),
            "providers": {"image": self.state["image_provider"], "text": self.state["text_provider"]},
            "products": {p["id"]: self.pstate(p["id"]) for p in self.brief.get("products", [])},
            "copy": self.state["copy"],
            "languages": brief_mod.languages(self.brief),
            "frames": self.state["frames"],
            "formats": config.FORMATS,
            "log": self.state["log"][-30:],
            "sample": (config.SAMPLES / self.id).exists(),
            "has_outputs": (self.out_dir() / "report.json").exists(),
            "market_requests": self.state.get("market_requests", {}),
        }

    def record_market_request(self, region: str, via: str, by: str | None) -> dict:
        """Remember that someone asked for a new market, so nobody asks twice."""
        if via not in ("email", "slack", "copy"):
            raise StudioError("Unknown way to send the request.")
        req = {"by": by or "someone", "at": now(), "via": via}
        self.state.setdefault("market_requests", {})[region] = req
        self.log(by, "market.requested", f"{region} by {via}")
        self.save()
        return req

    def set_provider(self, kind: str, name: str) -> None:
        """Choose who makes the images ("image") or who translates ("text")."""
        if kind not in providers.KINDS:
            raise StudioError("Choose either the image generator or the translation service.")
        name = providers.resolve(kind, name)
        entry = next((p for p in providers.available()[kind] if p["id"] == name), None)
        what = "image generator" if kind == "image" else "translation service"
        if entry is None:
            raise StudioError(f"Unknown {what}.")
        if not entry["ready"]:
            raise StudioError(f"{entry['label']} isn't connected yet. Add its credentials under Models first.")
        self.state[f"{kind}_provider"] = name
        self.save()


def with_campaign(cid: str, fn):
    """Run fn(campaign) under the lock, so two browser tabs can't clobber state."""
    with _lock:
        return fn(Campaign(cid))


__all__ = ["Campaign", "StudioError", "ProviderError", "list_campaigns", "create_campaign",
           "reset_sample", "start_over", "delete_campaign", "ensure_samples", "with_campaign", "generate_master", "translate_all"]


# ------------------------------------------------------------ slow steps
# Generation and translation can take a minute with a real provider. They run
# without holding the lock, then re-load the campaign and apply their result,
# so the person can work on one product while another is generating.

def generate_master(cid: str, pid: str, by: str | None = None, prompt: str | None = None,
                    from_brief: bool = False) -> dict:
    """Make a key visual. `prompt` is the person's own wording; once they've
    rewritten it, "Try another" keeps using theirs until they ask for the
    brief's wording again (`from_brief`)."""
    with _lock:
        c = Campaign(cid)
        p = c.product(pid)
        ps = c.pstate(pid)
        if p.get("photo") and not ps.get("force_generate"):
            return c.make_master(pid, by)
        provider = providers.get_image(c.state["image_provider"])
        prompt = (prompt or "").strip()[:4000] or None
        edited = bool(prompt) or bool(not from_brief and ps.get("prompt_edited") and ps.get("prompt"))
        prompt = prompt or (ps["prompt"] if edited else c.prompt_for(pid))
        attempt = ps.get("attempt", 0) + 1
        ps["attempt"] = attempt  # reserve the number so parallel clicks don't collide
        c.save()
        hints = {"name": p["name"], "description": p.get("description", ""),
                 "colors": c.brief["brand"]["colors"], "brand": c.brief["brand"]["name"]}
    seed = int(hashlib.sha1(f"{cid}{pid}{attempt}".encode()).hexdigest()[:8], 16)
    t0 = time.time()
    img = provider.generate_image(prompt, MASTER_SIZE, seed, hints)
    seconds = round(time.time() - t0, 1)
    with _lock:
        c = Campaign(cid)
        ps = c.pstate(pid)
        focal = list(img.info.get("focal", (0.5, 0.55)))
        name = f"masters/{pid}-{attempt}.png"
        (c.dir / "masters").mkdir(exist_ok=True)
        img.save(c.dir / name)
        if ps.get("master"):
            ps["history"].append(ps["master"])
        ps.update({"master": name, "origin": "generated", "provider": provider.id,
                   "zone": [round(v, 4) for v in img.info.get("zone", imaging.ZONE)],
                   "model": provider.model,
                   "prompt": prompt, "prompt_edited": edited, "focal": [round(f, 4) for f in focal],
                   "approved": None, "seconds": seconds, "size": list(img.size)})
        c.log(by, "master.generated", f"{c.product(pid)['name']} (attempt {attempt}, {provider.label}, {seconds}s"
                                      f"{', own wording' if edited else ''})")
        c._stale_frames(pid)
        c.save()
        return ps


def suggest_audience(cid: str, draft: dict) -> dict:
    """A first draft of "Who it's for", from the brief as it is on screen right now."""
    with _lock:
        c = Campaign(cid)
        brief = dict(c.brief)
        # The form autosaves after a pause, so use what's typed if the browser sent it.
        if isinstance(draft.get("message"), str):
            brief["message"] = draft["message"]
        for key in ("products", "markets"):
            if isinstance(draft.get(key), list):
                brief[key] = draft[key]
        provider = providers.get_text(c.state["text_provider"])
    return {"text": provider.suggest_audience(brief), "demo": provider.id == "mock"}


def describe_photo(cid: str, pid: str, name: str = "") -> dict:
    """A product description read from its photo, for the person to check and keep."""
    with _lock:
        c = Campaign(cid)
        p = c.product(pid)
        if not p.get("photo"):
            raise StudioError("Add a photo of the product first.")
        img = Image.open(c.dir / p["photo"]).convert("RGB")
        provider = providers.get_text(c.state["text_provider"])
        brief = c.brief
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return {"text": provider.describe_photo(buf.getvalue(), name or p.get("name", ""), brief)}


# The quick picks on the Message step, written as the instruction the translator gets.
REVISE_PRESETS = {
    "closer": "Stay closer to the original: keep every idea it has, and only rephrase where "
              "a word-for-word version would sound wrong.",
    "shorter": "Make it shorter, so it reads bigger on the ad. Keep the meaning.",
}


def revise_translation(cid: str, lang: str, instruction: str, by: str | None = None) -> dict:
    """Rewrite one language's line from a change asked for in English, so a reviewer
    who can't read the language can still fix it."""
    asked = instruction.strip()[:300]
    if not asked:
        raise StudioError("Say what should be different.")
    with _lock:
        c = Campaign(cid)
        src = brief_mod.source_language(c.brief)
        if lang == src or lang not in brief_mod.languages(c.brief) or lang not in c.state["copy"]:
            raise StudioError("That language isn't a translation in this campaign.")
        message = c.brief.get("message", "").strip()
        current = c.state["copy"][lang]["text"]
        provider = providers.get_text(c.state["text_provider"])
        brief = c.brief
    res = provider.translate(message, src, lang, brief, instruction=REVISE_PRESETS.get(asked, asked), current=current)
    label = {"closer": "Closer to the original", "shorter": "Shorter"}.get(asked, asked)
    with _lock:
        c = Campaign(cid)
        c.state["copy"][lang] = {**res, "origin": "machine", "asked": label, "provider": provider.id,
                                 "model": provider.text_model, "approved": None}
        c.log(by, "copy.revised", f"{lang}: {label}")
        c._stale_frames()
        c.save()
        return c.state["copy"][lang]


def translate_all(cid: str, by: str | None = None, force: bool = False) -> dict:
    with _lock:
        c = Campaign(cid)
        src = brief_mod.source_language(c.brief)
        message = c.brief.get("message", "").strip()
        if not message:
            raise StudioError("Add the campaign message first.")
        provider = providers.get_text(c.state["text_provider"])
        todo = [lang for lang in brief_mod.languages(c.brief)
                if lang != src and (force or lang not in c.state["copy"])]
        if src not in c.state["copy"] or force:
            c.state["copy"][src] = {"text": message, "back_translation": "", "note": "",
                                    "origin": "source", "approved": None}
        c.save()
        brief = c.brief
    results = {lang: provider.translate(message, src, lang, brief) for lang in todo}
    with _lock:
        c = Campaign(cid)
        for lang, res in results.items():
            c.state["copy"][lang] = {**res, "origin": "machine", "provider": provider.id,
                                     "model": provider.text_model, "approved": None}
            c.log(by, "copy.translated", f"{lang} via {provider.label}")
        c._stale_frames()
        c.save()
        return c.state["copy"]
