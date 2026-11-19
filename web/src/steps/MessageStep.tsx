import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, MessageSquareText, Pencil } from "lucide-react";
import { api, LANGUAGE_NAMES, restrictedHits, type Check as CheckT } from "../api";
import { Button, NextPanel, ErrorNote, Markers, StatusBadge, timeAgo, useApp, useDebounced } from "../ui";

export default function MessageStep() {
  const { view, run, busy, reviewer, goTo, errors } = useApp();
  const langs = view.languages;
  const approved = langs.filter((l) => view.copy[l]?.approved).length;
  const all = approved === langs.length;
  const translating = busy.has("translate");
  const missing = langs.some((l) => !view.copy[l]);
  const ads = view.brief.products.length * 3 * view.brief.markets.length;

  // Translations are made in place, like key visuals: any language without its line
  // (first visit, or after the English line changed) is translated straight away,
  // and its card shows that it's working. If it fails, the card says so and offers a retry.
  useEffect(() => {
    if (missing && !translating && !errors["translate"]) {
      reviewer().then((by) => run("translate", () => api.translate(view.id, by)));
    }
  }, [missing, translating]); // eslint-disable-line react-hooks/exhaustive-deps

  // The review screen builds the ads as soon as it opens.
  const build = () => goTo(3);
  // One size for every preview on the page, so each language row lines up the same way.
  const [format, setFormat] = useState("1x1");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approve the message</h1>
          <p>Check the wording in every language. Edits show on the ad straight away and cost nothing: the words sit on top of the image, not inside it.</p>
        </div>
      </div>

      <div className="grid-2">
      <div>
      <div className="preview-size">
        <span className="muted small">Preview every product as</span>
        <div className="seg">
          {Object.entries(view.formats).map(([k, f]) => (
            <button key={k} className={k === format ? "on" : ""} aria-pressed={k === format} onClick={() => setFormat(k)} title={`${f.label} · ${f.ratio}`}>{f.label}</button>
          ))}
        </div>
      </div>
      {langs.map((lang) => view.copy[lang]
        ? <LanguageCard key={lang} lang={lang} format={format} />
        : <TranslatingCard key={lang} lang={lang} />)}
      </div>

      <aside className="sticky">
        <NextPanel label="Languages" figure={`${approved} of ${langs.length} approved`}
          detail={all ? `Ready to build ${ads} ads.` : "Approve every language to build the ads."}>
          <Button kind="primary" size="lg" className="btn-block" disabled={!all} onClick={build}>Build all {ads} ads</Button>
        </NextPanel>
      </aside>
      </div>
    </>
  );
}

/** A language whose line is on its way: the same card, shimmering, until the translation lands. */
function TranslatingCard({ lang }: { lang: string }) {
  const { view, errors } = useApp();
  const failed = !!errors["translate"];
  return (
    <section className="card card-pad lang-row" aria-busy={!failed}>
      <div className="lang-head">
        <h3>{LANGUAGE_NAMES[lang]}</h3>
        <span className="muted small">{view.brief.markets.filter((m) => m.language === lang).map((m) => m.name).join(", ")}</span>
      </div>
      {failed ? <ErrorNote k="translate" action="Translate again" /> : (
        <>
          <div className="working-line" role="status">
            <Loader2 size={18} className="spin" />
            <span><b>Translating…</b> adapting the line for {LANGUAGE_NAMES[lang]}, not just swapping words.</span>
          </div>
          <div className="lang-previews f-1x1" style={{ "--across": Math.min(view.brief.products.length, 3) } as React.CSSProperties}>
            {view.brief.products.map((p) => <div key={p.id} className="preview-wrap skeleton" style={{ aspectRatio: "1 / 1" }} />)}
          </div>
        </>
      )}
    </section>
  );
}

function LanguageCard({ lang, format }: { lang: string; format: string }) {
  const { view, run, busy, reviewer } = useApp();
  const entry = view.copy[lang];
  const source = view.brief.message_language;
  const isSource = lang === source;
  const markets = view.brief.markets.filter((m) => m.language === lang).map((m) => m.name);
  const products = view.brief.products;
  const [text, setText] = useState(entry.text);
  const [previews, setPreviews] = useState<Record<string, { image: string; checks: CheckT[] }>>({});
  const [loading, setLoading] = useState(false);
  const typed = useDebounced(text, 280);
  const hits = restrictedHits(text, lang, view.brief);
  const dirty = text.trim() !== entry.text;
  const spec = view.formats[format];
  const [asking, setAsking] = useState(false);
  const [typing, setTyping] = useState(false);
  const canRewrite = view.providers.text !== "mock";
  const [ask, setAsk] = useState("");
  const revising = busy.has(`revise-${lang}`);
  const revise = async (instruction: string) => {
    const by = await reviewer();
    const ok = await run(`revise-${lang}`, () => api.reviseCopy(view.id, lang, instruction, by));
    if (ok) { setAsking(false); setAsk(""); }
  };

  useEffect(() => { setText(entry.text); setTyping(false); }, [entry.text]);

  // Every product at once, so the row always shows the same products in the same places.
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all(products.map((p) => api.preview(view.id, p.id, format, lang, typed.trim() || " ", 760).then((r) => [p.id, r] as const)))
      .then((all) => { if (live) { setPreviews(Object.fromEntries(all)); setLoading(false); } })
      .catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [typed, format, view.id, lang, products.map((p) => p.id).join()]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!dirty || hits.length > 0 || !text.trim()) return !dirty;
    const by = await reviewer();
    return run(`copy-${lang}`, () => api.editCopy(view.id, lang, text, by));
  };
  const approve = async () => {
    const by = await reviewer();
    if (!(await save())) return;
    await run(`approve-copy-${lang}`, () => api.approveCopy(view.id, lang, by));
  };

  // The wording's problems across every product, each said once.
  const WORD_CHECKS = ["readable", "fits", "words"];
  const problems: CheckT[] = [];
  for (const p of products) {
    for (const c of previews[p.id]?.checks ?? []) {
      if (c.status !== "pass" && WORD_CHECKS.includes(c.id) && !problems.some((x) => x.id === c.id)) problems.push(c);
    }
  }

  return (
    <section className="card card-pad lang-row">
      <div className="lang-head">
        <h3>{LANGUAGE_NAMES[lang]}</h3>
        <span className="muted small">{isSource ? "Original" : markets.join(", ")}</span>
        <span className="space" />
        {entry.approved ? <span title={`Approved by ${entry.approved.by}, ${timeAgo(entry.approved.at)}`}><StatusBadge status="pass"><Check size={12} strokeWidth={3} /> Approved</StatusBadge></span>
          : entry.origin === "edited" ? <StatusBadge status="warn">Edited · needs approval</StatusBadge>
          : <StatusBadge status="warn">Needs approval</StatusBadge>}
      </div>

      {/* Kept short: the line, what it says in English, and only the warnings that need action.
          A translated line isn't a text box; most reviewers can't type the language, so they
          ask for a change in English instead. Someone who can type it opens the box on purpose. */}
      <div className="lang-main">
        {entry.approved || (!isSource && !typing) ? (
          <div className="copy-input copy-locked" lang={lang} aria-label={`${LANGUAGE_NAMES[lang]} message`}>{entry.text}</div>
        ) : (
          <textarea
            className={`textarea copy-input ${hits.length ? "invalid" : ""}`}
            rows={2}
            value={text}
            lang={lang}
            autoFocus={typing}
            onChange={(e) => setText(e.target.value)}
            onBlur={save}
            aria-label={`${LANGUAGE_NAMES[lang]} message`}
          />
        )}
        {/* Undo sits right under the line being edited, not below the ads. */}
        {(hits.length > 0 || dirty) && (
          <div className="edit-row">
            {hits.length > 0 ? <span className="field-note fail">Legal restricts “{hits.join("”, “")}” in {LANGUAGE_NAMES[lang]}.</span> : <span />}
            {dirty && <Button kind="secondary" size="sm" onMouseDown={(e) => e.preventDefault()} onClick={() => { setText(entry.text); setTyping(false); }}>Undo changes</Button>}
          </div>
        )}
        {!isSource && entry.back_translation && !dirty && (
          <div className="meaning"><span className="muted">In English:</span> {entry.back_translation}</div>
        )}
        {/* Warnings, one line each, only while there's still a decision to make. */}
        {!entry.approved && !dirty && (entry.drift || problems.length > 0) && (
          <div className="lang-warnings">
            {!isSource && entry.drift && <div className="drift"><AlertTriangle size={15} /><span><b>Changed the meaning.</b> {entry.drift}</span></div>}
            {problems.map((c) => <div key={c.id} className={`drift ${c.status}`}><AlertTriangle size={15} /><span>{c.message}</span></div>)}
          </div>
        )}
      </div>

      {/* The ads share the row's width: big enough to read the words. Square ads go up to three
          across and wide ones two; tall ones keep a fixed width so they don't run off the screen. */}
      <div className={`lang-previews f-${format}`}
        style={{ "--across": Math.min(products.length, format === "16x9" ? 2 : format === "9x16" ? 4 : 3) } as React.CSSProperties}>
        {products.map((p) => {
          const r = previews[p.id];
          return (
            <figure key={p.id} className="lang-preview">
              <div className={`preview-wrap ${loading ? "loading" : ""}`} style={{ aspectRatio: `${spec.size[0]} / ${spec.size[1]}` }}>
                {r ? <img src={r.image} alt={`${p.name}, ${LANGUAGE_NAMES[lang]}`} />
                  : <div className="preview-pending"><Loader2 size={20} className="spin" /></div>}
                {r && <Markers checks={r.checks.filter((c) => WORD_CHECKS.includes(c.id))} />}
              </div>
              <figcaption>{p.name}</figcaption>
            </figure>
          );
        })}
      </div>

      <div className="row lang-actions">
        {entry.approved ? (
          <Button kind="ghost" size="sm" icon={<Pencil size={14} />} className="lang-edit"
            onClick={async () => { const by = await reviewer(); run(`copy-${lang}`, () => api.reopenCopy(view.id, lang, by)); }}>
            Edit
          </Button>
        ) : (
          <>
            <Button kind="approve" icon={<Check size={17} strokeWidth={2.6} />} onClick={approve}
              busy={busy.has(`approve-copy-${lang}`) || busy.has(`copy-${lang}`)} disabled={!text.trim() || hits.length > 0}>
              Approve {LANGUAGE_NAMES[lang]}
            </Button>
            {/* One way to change a translated line: ask in English. Typing it yourself is inside. */}
            {!isSource && !dirty && !asking && !typing && (
              <Button kind="ghost" icon={<MessageSquareText size={15} />} onClick={() => (canRewrite ? setAsking(true) : setTyping(true))}>
                {canRewrite ? "Ask for a change" : "Change the wording"}
              </Button>
            )}
          </>
        )}
      </div>
      {asking && !entry.approved && (
        <div className="ask-change">
          {/* Right under the button that opened it; the new line and its meaning show above as soon as it's back. */}
          <span className="label">What should be different? Ask in English.</span>
          <div className="row ask-picks">
            <Button size="sm" disabled={revising} onClick={() => revise("closer")}>Closer to the original</Button>
            <Button size="sm" disabled={revising} onClick={() => revise("shorter")}>Shorter</Button>
          </div>
          <form className="row ask-own" onSubmit={(e) => { e.preventDefault(); if (ask.trim()) revise(ask.trim()); }}>
            <input className="input" value={ask} onChange={(e) => setAsk(e.target.value)} autoFocus disabled={revising}
              placeholder={`Or in your words, e.g. keep “Made for”`} aria-label={`What should change in the ${LANGUAGE_NAMES[lang]} line`} />
            <Button kind="primary" type="submit" busy={revising} disabled={!ask.trim()}>Rewrite</Button>
            <Button kind="ghost" type="button" disabled={revising} onClick={() => { setAsking(false); setAsk(""); }}>Cancel</Button>
          </form>
          <button className="link small ask-type" onClick={() => { setAsking(false); setTyping(true); }}>I read {LANGUAGE_NAMES[lang]}. Let me type it.</button>
        </div>
      )}
    </section>
  );
}
