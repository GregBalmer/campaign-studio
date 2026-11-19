import { useCallback, useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, FilePlus, LogOut, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { api, ApiError, LANGUAGE_NAMES, NEW_MARKETS, setSignedOutHandler, type CampaignSummary, type DemoAccount, type Person, type ProviderLists, type View } from "./api";
import { AppCtx, Button, Drawer, Modal, clock, useDismiss, type Ctx } from "./ui";
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
  const [providers, setProviders] = useState<ProviderLists>({ image: [], text: [] });
  const [slack, setSlack] = useState(false);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [toastMsg, setToast] = useState<{ msg: string; kind: "info" | "error" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // undefined while checking; null when nobody is signed in.
  const [me, setMe] = useState<Person | null | undefined>(undefined);
  const [demo, setDemo] = useState<DemoAccount[]>([]);
  const [panel, setPanel] = useState<"settings" | "history" | "campaigns" | "new-campaign" | "account" | null>(null);
  const [creating, setCreating] = useState<"blank" | "duplicate" | null>(null);
  const toastTimer = useRef<number>();
  const switcher = useRef<HTMLDivElement>(null);
  const creator = useRef<HTMLDivElement>(null);
  const account = useRef<HTMLDivElement>(null);
  useDismiss(switcher, panel === "campaigns", () => setPanel(null));
  useDismiss(creator, panel === "new-campaign", () => setPanel(null));
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

  // On a narrow screen the steps scroll sideways; keep the current one in view.
  const stepper = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = stepper.current;
    const cur = nav?.querySelector<HTMLElement>(".step.current");
    if (nav && cur && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = cur.offsetLeft - nav.offsetLeft - 16;
  }, [step, view?.id]);

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
  const frames = Object.values(view.frames);
  const stats = [
    { label: "Products", value: view.brief.products.length },
    { label: "Markets", value: view.brief.markets.length },
    { label: "Ads", value: view.brief.products.length * view.brief.markets.length * Object.keys(view.formats).length },
    { label: "Approved", value: frames.filter((f) => f.decision?.value === "approved").length },
  ];

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
      {/* The app's bar runs edge to edge, a little below the top; the campaign and its steps sit on the page below. */}
      <header className="topbar">
        <div className="topbar-left">
          <span className="wordmark-mark"><AppMark /></span>
          <span className="wordmark">Campaign Studio</span>
        </div>
        <div className="spacer" />
        <div className="topbar-right">
          {/* Starting a campaign is an app action, so it lives here, away from the campaign you're working on. */}
          <div className="campaign-slot new-campaign-slot" ref={creator}>
            <button className="bar-link bar-action" aria-expanded={panel === "new-campaign"} aria-label="New campaign"
              onClick={() => setPanel(panel === "new-campaign" ? null : "new-campaign")}>
              <Plus size={14} strokeWidth={2.25} /><span className="bar-action-label">New campaign</span>
            </button>
            {panel === "new-campaign" && (
              <div className="menu new-campaign-menu">
                <button className="menu-item" onClick={() => { setPanel(null); setCreating("blank"); }}>
                  <span className="row"><FilePlus size={15} /> Blank campaign</span>
                </button>
                <button className="menu-item" onClick={() => { setPanel(null); setCreating("duplicate"); }}>
                  <span className="row"><Copy size={15} /> Duplicate “{view.brief.campaign || "Untitled campaign"}”</span>
                </button>
              </div>
            )}
          </div>
          <button className="bar-link" onClick={() => setPanel("settings")} title="Which services make the images and translate the message">Models</button>
          <button className="bar-link" onClick={() => setPanel("history")} title="Who did what">History</button>
          <div className="campaign-slot" ref={account}>
            <button className="avatar" aria-expanded={panel === "account"} onClick={() => setPanel(panel === "account" ? null : "account")}
              title={reviewerName} aria-label={`Account: ${reviewerName}`}>
              {initials(reviewerName)}
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
        </div>
      </header>

      <div className="camphead">
        <div className="camphead-inner">
          <div className="camphead-row">
            <div className="camphead-title">
              <div className="camphead-name-row">
              <div className="campaign-slot" ref={switcher}>
                <button className="campaign-switch" aria-expanded={panel === "campaigns"} aria-label="Switch campaign"
                  onClick={() => setPanel(panel === "campaigns" ? null : "campaigns")}>
                  <span className="campaign-name">{view.brief.campaign || "Untitled campaign"}</span>
                  {view.sample && <span className="badge">Sample</span>}
                  {/* The name is the control; the round white button says so. */}
                  <span className="campaign-chevron"><ChevronDown size={16} strokeWidth={2.25} /></span>
                </button>
                {panel === "campaigns" && (
                  <CampaignMenu
                    campaigns={campaigns}
                    current={view.id}
                    onPick={async (id) => { setPanel(null); await run("open", async () => { await open(id); }); }}
                    onDelete={async (c) => {
                      setPanel(null);
                      await run("delete", async () => {
                        const list = await api.deleteCampaign(c.id);
                        setCampaigns(list);
                        // Deleting the campaign you're in takes you to the sample.
                        if (c.id === view.id) {
                          const next = list.find((x) => x.sample)?.id ?? list[0]?.id;
                          if (next) { setStep(0); await open(next, false); }
                        }
                        toast(`Deleted “${c.name}”.`);
                      });
                    }}
                  />
                )}
              </div>
              {/* The sample can be put back to how it shipped, for the next demo. It asks first, in a small modal. */}
              {view.sample && (
                <RestartDemo busy={busy.has("reset")} onConfirm={async () => {
                  await run("reset", async () => {
                    const v = await api.reset(view.id, reviewerName);
                    setStep(0);
                    toast("The demo is back at the start.");
                    return v;
                  });
                }} />
              )}
              </div>
            </div>
            <dl className="camp-stats">
              {stats.map((s) => (
                <div className="camp-stat" key={s.label}>
                  <dd>{s.value}</dd>
                  <dt>{s.label}</dt>
                </div>
              ))}
            </dl>
          </div>

        </div>
      </div>

      {/* One flow, four steps: each says what you do there. */}
      <nav className="stepper" aria-label="Steps" ref={stepper}>
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
              <span className="when">{(({ day, time }) => <>{day && <span className="when-day">{day}</span>}{time}</>)(clock(l.at))}</span>
              <span><b>{l.by}</b> {describe(l.event)} <span className="muted">{humanDetail(view, l.event, l.detail)}</span></span>
            </div>
          ))}
        </Drawer>
      )}
      {creating && (
        <NewCampaignModal kind={creating} source={view.brief.campaign || "Untitled campaign"} onClose={() => setCreating(null)}
          onCreate={async () => {
            const kind = creating;
            setCreating(null);
            await run("new", async () => {
              const v = kind === "duplicate" ? await api.duplicateCampaign(view.id) : await api.createCampaign("Untitled campaign");
              await refreshCampaigns();
              setStep(0);
              return v;
            });
          }} />
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

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

/** One frame becoming many sizes. Deliberately unlike any client brand mark.
 *  Drawn in currentColor, so its tile sets the colour. */
export function AppMark({ size = 25 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="3" y="10" width="15" height="15" rx="3" fill="currentColor" opacity="0.55" />
      <rect x="14" y="5" width="10" height="18" rx="3" fill="currentColor" opacity="0.8" />
      <rect x="9" y="17" width="20" height="11" rx="3" fill="currentColor" />
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
    "copy.revised": "asked for a change to",
    "frames.rendered": "built",
    "frame.approved": "approved",
    "frame.rejected": "rejected",
    "frame.cleared": "cleared the decision on",
    "market.requested": "asked IT to set up",
    "campaign.restarted": "started the campaign over",
    "campaign.duplicated": "made this campaign as a copy of",
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
  if (event.startsWith("copy.")) {
    // "ja", "ja via OpenAI" or "ja: Make it shorter"
    const [, lang, sep, rest] = detail.match(/^([a-z]{2,3})(:? ?)(.*)$/) ?? [, detail, "", ""];
    return `${LANGUAGE_NAMES[lang!] ?? lang}${rest ? `${sep === ": " ? ": “" : " "}${rest}${sep === ": " ? "”" : ""}` : ""}`;
  }
  if (event === "frames.rendered") return detail.replace(/ new or changed frame\(s\)/, " ads, new or changed,");
  if (event === "market.requested") {
    const [region, , via] = detail.split(" ");
    const name = NEW_MARKETS.find((m) => m.region === region)?.name ?? region;
    return via ? `${name}, by ${via}` : name;
  }
  return detail;
}

/** One popup for both ways to start a campaign. No name asked: it's the first field on the Brief. */
function NewCampaignModal({ kind, source, onClose, onCreate }: {
  kind: "blank" | "duplicate"; source: string; onClose: () => void; onCreate: () => void;
}) {
  return (
    <Modal onClose={onClose}>
      <h2>{kind === "blank" ? "New campaign" : `Duplicate “${source}”`}</h2>
      <p className="muted" style={{ margin: "0 0 20px", lineHeight: 1.55 }}>
        {kind === "blank"
          ? "Starts with an empty brief. You can name it on the first step."
          : "Same brief and photos. Key visuals, translations and approvals start fresh."}
      </p>
      <div className="modal-actions">
        <Button kind="ghost" onClick={onClose}>Cancel</Button>
        <Button kind="primary" autoFocus onClick={onCreate}>Create</Button>
      </div>
    </Modal>
  );
}

function CampaignMenu({ campaigns, current, onPick, onDelete }: {
  campaigns: CampaignSummary[]; current: string;
  onPick: (id: string) => void; onDelete: (c: CampaignSummary) => void;
}) {
  // Deleting asks once, in place: the row turns into the question.
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <div className="menu" style={{ minWidth: 300 }}>
      {campaigns.map((c) => confirming === c.id ? (
        <div key={c.id} className="menu-confirm">
          <span>Delete “{c.name}” and its ads? This can't be undone.</span>
          <span className="row" style={{ gap: 6 }}>
            <Button size="sm" kind="ghost" onClick={() => setConfirming(null)}>Keep it</Button>
            <Button size="sm" kind="danger" autoFocus onClick={() => onDelete(c)}>Delete</Button>
          </span>
        </div>
      ) : (
        <div key={c.id} className="menu-row">
          <button className="menu-item" onClick={() => onPick(c.id)}>
            <span>{c.name}{c.sample && <span className="muted"> · sample</span>}</span>
            {c.id === current && <Check size={16} />}
          </button>
          {!c.sample && (
            <button className="menu-row-delete" aria-label={`Delete ${c.name}`} title="Delete this campaign" onClick={() => setConfirming(c.id)}>
              <Trash2 size={15} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

/** Restart demo: puts the sample back to how it shipped, after asking in a small modal. */
function RestartDemo({ busy, onConfirm }: { busy: boolean; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button size="sm" kind="ghost" icon={<RotateCcw size={14} strokeWidth={2.25} />} busy={busy} onClick={() => setAsking(true)}>Restart demo</Button>
      {asking && (
        <Modal className="modal-compact" onClose={() => setAsking(false)}>
          <h2>This will restart the demo</h2>
          <div className="modal-actions">
            <Button kind="secondary" onClick={() => setAsking(false)}>Cancel</Button>
            <Button kind="primary" autoFocus onClick={() => { setAsking(false); onConfirm(); }}>Restart</Button>
          </div>
        </Modal>
      )}
    </>
  );
}
