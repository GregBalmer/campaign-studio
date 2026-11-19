import { useState } from "react";
import { Image, Languages } from "lucide-react";
import { api, type ProviderInfo, type ProviderKind, type ProviderLists } from "./api";
import { Button, Drawer, useApp } from "./ui";

// What each service does in the flow, so the choice makes sense before picking one.
const GROUPS: { kind: ProviderKind; title: string; note: string; icon: typeof Image }[] = [
  { kind: "image", title: "Images", icon: Image, note: "Creates a key visual when a product has no photo of its own." },
  { kind: "text", title: "Translation", icon: Languages, note: "Adapts the message for each market. You check it in English before it\u2019s used." },
];

export default function SettingsDrawer({ providers, setProviders, onClose }: {
  providers: ProviderLists;
  setProviders: (p: ProviderLists) => void;
  onClose: () => void;
}) {
  const { view, run, busy } = useApp();
  // Which not-yet-connected row has its form open, as "kind/id".
  const [open, setOpen] = useState<string | null>(null);

  return (
    <Drawer onClose={onClose}>
      <h2>Models</h2>

      {GROUPS.map((g) => (
        <section key={g.kind} className="option-group">
          <h3><span className="option-group-icon"><g.icon size={18} /></span>{g.title}</h3>
          <p className="option-group-note">{g.note}</p>
          {providers[g.kind].map((p) => {
            const rowKey = `${g.kind}/${p.id}`;
            const title = (
              <span>
                <span className="option-title">
                  {p.label}
                  {p.id === "mock" && <span className="badge">Free</span>}
                  {p.id === "firefly" && <span className="badge adobe">For production</span>}
                  {p.id === "firefly-test" && <span className="badge warn">Test</span>}
                </span>
                <span className="option-detail" style={{ display: "block" }}>{p.detail}</span>
              </span>
            );
            if (!p.ready && p.connect) {
              const isOpen = open === rowKey;
              return (
                <div key={p.id} className={`option connectable ${isOpen ? "open" : ""}`}>
                  <button className="option-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : rowKey)}>
                    <span className="radio" />
                    {title}
                    {!isOpen && <span className="connect-link">Connect</span>}
                  </button>
                  {isOpen && <ConnectForm entry={p} setProviders={setProviders} onDone={() => setOpen(null)} />}
                </div>
              );
            }
            return (
              <button
                key={p.id}
                className={`option ${view.providers[g.kind] === p.id ? "on" : ""}`}
                disabled={!p.ready || busy.has("provider")}
                onClick={() => run("provider", () => api.setProvider(view.id, g.kind, p.id))}
              >
                <span className="radio" />
                {title}
              </button>
            );
          })}
        </section>
      ))}
    </Drawer>
  );
}

/** The short form a row opens when its service still needs credentials. */
function ConnectForm({ entry, setProviders, onDone }: {
  entry: ProviderInfo;
  setProviders: (p: ProviderLists) => void;
  onDone: () => void;
}) {
  const { view, run, busy, toast } = useApp();
  const [key, setKey] = useState("");
  const [clientId, setClientId] = useState("");
  const [secret, setSecret] = useState("");

  if (entry.connect === "openai") {
    return (
      <form
        className="connect-form"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await run("key", async () => {
            const r = await api.saveKey(key.trim());
            setProviders(r.providers);
            toast("OpenAI connected.");
            await api.setProvider(view.id, "image", "openai");
            return api.setProvider(view.id, "text", "openai");
          });
          if (ok) onDone();
        }}
      >
        <label className="label" htmlFor="oa-key">API key</label>
        <input id="oa-key" className="input" type="password" autoComplete="off" autoFocus placeholder="sk-…"
          value={key} onChange={(e) => setKey(e.target.value)} />
        <Button kind="primary" className="btn-block" busy={busy.has("key")} disabled={key.trim().length < 20}>
          Connect
        </Button>
        <p className="connect-note">From platform.openai.com. Saved on this computer only.</p>
      </form>
    );
  }

  const test = entry.id === "firefly-test";
  return (
    <form
      className="connect-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run("firefly", async () => {
          const r = await api.saveFirefly(clientId.trim(), secret.trim());
          setProviders(r.providers);
          toast(test ? "Firefly test server connected." : "Firefly connected.");
          return api.setProvider(view.id, "image", "firefly");
        });
        if (ok) onDone();
      }}
    >
      <label className="label" htmlFor="ff-id">Client ID</label>
      <input id="ff-id" className="input" autoComplete="off" autoFocus value={clientId} onChange={(e) => setClientId(e.target.value)} />
      <label className="label" htmlFor="ff-secret">Client secret</label>
      <input id="ff-secret" className="input" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
      <Button kind="primary" className="btn-block" busy={busy.has("firefly")} disabled={!clientId.trim() || !secret.trim()}>
        Connect
      </Button>
      <p className="connect-note">
        {test ? "Checked with the test server, not Adobe." : "Checked with Adobe."} Saved on this computer only.
      </p>
      <details>
        <summary>Where do I find these?</summary>
        <ol>
          <li>Your Adobe admin opens the Adobe Developer Console and your project.</li>
          <li>They add the Firefly Services API.</li>
          <li>They choose OAuth Server-to-Server and send you the client ID and client secret.</li>
        </ol>
      </details>
    </form>
  );
}
