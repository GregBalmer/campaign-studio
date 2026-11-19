import { useEffect, useRef, useState } from "react";
import { Camera, Check, ChevronRight, Loader2, RefreshCw, Sparkles, Undo2 } from "lucide-react";
import { api, masterUrl, type Check as CheckT, type View } from "../api";
import { Button, ErrorNote, NextPanel, StatusBadge, timeAgo, useApp, useDebounced } from "../ui";

export default function KeyVisualStep() {
  const { view, goTo } = useApp();
  const products = view.brief.products;
  const approvedCount = products.filter((p) => view.products[p.id]?.approved).length;
  const allApproved = approvedCount === products.length;

  // The Message step translates whatever's missing as soon as it opens.
  const toMessage = () => goTo(2);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approve the key visual</h1>
          <p>One image per product. Fit the box around the product: every size is cropped around it, and the message is kept clear of it.</p>
        </div>
      </div>

      {/* One row per product, so nothing swaps as you work and five products scroll like two.
          The right-hand column holds only the next step, as on every step. */}
      <div className="grid-2">
        <div className="stack kv-rows">
          {products.map((p) => <ProductRow key={p.id} pid={p.id} />)}
        </div>

        <aside className="sticky">
          <NextPanel label="Key visuals" figure={`${approvedCount} of ${products.length} approved`}
            detail={allApproved ? "Every product has its key visual." : "Approve one for each product to continue."}>
            <Button kind="primary" size="lg" className="btn-block" disabled={!allApproved} onClick={toMessage}>Continue to the message</Button>
          </NextPanel>
        </aside>
      </div>
    </>
  );
}

/** One product: its key visual on the left, everything you do to it on the right. */
function ProductRow({ pid }: { pid: string }) {
  const { view, run, busy, reviewer, errors } = useApp();
  const products = view.brief.products;
  const product = products.find((p) => p.id === pid)!;
  const ps = view.products[pid] ?? {};
  const generating = busy.has(`master-${pid}`);
  const row = useRef<HTMLElement>(null);
  const [editing, setEditing] = useState(false);
  const [prompt, setPrompt] = useState(ps.prompt ?? "");
  useEffect(() => { if (!editing) setPrompt(ps.prompt ?? ""); }, [ps.prompt, editing]);

  const make = async (custom?: string, fromBrief = false) => {
    const by = await reviewer();
    setEditing(false);
    await run(`master-${pid}`, () => api.makeMaster(view.id, pid, by, custom, fromBrief));
  };
  const approve = async () => {
    const by = await reviewer();
    const ok = await run(`approve-${pid}`, () => api.approveMaster(view.id, pid, by));
    // Bring the next product that still needs a decision into view.
    const next = products.find((p) => p.id !== pid && !view.products[p.id]?.approved);
    if (ok && next) document.getElementById(`kv-${next.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const switchSource = async (generate: boolean) => {
    const by = await reviewer();
    await run(`master-${pid}`, async () => {
      await api.setSource(view.id, pid, generate);
      return api.makeMaster(view.id, pid, by);
    });
  };

  const generatedBy = ps.origin === "supplied" ? "Your photo"
    : ps.provider === "openai" ? `Created by OpenAI${ps.seconds ? ` in ${Math.round(ps.seconds)}s` : ""}`
    : ps.provider === "firefly" ? `Created by Adobe Firefly${ps.seconds ? ` in ${Math.round(ps.seconds)}s` : ""}`
    : ps.provider === "firefly-test" ? "Created by the Firefly test server"
    : ps.provider === "mock" ? "Demo image (drawn locally)" : "";

  return (
    <section className="card card-pad kv-row" id={`kv-${pid}`} ref={row}>
      {/* The product's name and where its image came from head the whole row. */}
      <div className="kv-head">
        <h3>{product.name || "Untitled product"}</h3>
        <span className="muted small">{generatedBy || "No key visual yet"}{ps.prompt_edited && ps.origin === "generated" ? ", from your wording" : ""}</span>
        <span className="space" />
        {generating ? <StatusBadge status="neutral">Creating…</StatusBadge>
          : errors[`master-${pid}`] ? <StatusBadge status="fail">Didn't work</StatusBadge>
          : ps.approved ? <span title={`Approved by ${ps.approved.by}, ${timeAgo(ps.approved.at)}`}><StatusBadge status="pass"><Check size={12} strokeWidth={3} /> Approved</StatusBadge></span>
          : ps.master ? <StatusBadge status="warn">Needs approval</StatusBadge> : null}
      </div>

      <FocalStage view={view} pid={pid} generating={generating} onCreate={() => make()} />

      <div className="kv-side">
        <div className="stack">
          <ErrorNote k={`master-${pid}`} />
          {ps.approved ? (
            <>
              {/* The badge in the row's header already says Approved; who and when is on hover. */}
              <Button kind="ghost" className="kv-reopen" icon={<Undo2 size={16} />} onClick={async () => { const by = await reviewer(); run("reopen", () => api.reopenMaster(view.id, pid, by)); }}>
                Reopen to make changes
              </Button>
            </>
          ) : (
            <>
              <Button kind="approve" size="lg" className="btn-block" disabled={!ps.master || generating}
                busy={busy.has(`approve-${pid}`)} icon={<Check size={18} strokeWidth={2.6} />} onClick={approve}>
                Approve key visual
              </Button>
              <div className="row">
                {ps.origin !== "supplied" && (
                  <Button className="btn-block" disabled={generating} icon={<RefreshCw size={16} />} onClick={() => make()}>
                    {ps.master ? "Try another" : "Create one"}
                  </Button>
                )}
                {product.photo && ps.origin === "generated" && (
                  <Button className="btn-block" disabled={generating} icon={<Camera size={16} />} onClick={() => switchSource(false)}>Use my photo</Button>
                )}
                {product.photo && ps.origin === "supplied" && (
                  <Button className="btn-block" disabled={generating} icon={<Sparkles size={16} />} onClick={() => switchSource(true)}>Create one instead</Button>
                )}
              </div>
            </>
          )}
        </div>

        {ps.master && !generating && <div style={{ marginTop: ps.approved ? 12 : 20 }}><MiniPreviews view={view} pid={pid} /></div>}
      </div>

      {/* Long text, so it gets the row's full width rather than the narrow side column. */}

        {ps.prompt && ps.origin === "generated" && (
          <details className="details kv-prompt" open={editing || undefined}>
            <summary><ChevronRight size={14} /> What we asked the generator for</summary>
            {editing ? (
              <div className="prompt-edit">
                <textarea className="textarea" rows={8} value={prompt} onChange={(e) => setPrompt(e.target.value)} aria-label="What to ask the generator for" autoFocus />
                <div className="row">
                  <Button kind="primary" size="sm" icon={<Sparkles size={14} />} disabled={!prompt.trim() || generating} onClick={() => make(prompt.trim())}>Create with this</Button>
                  <Button kind="ghost" size="sm" onClick={() => { setEditing(false); setPrompt(ps.prompt ?? ""); }}>Cancel</Button>
                </div>
              </div>
            ) : (
              <>
                <p>{ps.prompt}</p>
                {!ps.approved && (
                  <span className="prompt-links">
                    <button className="link" onClick={() => setEditing(true)}>Change the wording and try again</button>
                    {ps.prompt_edited && <button className="link" disabled={generating} onClick={() => make(undefined, true)}>Go back to the brief's wording</button>}
                  </span>
                )}
              </>
            )}
          </details>
        )}
    </section>
  );
}

/** The master with a movable, resizable product box and outlines of where each
 *  size will crop. The box tells layout and checks where the product is. */
function FocalStage({ view, pid, generating, onCreate }: { view: View; pid: string; generating: boolean; onCreate: () => void }) {
  const { run, busy } = useApp();
  const ps = view.products[pid] ?? {};
  const url = masterUrl(view, pid);
  const ref = useRef<HTMLDivElement>(null);
  const [focal, setFocal] = useState<[number, number]>(ps.focal ?? [0.5, 0.5]);
  const [zone, setZone] = useState<[number, number]>(ps.zone ?? [0.08, 0.2]);
  const [mode, setMode] = useState<null | { kind: "move" | "resize"; dx: number; dy: number }>(null);
  const [guides, setGuides] = useState(true);
  const [shown, setShown] = useState("");
  const locked = !!ps.approved;
  const src = `${url}?v=${ps.attempt ?? 0}&w=1200`;

  useEffect(() => {
    setFocal(ps.focal ?? [0.5, 0.5]);
    setZone(ps.zone ?? [0.08, 0.2]);
  }, [pid, ps.master, ps.focal?.[0], ps.focal?.[1], ps.zone?.[0], ps.zone?.[1]]); // eslint-disable-line react-hooks/exhaustive-deps

  const point = (e: React.PointerEvent): [number, number] => {
    const r = ref.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

  if (generating) {
    return (
      <div className="stage">
        <div className="generating">
          <Sparkles size={26} />
          <strong>Creating the key visual…</strong>
          <span className="small">{view.providers.image === "openai" ? "Usually 15 to 40 seconds."
            : view.providers.image.startsWith("firefly") ? "This can take up to a minute." : "Just a moment."} You can work on another product meanwhile.</span>
        </div>
      </div>
    );
  }
  if (!url) {
    return (
      <div className="stage">
        <div className="generating" style={{ animation: "none" }}>
          <strong>No key visual yet</strong>
          <Button kind="primary" icon={<Sparkles size={16} />} onClick={onCreate} busy={busy.has(`master-${pid}`)}>Create key visual</Button>
        </div>
      </div>
    );
  }

  const [mw, mh] = ps.size ?? [1, 1];
  const crops = Object.entries(view.formats).map(([k, f]) => {
    const r = f.size[0] / f.size[1];
    let cw = mw, ch = mh;
    if (mw / mh > r) cw = mh * r; else ch = mw / r;
    const x0 = Math.min(Math.max(focal[0] * mw - cw / 2, 0), mw - cw);
    const y0 = Math.min(Math.max(focal[1] * mh - ch / 2, 0), mh - ch);
    return { k, label: `${f.label} ${f.ratio}`, x: x0 / mw, y: y0 / mh, w: cw / mw, h: ch / mh };
  }).filter((c) => c.w < 0.999 || c.h < 0.999);

  const box = { l: focal[0] - zone[0], t: focal[1] - zone[1], w: zone[0] * 2, h: zone[1] * 2 };

  const down = (e: React.PointerEvent) => {
    if (locked) return;
    ref.current!.setPointerCapture(e.pointerId);
    const p = point(e);
    if ((e.target as HTMLElement).dataset.handle) {
      setMode({ kind: "resize", dx: 0, dy: 0 });
    } else if (Math.abs(p[0] - focal[0]) <= zone[0] && Math.abs(p[1] - focal[1]) <= zone[1]) {
      setMode({ kind: "move", dx: p[0] - focal[0], dy: p[1] - focal[1] });
    } else {
      setFocal(p);
      setMode({ kind: "move", dx: 0, dy: 0 });
    }
  };
  const move = (e: React.PointerEvent) => {
    if (!mode) return;
    const p = point(e);
    if (mode.kind === "move") setFocal([clamp(p[0] - mode.dx, 0, 1), clamp(p[1] - mode.dy, 0, 1)]);
    else setZone([clamp(Math.abs(p[0] - focal[0]), 0.02, 0.5), clamp(Math.abs(p[1] - focal[1]), 0.02, 0.5)]);
  };
  const up = () => {
    if (!mode) return;
    setMode(null);
    run(`focal-${pid}`, () => api.setFocal(view.id, pid, focal[0], focal[1], zone[0], zone[1]));
  };

  return (
    <div ref={ref} className={`stage ${locked ? "" : "can-drag"}`} onPointerDown={down} onPointerMove={move} onPointerUp={up}>
      <img src={src} alt="Key visual" draggable={false} onLoad={() => setShown(src)} className={shown === src ? "" : "loading"} />
      {shown !== src && <div className="stage-loading"><Loader2 size={22} className="spin" /></div>}
      {guides && crops.map((c) => (
        <div key={c.k} className="crop-guide" style={{ left: `${c.x * 100}%`, top: `${c.y * 100}%`, width: `${c.w * 100}%`, height: `${c.h * 100}%` }}>
          <span>{c.label}</span>
        </div>
      ))}
      <div className={`product-box ${mode ? "active" : ""} ${locked ? "locked" : ""}`}
        style={{ left: `${box.l * 100}%`, top: `${box.t * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }}>
        <span className="product-box-label">Product</span>
        {!locked && <span className="product-box-handle" data-handle="1" aria-label="Resize product box" />}
      </div>
      {!locked && !mode && (
        <div className="focal-label" style={{ left: `${focal[0] * 100}%`, top: `${(focal[1] + zone[1]) * 100}%` }}>
          Drag to the product · corner to fit
        </div>
      )}
      <div className="stage-toolbar" onPointerDown={(e) => e.stopPropagation()}>
        <button className={guides ? "on" : ""} aria-pressed={guides} onClick={() => setGuides(!guides)}>{guides ? "Hide crops" : "Show crops"}</button>
      </div>
    </div>
  );
}

function MiniPreviews({ view, pid }: { view: View; pid: string }) {
  const ps = view.products[pid];
  const lang = view.brief.message_language;
  const key = useDebounced(`${pid}|${ps?.focal?.join(",")}|${ps?.zone?.join(",")}|${ps?.master}|${view.brief.message}`, 250);
  const [imgs, setImgs] = useState<Record<string, { image: string; checks: CheckT[] }>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all(Object.keys(view.formats).map((f) => api.preview(view.id, pid, f, lang, undefined, 360).then((r) => [f, r] as const)))
      .then((all) => { if (live) { setImgs(Object.fromEntries(all)); setLoading(false); } })
      .catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <div className="label" style={{ marginBottom: 8 }}>How it lands in each size <span className="muted">{loading ? "Updating…" : "Live"}</span></div>
      <div className="mini-previews">
        {Object.entries(view.formats).map(([k, f]) => {
          const r = imgs[k];
          const worst = r?.checks.some((c) => c.status === "fail") ? "fail" : r?.checks.some((c) => c.status === "warn") ? "warn" : "pass";
          return (
            <div className="mini" key={k}>
              <div className="mini-img" style={{ aspectRatio: `${f.size[0]} / ${f.size[1]}`, opacity: loading ? 0.6 : 1 }}>
                {r && <img src={r.image} alt={`${f.label} preview`} />}
              </div>
              <div className="mini-label">
                <span title={f.ratio}>{f.label}</span>
                {r && worst !== "pass" && <span style={{ color: worst === "fail" ? "var(--fail)" : "var(--warn)", fontWeight: 650 }}>{worst === "fail" ? "Fix" : "Check"}</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
