import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Check, CheckCheck, Download, FolderOpen, Loader2, X } from "lucide-react";
import { api, frameUrl, LANGUAGE_NAMES, type Frame } from "../api";
import { Button, CheckIconDot, ErrorNote, Markers, StatusBadge, timeAgo, useApp, useEscape } from "../ui";

type Filter = "all" | "open" | "approved" | "rejected";
const FORMAT_ORDER = ["1x1", "9x16", "16x9"];

export default function ReviewStep() {
  const { view, run, busy, reviewer } = useApp();
  const [filter, setFilter] = useState<Filter>("all");
  const [openKey, setOpenKey] = useState<string | null>(null);
  const building = busy.has("fanout");

  const entries = useMemo(() => {
    const regions = view.brief.markets.map((m) => m.region);
    return Object.entries(view.frames).sort(([, a], [, b]) =>
      FORMAT_ORDER.indexOf(a.format) - FORMAT_ORDER.indexOf(b.format) || regions.indexOf(a.region) - regions.indexOf(b.region));
  }, [view.frames, view.brief.markets]);

  const stale = entries.length === 0 || entries.some(([, f]) => f.stale);
  // Build (or rebuild only what changed) as soon as this screen opens.
  useEffect(() => {
    if (stale && !building) {
      reviewer().then((by) => run("fanout", () => api.fanOut(view.id, by)));
    }
  }, [stale]); // eslint-disable-line react-hooks/exhaustive-deps

  const counts = {
    total: entries.length,
    approved: entries.filter(([, f]) => f.decision?.value === "approved").length,
    rejected: entries.filter(([, f]) => f.decision?.value === "rejected").length,
  };
  const open = counts.total - counts.approved - counts.rejected;
  const flaggedOpen = entries.filter(([, f]) => !f.decision && f.status !== "pass").length;
  const passingOpen = entries.filter(([, f]) => !f.decision && f.status === "pass");

  const shown = entries.filter(([, f]) =>
    filter === "all" ? true
    : filter === "open" ? !f.decision
    : f.decision?.value === filter);

  const approveAllPassing = async () => {
    const by = await reviewer();
    await run("bulk", async () => {
      let v = view;
      for (const [k] of passingOpen) v = await api.decide(view.id, k, "approved", by);
      return v;
    });
  };

  if (building && entries.length === 0) {
    return (
      <div className="empty" style={{ marginTop: 40 }}>
        <Loader2 size={28} className="spin" />
        <h2 style={{ margin: "14px 0 6px", color: "var(--ink)" }}>Building {view.brief.products.length * 3 * view.brief.markets.length} ads…</h2>
        <p style={{ margin: 0 }}>Cropping each key visual, setting the message in every language and running the checks.</p>
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review and export</h1>
          <p>Every size in every market. Anything a check flagged is marked on the ad itself. Click an ad to look closer.</p>
        </div>
        <div className="row">
          <a className="btn btn-secondary" href={`/api/campaigns/${view.id}/download`} aria-disabled={!view.has_outputs}>
            <Download size={16} /> All ads
          </a>
          <a className={`btn btn-primary ${counts.approved ? "" : "disabled"}`} href={counts.approved ? `/api/campaigns/${view.id}/download?only=approved` : undefined}
            style={counts.approved ? undefined : { opacity: 0.45, pointerEvents: "none" }}>
            <Download size={16} /> Approved ({counts.approved})
          </a>
        </div>
      </div>

      <div className="review-bar">
        {([
          ["all", counts.total, counts.total === 1 ? "ad" : "ads", undefined, "Show every ad"],
          ["open", open, "to review", undefined, "Show ads nobody has approved or rejected yet"],
          ["approved", counts.approved, "approved", counts.approved ? "var(--ok)" : undefined, "Show approved ads"],
          ["rejected", counts.rejected, "rejected", counts.rejected ? "var(--fail)" : undefined, "Show rejected ads"],
        ] as const).map(([k, n, label, color, title]) => (
          <button key={k} className={`stat ${filter === k ? "on" : ""}`} aria-pressed={filter === k}
            onClick={() => setFilter(filter === k ? "all" : k)} title={title}>
            <b style={{ color }}>{n}</b>
            <span>{label}{k === "open" && flaggedOpen > 0 && <em className="stat-flag"> · {flaggedOpen} flagged</em>}</span>
          </button>
        ))}
        <span className="space" />
        {building && <span className="row muted small"><Loader2 size={15} className="spin" /> Updating…</span>}
        {passingOpen.length > 0 ? (
          <Button kind="approve" icon={<CheckCheck size={17} />} busy={busy.has("bulk")} onClick={approveAllPassing}>
            Approve all that pass ({passingOpen.length})
          </Button>
        ) : counts.total > 0 && !building && (
          <span className="row muted small"><CheckCheck size={16} /> {open ? "Every passing ad is approved" : "Every ad has a decision"}</span>
        )}
      </div>
      <div style={{ marginBottom: 16 }}><ErrorNote k="fanout" action="Build again" /></div>

      {view.brief.products.map((p) => {
        const items = shown.filter(([, f]) => f.product === p.id);
        if (!items.length) return null;
        return (
          <section className="product-section" key={p.id}>
            <h2>{p.name}</h2>
            {view.brief.markets.map((m) => {
              const row = items.filter(([, f]) => f.region === m.region);
              if (!row.length) return null;
              return (
                <div className="sheet-row" key={m.region}>
                  <div className="sheet-row-label">
                    <b>{m.name}</b>
                    <span className="muted">{LANGUAGE_NAMES[m.language]}</span>
                  </div>
                  <div className="sheet">
                    {row.map(([k, f]) => <Tile key={k} f={f} onOpen={() => setOpenKey(k)} />)}
                  </div>
                </div>
              );
            })}
          </section>
        );
      })}
      {shown.length === 0 && (
        <div className="empty">
          {{ all: "No ads yet.", open: "Nothing left to review. Every ad has a decision.",
             approved: "No ads approved yet.", rejected: "No ads rejected." }[filter]}
          {filter !== "all" && <><br /><button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }} onClick={() => setFilter("all")}>Show all ads</button></>}
        </div>
      )}

      <p className="muted small" style={{ marginTop: 40, display: "flex", gap: 8, alignItems: "center" }}>
        <FolderOpen size={15} /> Also saved on this computer in <code>outputs/{view.id}/</code>, by product and size, with <code>report.json</code>.
      </p>

      {openKey && view.frames[openKey] && (
        <Lightbox
          keys={shown.map(([k]) => k)}
          current={openKey}
          onMove={setOpenKey}
          onClose={() => setOpenKey(null)}
        />
      )}
    </>
  );
}

function Tile({ f, onOpen }: { f: Frame; onOpen: () => void }) {
  const { view } = useApp();
  const spec = view.formats[f.format];
  const h = 200;
  const w = Math.round((h * spec.size[0]) / spec.size[1]);
  const market = view.brief.markets.find((m) => m.region === f.region);
  const decided = f.decision?.value;
  return (
    <button className="tile" onClick={onOpen} style={{ width: w }}>
      <div className={`tile-img ${decided ? `decided-${decided}` : ""}`} style={{ width: w, height: h }}>
        <img src={`${frameUrl(view, f)}&w=640`} alt={`${spec.label}, ${market?.name}`} loading="lazy" />
        {!decided && <Markers checks={f.checks} />}
        <span className="tile-status">
          {decided === "approved" ? <StatusBadge status="pass"><Check size={12} strokeWidth={3} /> Approved</StatusBadge>
            : decided === "rejected" ? <StatusBadge status="fail">Rejected</StatusBadge>
            : f.status === "fail" ? <StatusBadge status="fail">Fix needed</StatusBadge>
            : f.status === "warn" ? <StatusBadge status="warn">Check</StatusBadge> : null}
        </span>
      </div>
      <span className="tile-meta">
        <span>{spec.label}</span>
        <span className="muted">{spec.ratio} · {spec.size[0]}×{spec.size[1]}</span>
      </span>
    </button>
  );
}

function Lightbox({ keys, current, onMove, onClose }: { keys: string[]; current: string; onMove: (k: string) => void; onClose: () => void }) {
  const { view, run, busy, reviewer, goTo } = useApp();
  const f = view.frames[current];
  const spec = view.formats[f.format];
  const product = view.brief.products.find((p) => p.id === f.product)!;
  const market = view.brief.markets.find((m) => m.region === f.region);
  const idx = keys.indexOf(current);
  const [note, setNote] = useState("");
  const flagged = f.checks.filter((c) => c.status !== "pass");
  const ordered = [...flagged, ...f.checks.filter((c) => c.status === "pass")];
  const numbered = flagged.filter((c) => c.box);

  const move = useCallback((d: number) => {
    const n = keys[(idx + d + keys.length) % keys.length];
    if (n) { onMove(n); setNote(""); }
  }, [idx, keys, onMove]);

  const decide = async (decision: "approved" | "rejected" | null) => {
    const by = await reviewer();
    const ok = await run("decide", () => api.decide(view.id, current, decision, by, note));
    if (ok && decision && idx < keys.length - 1) move(1);
  };

  useEscape(onClose);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowRight") move(1);
      if (e.key === "ArrowLeft") move(-1);
      if (e.key.toLowerCase() === "a" && f.status !== "fail") decide("approved");
      if (e.key.toLowerCase() === "r") decide("rejected");
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const fixMaster = f.checks.some((c) => c.status !== "pass" && ["clear", "whole", "readable", "sharp"].includes(c.id));
  const fixWords = f.checks.some((c) => c.status !== "pass" && ["words", "fits"].includes(c.id));

  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lightbox-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="lightbox-stage">
          <div className="frame">
            <img src={`${frameUrl(view, f)}&w=1600`} alt="" />
            <Markers checks={f.checks} />
          </div>
        </div>
        <div className="lightbox-side" style={{ position: "relative" }}>
          <button className="btn btn-ghost icon-btn close-x" onClick={onClose} aria-label="Close"><X size={18} /></button>
          <div>
            <div className="muted small" style={{ fontWeight: 600 }}>{idx + 1} of {keys.length}</div>
            <h2 style={{ margin: "4px 0 2px", fontSize: 20, letterSpacing: "-0.02em" }}>{product.name}</h2>
            <div className="muted">{spec.label} · {spec.ratio} · {market?.name} ({LANGUAGE_NAMES[f.language]})</div>
          </div>

          <ul className="check-list">
            {ordered.map((c) => {
              const n = numbered.indexOf(c);
              return (
                <li className="check-item" key={c.id}>
                  <CheckIconDot status={c.status} />
                  <div>
                    <div className="ci-label">{n >= 0 && <span className="badge" style={{ height: 18, marginRight: 6 }}>{n + 1}</span>}{c.label}</div>
                    <div className="ci-msg">{c.message}</div>
                  </div>
                </li>
              );
            })}
          </ul>

          {(fixMaster || fixWords) && (
            <div className="row" style={{ flexWrap: "wrap" }}>
              {fixMaster && <Button size="sm" onClick={async () => { const by = await reviewer(); await run("reopen", () => api.reopenMaster(view.id, f.product, by)); goTo(1); }}>Adjust the key visual</Button>}
              {fixWords && <Button size="sm" onClick={async () => { const by = await reviewer(); await run("reopen", () => api.reopenCopy(view.id, f.language, by)); goTo(2); }}>Edit the {LANGUAGE_NAMES[f.language]} message</Button>}
            </div>
          )}

          <div className="space" />

          {f.decision ? (
            <div className={f.decision.value === "approved" ? "approved-stamp" : "problems"} style={{ margin: 0 }}>
              {f.decision.value === "approved" ? <Check size={18} strokeWidth={3} /> : <X size={18} />}
              <span>
                {f.decision.value === "approved" ? "Approved" : "Rejected"} by {f.decision.by} · {timeAgo(f.decision.at)}
                {f.decision.note && <><br /><span style={{ fontWeight: 450 }}>“{f.decision.note}”</span></>}
              </span>
            </div>
          ) : (
            <input className="input" placeholder="Add a note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          )}
          <div className="row">
            {f.decision ? (
              <Button className="btn-block" onClick={() => decide(null)} busy={busy.has("decide")}>Change decision</Button>
            ) : (
              <>
                <Button kind="danger" className="btn-block" icon={<X size={16} />} title="Reject (R)" onClick={() => decide("rejected")} busy={busy.has("decide")}>Reject <kbd>R</kbd></Button>
                <Button kind="approve" className="btn-block" icon={<Check size={16} strokeWidth={2.6} />} disabled={f.status === "fail"}
                  title={f.status === "fail" ? "Fix the failed check first" : "Approve (A)"} onClick={() => decide("approved")} busy={busy.has("decide")}>Approve <kbd>A</kbd></Button>
              </>
            )}
          </div>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <Button kind="ghost" size="sm" icon={<ArrowLeft size={15} />} onClick={() => move(-1)} title="Previous ad (←)">Previous</Button>
            <Button kind="ghost" size="sm" onClick={() => move(1)} title="Next ad (→)">Next <ArrowRight size={15} /></Button>
          </div>
        </div>
      </div>
    </div>
  );
}
