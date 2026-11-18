import { useEffect, useState } from "react";
import { ArrowRight, Check, Languages, Pencil } from "lucide-react";
import { api, LANGUAGE_NAMES, restrictedHits, type Check as CheckT } from "../api";
import { Button, CheckIconDot, ErrorNote, Markers, StatusBadge, timeAgo, useApp, useDebounced } from "../ui";

export default function MessageStep() {
  const { view, run, busy, reviewer, goTo } = useApp();
  const langs = view.languages;
  const approved = langs.filter((l) => view.copy[l]?.approved).length;
  const all = approved === langs.length;
  const translating = busy.has("translate");
  const missing = langs.some((l) => !view.copy[l]);
  const ads = view.brief.products.length * 3 * view.brief.markets.length;

  // The review screen builds the ads as soon as it opens.
  const build = () => goTo(3);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approve the message</h1>
          <p>Check the wording in every language. Edits show on the ad straight away and cost nothing: the words sit on top of the image, not inside it.</p>
        </div>
      </div>

      {missing && (
        <div className="card card-pad empty" style={{ padding: 40 }}>
          <ErrorNote k="translate" />
          {translating ? (
            <><Languages size={26} /><p style={{ margin: "12px 0 0" }}><b>Translating…</b> adapting the line for each market, not just swapping words.</p></>
          ) : (
            <Button kind="primary" icon={<Languages size={16} />}
              onClick={async () => { const by = await reviewer(); run("translate", () => api.translate(view.id, by)); }}>
              Translate the message
            </Button>
          )}
        </div>
      )}

      {!missing && langs.map((lang) => <LanguageCard key={lang} lang={lang} />)}

      <div className="footer-bar">
        <div className="footer-inner">
          <span className="msg"><b>{approved} of {langs.length}</b> languages approved{all ? `. Ready to build ${ads} ads.` : "."}</span>
          <Button kind="primary" disabled={!all} icon={<ArrowRight size={17} />} onClick={build}>Build all {ads} ads</Button>
        </div>
      </div>
    </>
  );
}

function LanguageCard({ lang }: { lang: string }) {
  const { view, run, busy, reviewer } = useApp();
  const entry = view.copy[lang];
  const source = view.brief.message_language;
  const isSource = lang === source;
  const markets = view.brief.markets.filter((m) => m.language === lang).map((m) => m.name);
  const [text, setText] = useState(entry.text);
  const [product, setProduct] = useState(view.brief.products[0].id);
  const [format, setFormat] = useState("1x1");
  const [preview, setPreview] = useState<{ image: string; checks: CheckT[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const typed = useDebounced(text, 280);
  const hits = restrictedHits(text, lang, view.brief);
  const dirty = text.trim() !== entry.text;

  useEffect(() => setText(entry.text), [entry.text]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.preview(view.id, product, format, lang, typed.trim() || " ", 640)
      .then((r) => { if (live) { setPreview(r); setLoading(false); } })
      .catch(() => live && setLoading(false));
    return () => { live = false; };
  }, [typed, product, format, view.id, lang]);

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

  const problems = preview?.checks.filter((c) => c.status !== "pass" && ["readable", "fits", "words"].includes(c.id)) ?? [];

  return (
    <section className="card card-pad" style={{ marginBottom: 16 }}>
      <div className="lang-card">
        <div className="lang-main">
          <div className="lang-head">
            <h3>{LANGUAGE_NAMES[lang]}</h3>
            <span className="muted small">{isSource ? "Original" : markets.join(", ")}</span>
            <span className="space" />
            {entry.approved ? <StatusBadge status="pass"><Check size={12} strokeWidth={3} /> Approved</StatusBadge>
              : entry.origin === "edited" ? <StatusBadge status="warn">Edited · needs approval</StatusBadge>
              : <StatusBadge status="warn">Needs approval</StatusBadge>}
          </div>

          {!isSource && (
            <div className="source-line">From {LANGUAGE_NAMES[source]}: <b>{view.copy[source]?.text}</b></div>
          )}
          {entry.approved ? (
            <div className="copy-input copy-locked" lang={lang} aria-label={`${LANGUAGE_NAMES[lang]} message, approved`}>{entry.text}</div>
          ) : (
            <textarea
              className={`textarea copy-input ${hits.length ? "invalid" : ""}`}
              rows={2}
              value={text}
              lang={lang}
              onChange={(e) => setText(e.target.value)}
              onBlur={save}
              aria-label={`${LANGUAGE_NAMES[lang]} message`}
            />
          )}
          {hits.length > 0 && <div className="field-note fail" style={{ marginTop: 6 }}>Legal restricts “{hits.join("”, “")}” in {LANGUAGE_NAMES[lang]}.</div>}
          {!isSource && entry.back_translation && !dirty && (
            <div className="meaning"><b>What it says:</b> {entry.back_translation}</div>
          )}
          {/* The note is for a reviewer who reads the source language; older notes came back in the target language. */}
          {!isSource && entry.note && !dirty && (source !== "en" || !/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(entry.note)) && <div className="note">{entry.note}</div>}

          {problems.length > 0 && (
            <ul className="check-list" style={{ marginTop: 14 }}>
              {problems.map((c) => (
                <li key={c.id} className="check-item"><CheckIconDot status={c.status} /><div><div className="ci-label">{c.label}</div><div className="ci-msg">{c.message}</div></div></li>
              ))}
            </ul>
          )}

          <div className="row lang-actions">
            {entry.approved ? (
              <>
                <span className="muted small">Approved by {entry.approved.by} · {timeAgo(entry.approved.at)}</span>
                <Button kind="ghost" size="sm" icon={<Pencil size={14} />}
                  onClick={async () => { const by = await reviewer(); run(`copy-${lang}`, () => api.reopenCopy(view.id, lang, by)); }}>
                  Edit
                </Button>
              </>
            ) : (
              <>
                <Button kind="approve" icon={<Check size={17} strokeWidth={2.6} />} onClick={approve}
                  busy={busy.has(`approve-copy-${lang}`) || busy.has(`copy-${lang}`)} disabled={!text.trim() || hits.length > 0}>
                  Approve {LANGUAGE_NAMES[lang]}
                </Button>
                {dirty && <Button kind="ghost" onMouseDown={(e) => e.preventDefault()} onClick={() => setText(entry.text)}>Undo changes</Button>}
              </>
            )}
          </div>
        </div>

        <div>
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
            <div className="seg">
              {view.brief.products.map((p) => (
                <button key={p.id} className={p.id === product ? "on" : ""} onClick={() => setProduct(p.id)} title={p.name}>
                  {p.name.split(" ")[0]}
                </button>
              ))}
            </div>
            <div className="seg">
              {Object.entries(view.formats).map(([k, f]) => (
                <button key={k} className={k === format ? "on" : ""} onClick={() => setFormat(k)} title={`${f.label} · ${f.ratio}`}>{f.label.split(" ")[0]}</button>
              ))}
            </div>
          </div>
          <div className={`preview-wrap ${loading ? "loading" : ""}`} style={{ aspectRatio: `${view.formats[format].size[0]} / ${view.formats[format].size[1]}`, width: format === "9x16" ? 236 : "100%", marginInline: "auto" }}>
            {preview && <img src={preview.image} alt={`${LANGUAGE_NAMES[lang]} preview`} />}
            {preview && <Markers checks={preview.checks.filter((c) => ["readable", "fits", "words"].includes(c.id))} />}
          </div>
        </div>
      </div>
    </section>
  );
}
