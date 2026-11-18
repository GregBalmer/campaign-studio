import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, History, LogOut, Plus, RotateCcw, Settings2, UserRound, X } from "lucide-react";
import { api, ApiError, LANGUAGE_NAMES, NEW_MARKETS, setSignedOutHandler, type CampaignSummary, type DemoAccount, type Person, type ProviderInfo, type View } from "./api";
import { AppCtx, Button, Drawer, clock, useDismiss, type Ctx } from "./ui";
import SignIn from "./SignIn";
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
const INLINE_ERRORS = /^(master-|upload-|translate$|fanout$)/;

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
  const [slack, setSlack] = useState(false);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [toastMsg, setToast] = useState<{ msg: string; kind: "info" | "error" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // undefined while checking; null when nobody is signed in.
  const [me, setMe] = useState<Person | null | undefined>(undefined);
  const [demo, setDemo] = useState<DemoAccount[]>([]);
  const [panel, setPanel] = useState<"settings" | "history" | "campaigns" | "account" | null>(null);
  const toastTimer = useRef<number>();
  const switcher = useRef<HTMLDivElement>(null);
  const account = useRef<HTMLDivElement>(null);
  useDismiss(switcher, panel === "campaigns", () => setPanel(null));
  useDismiss(account, panel === "account", () => setPanel(null));

  useEffect(() => {
    setSignedOutHandler(() => setMe(null));
    api.me().then((r) => { setDemo(r.demo); setMe(r.user); })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)));
  }, []);

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
    if (!me) return;
    (async () => {
      try {
        const [list, status] = await Promise.all([api.campaigns(), api.status()]);
        setCampaigns(list);
        setProviders(status.providers);
        setSlack(status.slack);
        const last = store("studio.campaign");
        const id = list.find((c) => c.id === last)?.id ?? list.find((c) => c.sample)?.id ?? list[0]?.id;
        if (id) await open(id);
      } catch (e) {
        if (e instanceof ApiError && e.message.startsWith("Sign in")) return;
        setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [open, me]);

  const loaded = view !== null;
  useEffect(() => {
    if (loaded && window.location.hash !== `#${HASHES[step]}`) history.replaceState(null, "", `#${HASHES[step]}`);
  }, [step, loaded]);

  // The browser's Back and Forward buttons (and edits to the address) move between steps,
  // but never past the furthest step the campaign has reached.
  const furthest = view ? stageStep[view.stage] : 0;
  useEffect(() => {
    const onNav = () => {
      const asked = HASHES.indexOf(window.location.hash.slice(1));
      if (asked < 0) return;
      setStep(Math.min(asked, furthest));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("popstate", onNav);
    window.addEventListener("hashchange", onNav);
    return () => {
      window.removeEventListener("popstate", onNav);
      window.removeEventListener("hashchange", onNav);
    };
  }, [furthest]);

  // Errors from long-running work (creating an image, translating, building the ads,
  // uploading) stay next to the thing that failed, with a Try again button, instead of
  // a toast that can vanish while nobody's looking.
  const [errors, setErrors] = useState<Record<string, string>>({});
  const retries = useRef<Record<string, () => Promise<View | void>>>({});
  const run = useCallback<Ctx["run"]>(async (key, fn) => {
    setBusy((b) => new Set(b).add(key));
    setErrors((e) => { if (!(key in e)) return e; const n = { ...e }; delete n[key]; return n; });
    try {
      const v = await fn();
      if (v) setView(v);
      return true;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
      if (INLINE_ERRORS.test(key)) {
        retries.current[key] = fn;
        setErrors((x) => ({ ...x, [key]: msg }));
      } else {
        toast(msg, "error");
      }
      return false;
    } finally {
      setBusy((b) => {
        const n = new Set(b);
        n.delete(key);
        return n;
      });
    }
  }, [toast]);

  const retry = useCallback((key: string) => {
    const fn = retries.current[key];
    if (fn) void run(key, fn);
  }, [run]);
  const dismissError = useCallback((key: string) => {
    setErrors((e) => { const n = { ...e }; delete n[key]; return n; });
  }, []);

  // Approvals are stamped on the server with whoever is signed in; this is just for display.
  const reviewerName = me?.name ?? "";
  const reviewer = useCallback(() => Promise.resolve(reviewerName), [reviewerName]);

  const signOut = async () => {
    setPanel(null);
    await api.signOut().catch(() => {});
    setView(null);
    setMe(null);
  };

  const refreshCampaigns = async () => setCampaigns(await api.campaigns());

  if (me === null) {
    return <SignIn demo={demo} onSignedIn={(p) => { setMe(p); setLoadError(null); }} />;
  }
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
    view, setView, run, busy, reviewer, reviewerName, toast, slack, errors, retry, dismissError,
    goTo: (s) => {
      if (s !== step) history.pushState(null, "", `#${HASHES[s]}`);
      setStep(s);
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
  };

  return (
    <AppCtx.Provider value={ctx}>
      <header className="topbar">
        <div className="wordmark">
          <span className="wordmark-mark"><AppMark /></span>
          Campaign Studio
          <span className="tagline">Built for Adobe Firefly Services</span>
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
        <div style={{ position: "relative" }} ref={account}>
          <button className="chip-button" aria-expanded={panel === "account"} onClick={() => setPanel(panel === "account" ? null : "account")}>
            <UserRound size={15} /> {reviewerName}
          </button>
          {panel === "account" && me && (
            <div className="menu user-menu">
              <div className="user-menu-head">
                <b>{me.name}</b>
                <span className="muted small">{me.email}{me.role && ` · ${me.role}`}</span>
              </div>
              <div style={{ borderTop: "1px solid var(--line)", margin: "4px 0" }} />
              <button className="menu-item" onClick={signOut}><span className="row"><LogOut size={15} /> Sign out</span></button>
            </div>
          )}
        </div>
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
          {[...view.log].reverse().filter((l) => !(l.event === "frames.rendered" && /^0 /.test(l.detail))).map((l, i) => (
            <div className="history-item" key={i}>
              <span className="when">{clock(l.at)}</span>
              <span><b>{l.by}</b> {describe(l.event)} <span className="muted">{humanDetail(view, l.event, l.detail)}</span></span>
            </div>
          ))}
        </Drawer>
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

/** One frame becoming many sizes. Deliberately unlike any client brand mark. */
export function AppMark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="3" y="10" width="15" height="15" rx="3" fill="#fff" opacity="0.55" />
      <rect x="14" y="5" width="10" height="18" rx="3" fill="#fff" opacity="0.8" />
      <rect x="9" y="17" width="20" height="11" rx="3" fill="#fff" />
    </svg>
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
    "copy.reopened": "reopened the message:",
    "frames.rendered": "built",
    "frame.approved": "approved",
    "frame.rejected": "rejected",
    "frame.cleared": "cleared the decision on",
    "market.requested": "asked IT to set up",
  } as Record<string, string>)[event] ?? event;
}

/** Turns the record's ids ("after-sun-gel/16x9/JP", "ja") into what people call them. */
function humanDetail(view: View, event: string, detail: string): string {
  const product = (id: string) => view.brief.products.find((p) => p.id === id)?.name ?? id;
  const market = (r: string) => view.brief.markets.find((m) => m.region === r)?.name ?? r;
  if (event.startsWith("frame.")) {
    const [key, ...note] = detail.split(": ");
    const [pid, fmt, region] = key.split("/");
    if (!fmt || !region) return detail;
    const size = view.formats[fmt]?.label ?? fmt;
    return `${product(pid)} · ${size} · ${market(region)}${note.length ? ` · “${note.join(": ")}”` : ""}`;
  }
  if (event.startsWith("copy.")) return LANGUAGE_NAMES[detail] ?? detail;
  if (event === "frames.rendered") return detail.replace(/ new or changed frame\(s\)/, " ads, new or changed,");
  if (event === "market.requested") {
    const [region, , via] = detail.split(" ");
    const name = NEW_MARKETS.find((m) => m.region === region)?.name ?? region;
    return via ? `${name}, by ${via}` : name;
  }
  return detail;
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
