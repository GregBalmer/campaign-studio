import { useEffect, useRef, useState } from "react";
import { ArrowRight, ImagePlus, Plus, Sparkles, Trash2, X } from "lucide-react";
import { api, LANGUAGE_NAMES, MARKET_PRESETS, NEW_MARKETS, photoUrl, restrictedHits, type Brief, type Market, type NewMarket, type Product } from "../api";
import { Button, FormatGlyph, Modal, useApp, useDebounced, useDismiss } from "../ui";

export default function BriefStep() {
  const { view, setView, run, busy, goTo, reviewer, toast } = useApp();
  const [draft, setDraft] = useState<Brief>(view.brief);
  const saved = useRef(JSON.stringify(view.brief));
  const debounced = useDebounced(draft, 500);

  // Start from the server's copy whenever another campaign is opened.
  useEffect(() => {
    setDraft(view.brief);
    saved.current = JSON.stringify(view.brief);
  }, [view.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Autosave: there is no Save button to forget.
  useEffect(() => {
    const s = JSON.stringify(debounced);
    if (s === saved.current) return;
    saved.current = s;
    const { campaign, message, audience, mood, markets, products } = debounced;
    api.patchBrief(view.id, { campaign, message, audience, mood, markets, products }).then(setView).catch(() =>
      toast("Couldn't save the last change. Check the app is still running.", "error"));
  }, [debounced]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = <K extends keyof Brief>(k: K, v: Brief[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const setProduct = (i: number, patch: Partial<Product>) =>
    set("products", draft.products.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  const hits = restrictedHits(draft.message, draft.message_language, draft);
  const ads = draft.products.length * 3 * draft.markets.length;
  const langs = Array.from(new Set(draft.markets.map((m) => m.language)));
  const ready = view.problems.length === 0 && JSON.stringify(draft) === saved.current;
  const started = draft.products.some((p) => view.products[p.id]?.master);

  const upload = async (pid: string, file: File) => {
    await run(`upload-${pid}`, async () => {
      const v = await api.upload(view.id, pid, file);
      setDraft(v.brief);
      saved.current = JSON.stringify(v.brief);
      return v;
    });
  };
  const removePhoto = (pid: string) =>
    run(`upload-${pid}`, async () => {
      const v = await api.removePhoto(view.id, pid);
      setDraft(v.brief);
      saved.current = JSON.stringify(v.brief);
      return v;
    });

  const begin = async () => {
    const by = await reviewer();
    goTo(1);
    // Kick off every product without a key visual; the next screen shows progress.
    for (const p of draft.products) {
      if (!view.products[p.id]?.master) void run(`master-${p.id}`, () => api.makeMaster(view.id, p.id, by));
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Set up the campaign</h1>
          <p>Tell us what you're launching. You'll approve one key visual per product, then we adapt it to every size and market.</p>
        </div>
      </div>

      <div className="grid-2">
        <div>
          <section className="card card-pad">
            <div className="field">
              <label className="label" htmlFor="campaign">Campaign name</label>
              <input id="campaign" className="input" value={draft.campaign} onChange={(e) => set("campaign", e.target.value)} />
            </div>
            <div className="field">
              <label className="label" htmlFor="message">
                Message <span className="muted">Shown on every ad · {draft.message.length} characters</span>
              </label>
              <input
                id="message"
                className={`input big ${hits.length ? "invalid" : ""}`}
                value={draft.message}
                placeholder="One short line, in English"
                onChange={(e) => set("message", e.target.value)}
              />
              {hits.length > 0 ? (
                <span className="field-note fail">Legal restricts “{hits.join("”, “")}”. Change the wording.</span>
              ) : (
                <span className="field-note">Short lines read best on a phone. Under 40 characters is ideal.</span>
              )}
            </div>
            <div className="field">
              <label className="label" htmlFor="audience">Who it's for</label>
              <textarea id="audience" className="textarea" rows={2} value={draft.audience} onChange={(e) => set("audience", e.target.value)} />
            </div>
          </section>

          <section className="card card-pad">
            <h3 className="card-title">Markets</h3>
            <p className="card-hint">Each market gets every ad in its own language. You'll check each translation before anything is made.</p>
            <div className="row-wrap">
              {draft.markets.map((m) => (
                <span className="market-chip" key={m.region}>
                  <span className="flag">{m.region}</span>
                  {m.name}
                  <span className="muted small">{LANGUAGE_NAMES[m.language]}</span>
                  {draft.markets.length > 1 && (
                    <button aria-label={`Remove ${m.name}`} onClick={() => set("markets", draft.markets.filter((x) => x.region !== m.region))}>
                      <X size={14} />
                    </button>
                  )}
                </span>
              ))}
              <AddMarket existing={draft.markets} onAdd={(m) => set("markets", [...draft.markets, m])} />
            </div>
          </section>

          <section className="card card-pad">
            <h3 className="card-title">Products</h3>
            <p className="card-hint">Have a product photo? Drop it in and we'll use it. No photo? Leave it empty and we'll create one from the description.</p>
            {draft.products.map((p, i) => (
              <div className="product-card" key={p.id}>
                <PhotoDrop
                  url={photoUrl(view, p)}
                  busy={busy.has(`upload-${p.id}`)}
                  onFile={(f) => upload(p.id, f)}
                  onRemove={() => removePhoto(p.id)}
                />
                <div>
                  <div className="field">
                    <label className="label" htmlFor={`pn-${p.id}`}>
                      Product {i + 1}
                      {draft.products.length > 2 && (
                        <button className="btn btn-ghost btn-sm" style={{ height: 22, padding: "0 6px" }}
                          onClick={() => set("products", draft.products.filter((x) => x.id !== p.id))}>
                          <Trash2 size={13} /> Remove
                        </button>
                      )}
                    </label>
                    <input id={`pn-${p.id}`} className="input" placeholder="Product name" value={p.name} onChange={(e) => setProduct(i, { name: e.target.value })} />
                  </div>
                  <div className="field" style={{ marginTop: 10 }}>
                    <textarea
                      className="textarea"
                      rows={2}
                      placeholder="What does it look like? Colour, shape, packaging."
                      value={p.description ?? ""}
                      onChange={(e) => setProduct(i, { description: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            ))}
            {draft.products.length < 6 && (
              <Button kind="ghost" icon={<Plus size={16} />} style={{ marginTop: 10 }}
                onClick={() => set("products", [...draft.products, { id: `product-${Date.now().toString(36)}`, name: "", description: "" }])}>
                Add a product
              </Button>
            )}
          </section>

          <section className="card card-pad">
            <h3 className="card-title">Look and feel</h3>
            <p className="card-hint">Guides any image we create. Brand colours and logo come from the {draft.brand.name} brand kit.</p>
            <div className="field">
              <label className="label" htmlFor="mood">Mood</label>
              <textarea id="mood" className="textarea" rows={2} value={draft.mood ?? ""} onChange={(e) => set("mood", e.target.value)}
                placeholder="Light, setting, feeling. For example: golden-hour beach, relaxed and premium." />
            </div>
            <div className="row" style={{ marginTop: 18, gap: 24, flexWrap: "wrap" }}>
              <div>
                <div className="label" style={{ marginBottom: 8 }}>Brand colours</div>
                <div className="row">
                  {Object.entries(draft.brand.colors).map(([k, c]) => (
                    <span key={k} className="swatch" style={{ background: c }} title={`${k} ${c}`} />
                  ))}
                </div>
              </div>
              {draft.brand.logo && (
                <div>
                  <div className="label" style={{ marginBottom: 8 }}>Logo</div>
                  <div className="logo-box"><img src={`/files/workspace/${view.id}/${draft.brand.logo}`} alt={`${draft.brand.name} logo`} /></div>
                </div>
              )}
            </div>
          </section>
        </div>

        <aside className="sticky">
          <section className="card card-pad">
            <div className="muted small" style={{ fontWeight: 600, marginBottom: 8 }}>What you'll get</div>
            <div className="summary-figure">{ads} ads</div>
            <div className="equation">
              <b>{draft.products.length}</b> products × <b>3</b> sizes × <b>{draft.markets.length}</b> {draft.markets.length === 1 ? "market" : "markets"}
            </div>
            <div className="format-icons">
              {Object.values(view.formats).map((f) => (
                <span className="format-icon" key={f.ratio}><FormatGlyph ratio={f.ratio} h={34} />{f.label}</span>
              ))}
            </div>
            <div className="muted small" style={{ marginBottom: 18, lineHeight: 1.5 }}>
              In {langs.map((l) => LANGUAGE_NAMES[l]).join(" and ")}. Every ad is checked for logo, brand colours, legibility and restricted words.
            </div>
            {view.problems.length > 0 && (
              <div className="problems">
                <b>Before you continue</b>
                <ul>{view.problems.map((p) => <li key={p}>{p}</li>)}</ul>
              </div>
            )}
            <Button kind="primary" size="lg" className="btn-block" disabled={!ready} onClick={begin}
              icon={started ? <ArrowRight size={18} /> : <Sparkles size={18} />}>
              {started ? "Continue to key visuals" : "Create key visuals"}
            </Button>
          </section>
        </aside>
      </div>
    </>
  );
}

function AddMarket({ existing, onAdd }: { existing: Market[]; onAdd: (m: Market) => void }) {
  const [open, setOpen] = useState(false);
  const [setup, setSetup] = useState<NewMarket | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  useDismiss(ref, open, () => setOpen(false));
  const options = MARKET_PRESETS.filter((m) => !existing.some((e) => e.region === m.region));
  return (
    <span className="add-market" ref={ref}>
      <Button kind="ghost" icon={<Plus size={16} />} onClick={() => setOpen(!open)} style={{ height: 38 }}
        aria-expanded={open} aria-haspopup="menu">Add market</Button>
      {open && (
        <div className="menu" role="menu">
          {options.length > 0 && <div className="menu-heading">Ready to use</div>}
          {options.map((m) => (
            <button key={m.region} role="menuitem" className="menu-item" onClick={() => { onAdd(m); setOpen(false); }}>
              {m.name} <span className="muted">{LANGUAGE_NAMES[m.language]}</span>
            </button>
          ))}
          <div className="menu-heading">New to the brand <span className="muted">· one-time setup</span></div>
          {NEW_MARKETS.map((m) => (
            <button key={m.region} role="menuitem" className="menu-item" onClick={() => { setSetup(m); setOpen(false); }}>
              {m.name} <span className="badge">Set up</span>
            </button>
          ))}
        </div>
      )}
      {setup && <MarketSetup market={setup} onClose={() => setSetup(null)} />}
    </span>
  );
}

/** What it takes to launch somewhere the brand hasn't been before. */
function MarketSetup({ market: m, onClose }: { market: NewMarket; onClose: () => void }) {
  const { view, toast } = useApp();
  const brand = view.brief.brand.name;
  const steps: { title: string; who: string; body: string }[] = [
    {
      title: `A typeface for ${m.languageName}`,
      who: "Your Adobe or IT team, once",
      body: `${m.script} isn't covered by ${brand}'s current fonts, so the app won't offer ${m.name} yet rather than print empty boxes. `
        + `Add ${m.font} (free, from Google Fonts, SIL Open Font Licence) or ${brand}'s licensed ${m.languageName} typeface. Nobody on the creative team downloads anything.`
        + (m.rtl ? ` ${m.languageName} reads right to left, so layouts mirror too: the message card and logo move to the right. That's a one-time template change.` : ""),
    },
    {
      title: `Someone who reads ${m.languageName}`,
      who: "Your local marketing team",
      body: `They approve the message in step 3. "What it says" helps everyone else follow along, but a native reader signs off.`,
    },
    {
      title: "Restricted words and claims",
      who: `Legal, for ${m.name}`,
      body: `The list of words and claims to avoid in ${m.languageName}. It goes into the brand kit and is checked automatically on every ad, as English and Japanese are today.`,
    },
    {
      title: "Local advertising rules",
      who: `Legal or your agency in ${m.name}`,
      body: "Ad rules differ by country: what a product may claim (sun-protection and skincare claims are regulated in many markets), required disclaimers, "
        + "and in some places approval before an ad runs. They're confirmed before launch; any wording that must appear on the ad becomes part of the template.",
    },
    {
      title: "Local assets, if needed",
      who: "Brand team",
      body: "Imagery that fits the market (people, settings, seasons), local product names, and any logo variant used there.",
    },
  ];
  const copy = () => {
    const text = `Launching ${brand} in ${m.name}: what we need\n\n` +
      steps.map((s, i) => `${i + 1}. ${s.title} (${s.who})\n   ${s.body}`).join("\n\n");
    navigator.clipboard?.writeText(text).then(() => toast("Checklist copied. Paste it into an email or ticket."),
      () => toast("Couldn't copy. Select the text instead.", "error"));
  };
  return (
    <Modal onClose={onClose}>
      <div className="setup-modal">
        <h2>Launching in {m.name}</h2>
        <p className="muted" style={{ marginTop: 0, lineHeight: 1.5 }}>
          {brand} hasn't run in {m.name} before. Here's what's set up once, and by whom. After that, {m.name} joins the ready list and
          the workflow is exactly the same.
        </p>
        <ol className="setup-list">
          {steps.map((s) => (
            <li key={s.title}>
              <div className="setup-title">{s.title} <span className="badge">{s.who}</span></div>
              <div className="setup-body">{s.body}</div>
            </li>
          ))}
        </ol>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
          <Button kind="ghost" onClick={onClose}>Close</Button>
          <Button kind="primary" onClick={copy}>Copy checklist</Button>
        </div>
      </div>
    </Modal>
  );
}

function PhotoDrop({ url, busy, onFile, onRemove }: { url: string | null; busy: boolean; onFile: (f: File) => void; onRemove: () => void }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      className={`dropzone ${over ? "over" : ""}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
      role="button"
      tabIndex={0}
      aria-label={url ? "Replace product photo" : "Add product photo"}
    >
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      {url ? (
        <>
          <img src={url} alt="" />
          <span className="tag">Your photo</span>
          <button className="remove" aria-label="Remove photo" onClick={(e) => { e.stopPropagation(); onRemove(); }}><X size={14} /></button>
        </>
      ) : (
        <>
          <ImagePlus size={22} />
          {busy ? "Uploading…" : <>Drop a photo<br /><span style={{ opacity: 0.8 }}>or leave empty to create one</span></>}
        </>
      )}
    </div>
  );
}
