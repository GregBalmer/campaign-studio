import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, History, Plus, RotateCcw, Settings2, UserRound, X } from "lucide-react";
import { api, ApiError, type CampaignSummary, type ProviderInfo, type View } from "./api";
import { AppCtx, Button, Drawer, Modal, clock, useDismiss, type Ctx } from "./ui";
import BriefStep from "./steps/BriefStep";
import KeyVisualStep from "./steps/KeyVisualStep";
import MessageStep from "./steps/MessageStep";
import ReviewStep from "./steps/ReviewStep";
import SettingsDrawer from "./SettingsDrawer";

const STEPS = [
  { title: "Brief", sub: "Products, markets, message" },
  { title: "Key visual", sub: "Approve one image per product" },
  { title: "Message", sub: "Approve every language" },
  { title: "Review & export", sub: "Every size, every market" },
];

const stageStep = { setup: 0, master: 1, words: 2, review: 3 } as const;
// Each step has its own address, so a refresh or a shared link keeps your place.
const HASHES = ["brief", "key-visual", "message", "review"];

function store(key: string, value?: string): string | null {
  try {
    if (value !== undefined) localStorage.setItem(key, value);
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export default function App() {
  const [view, setView] = useState<View | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [toastMsg, setToast] = useState<{ msg: string; kind: "info" | "error" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reviewerName, setReviewerName] = useState(store("studio.reviewer") || "");
  const [askName, setAskName] = useState<((n: string) => void) | null>(null);
  const [panel, setPanel] = useState<"settings" | "history" | "campaigns" | null>(null);
  const toastTimer = useRef<number>();
  const switcher = useRef<HTMLDivElement>(null);
  useDismiss(switcher, panel === "campaigns", () => setPanel(null));

  const toast = useCallback((msg: string, kind: "info" | "error" = "info") => {
    setToast({ msg, kind });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), kind === "error" ? 9000 : 3500);
  }, []);

  const open = useCallback(async (id: string, jump = true) => {
    const v = await api.get(id);
    setView(v);
    store("studio.campaign", id);
    if (jump) {
      const asked = HASHES.indexOf(window.location.hash.slice(1));
      setStep(asked >= 0 && asked <= stageStep[v.stage] ? asked : stageStep[v.stage]);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [list, status] = await Promise.all([api.campaigns(), api.status()]);
        setCampaigns(list);
        setProviders(status.providers);
        const last = store("studio.campaign");
        const id = list.find((c) => c.id === last)?.id ?? list.find((c) => c.sample)?.id ?? list[0]?.id;
        if (id) await open(id);
      } catch (e) {
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [open]);

  const loaded = view !== null;
  useEffect(() => {
    if (loaded) history.replaceState(null, "", `#${HASHES[step]}`);
  }, [step, loaded]);

  const run = useCallback<Ctx["run"]>(async (key, fn) => {
    setBusy((b) => new Set(b).add(key));
    try {
      const v = await fn();
      if (v) setView(v);
      return true;
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Something went wrong. Try again.", "error");
      return false;
    } finally {
      setBusy((b) => {
        const n = new Set(b);
        n.delete(key);
        return n;
      });
    }
  }, [toast]);

  const reviewer = useCallback(() => {
    if (reviewerName) return Promise.resolve(reviewerName);
    return new Promise<string>((resolve) => setAskName(() => resolve));
  }, [reviewerName]);

  const refreshCampaigns = async () => setCampaigns(await api.campaigns());

  if (loadError) {
    return <div className="empty"><h2>Campaign Studio isn't responding</h2><p>{loadError}</p></div>;
  }
  if (!view) return <div className="empty">Opening Campaign Studio…</div>;

  const allMasters = view.brief.products.every((p) => view.products[p.id]?.approved);
  const allCopy = view.languages.every((l) => view.copy[l]?.approved);
  const unlocked = [true, view.problems.length === 0, allMasters, allMasters && allCopy];
  const done = [
    view.problems.length === 0 && view.stage !== "setup",
    allMasters,
    allMasters && allCopy,
    Object.values(view.frames).length > 0 && Object.values(view.frames).every((f) => f.decision),
  ];
  const provider = providers.find((p) => p.id === view.provider);

  const ctx: Ctx = {
    view, setView, run, busy, reviewer, reviewerName, toast,
    goTo: (s) => { setStep(s); window.scrollTo({ top: 0, behavior: "smooth" }); },
  };

  return (
    <AppCtx.Provider value={ctx}>
      <header className="topbar">
        <div className="wordmark">
          <span className="wordmark-mark">
            <svg width="16" height="16" viewBox="0 0 32 32"><path d="M4 20a12 12 0 0 1 24 0z" fill="#FF7A59" /><rect x="4" y="23" width="24" height="3" fill="#FF7A59" /></svg>
          </span>
          Campaign Studio
        </div>
        <span className="divider-v" />
        <div style={{ position: "relative" }} ref={switcher}>
          <button className="campaign-switch" aria-expanded={panel === "campaigns"} onClick={() => setPanel(panel === "campaigns" ? null : "campaigns")}>
            {view.brief.campaign || "Untitled campaign"}
            {view.sample && <span className="badge">Sample</span>}
            <ChevronDown size={16} className="muted" />
          </button>
          {panel === "campaigns" && (
            <CampaignMenu
              campaigns={campaigns}
              current={view.id}
              sample={view.sample}
              onPick={async (id) => { setPanel(null); await run("open", async () => { await open(id); }); }}
              onNew={async (name) => {
                setPanel(null);
                await run("new", async () => { const v = await api.createCampaign(name); await refreshCampaigns(); setStep(0); return v; });
              }}
              onReset={async () => {
                setPanel(null);
                await run("reset", async () => { const v = await api.reset(view.id); setStep(0); toast("Sample reset to the start."); return v; });
              }}
              onClose={() => setPanel(null)}
            />
          )}
        </div>
        <div className="spacer" />
        <button className="chip-button" onClick={() => setPanel("settings")} title="Image generator">
          <span className={`dot ${view.provider === "openai" ? "ok" : "demo"}`} />
          {provider?.label ?? view.provider}
          <Settings2 size={15} />
        </button>
        <button className="chip-button" onClick={() => setPanel("history")} title="Approval history">
          <History size={15} /> History
        </button>
        <button className="chip-button" onClick={() => setAskName(() => () => {})} title="Change reviewer">
          <UserRound size={15} /> {reviewerName || "Add your name"}
        </button>
      </header>

      <nav className="stepper" aria-label="Steps">
        {STEPS.map((s, i) => (
          <button
            key={s.title}
            className={`step ${step === i ? "current" : ""} ${done[i] && step !== i ? "done" : ""}`}
            disabled={!unlocked[i]}
            onClick={() => ctx.goTo(i)}
            aria-current={step === i ? "step" : undefined}
          >
            <span className="step-num">{done[i] && step !== i ? <Check size={15} strokeWidth={3} /> : i + 1}</span>
            <span className="step-text">
              <span className="step-title">{s.title}</span>
              <span className="step-sub">{s.sub}</span>
            </span>
          </button>
        ))}
      </nav>

      <main className="page">
        {step === 0 && <BriefStep />}
        {step === 1 && <KeyVisualStep />}
        {step === 2 && <MessageStep />}
        {step === 3 && <ReviewStep />}
      </main>

      {panel === "settings" && (
        <SettingsDrawer providers={providers} setProviders={setProviders} onClose={() => setPanel(null)} />
      )}
      {panel === "history" && (
        <Drawer onClose={() => setPanel(null)}>
          <h2>History</h2>
          <p className="muted small" style={{ marginTop: 0 }}>Who did what. The full record is saved in report.json.</p>
          {view.log.length === 0 && <p className="muted">Nothing yet.</p>}
          {[...view.log].reverse().map((l, i) => (
            <div className="history-item" key={i}>
              <span className="when">{clock(l.at)}</span>
              <span><b>{l.by}</b> {describe(l.event)} <span className="muted">{l.detail}</span></span>
            </div>
          ))}
        </Drawer>
      )}
      {askName && (
        <NameModal
          initial={reviewerName}
          onSave={(n) => { store("studio.reviewer", n); setReviewerName(n); askName(n); setAskName(null); }}
          onClose={() => setAskName(null)}
        />
      )}
      {toastMsg && (
        <div className={`toast ${toastMsg.kind}`} role="status">
          <span style={{ flex: 1 }}>{toastMsg.msg}</span>
          <button onClick={() => setToast(null)} aria-label="Dismiss"><X size={16} /></button>
        </div>
      )}
    </AppCtx.Provider>
  );
}

function describe(event: string): string {
  return ({
    "master.supplied": "used the supplied photo for",
    "master.generated": "created a key visual for",
    "master.approved": "approved the key visual for",
    "master.reopened": "reopened the key visual for",
    "copy.translated": "translated the message:",
    "copy.edited": "edited the message:",
    "copy.approved": "approved the message:",
    "frames.rendered": "built the ads:",
    "frame.approved": "approved",
    "frame.rejected": "rejected",
    "frame.cleared": "cleared the decision on",
  } as Record<string, string>)[event] ?? event;
}

function CampaignMenu({ campaigns, current, sample, onPick, onNew, onReset, onClose }: {
  campaigns: CampaignSummary[]; current: string; sample: boolean;
  onPick: (id: string) => void; onNew: (name: string) => void; onReset: () => void; onClose: () => void;
}) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  void onClose;
  return (
    <div className="menu" style={{ minWidth: 280 }}>
      {campaigns.map((c) => (
        <button key={c.id} className="menu-item" onClick={() => onPick(c.id)}>
          <span>{c.name}{c.sample && <span className="muted"> · sample</span>}</span>
          {c.id === current && <Check size={16} />}
        </button>
      ))}
      <div style={{ borderTop: "1px solid var(--line)", margin: "6px 0" }} />
      {naming ? (
        <form className="row" style={{ padding: 6 }} onSubmit={(e) => { e.preventDefault(); if (name.trim()) onNew(name.trim()); }}>
          <input className="input" autoFocus placeholder="Campaign name" value={name} onChange={(e) => setName(e.target.value)} style={{ padding: "8px 10px", fontSize: 14 }} />
          <Button kind="primary" size="sm" type="submit" disabled={!name.trim()}>Create</Button>
        </form>
      ) : (
        <button className="menu-item" onClick={() => setNaming(true)}><span className="row"><Plus size={16} /> New campaign</span></button>
      )}
      {sample && (
        <button className="menu-item" onClick={onReset}><span className="row"><RotateCcw size={15} /> Start the sample over</span></button>
      )}
    </div>
  );
}

function NameModal({ initial, onSave, onClose }: { initial: string; onSave: (n: string) => void; onClose: () => void }) {
  const [n, setN] = useState(initial);
  const valid = useMemo(() => n.trim().length >= 2, [n]);
  return (
    <Modal onClose={onClose}>
      <h2>Who's reviewing?</h2>
      <p className="muted" style={{ marginTop: 0, lineHeight: 1.5 }}>
        Approvals are signed with your name and the time, so the team can see who signed off on what.
      </p>
      <form onSubmit={(e) => { e.preventDefault(); if (valid) onSave(n.trim()); }}>
        <input className="input" autoFocus placeholder="Your name" value={n} onChange={(e) => setN(e.target.value)} />
        <div className="row" style={{ marginTop: 18, justifyContent: "flex-end" }}>
          <Button kind="ghost" type="button" onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" disabled={!valid}>Continue</Button>
        </div>
      </form>
    </Modal>
  );
}
