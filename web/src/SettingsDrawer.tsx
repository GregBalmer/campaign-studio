import { useState } from "react";
import { Check, Cloud, Image, Languages } from "lucide-react";
import { api, ApiError, type ProviderInfo, type ProviderKind, type ProviderLists } from "./api";
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
      <h2>Services</h2>

      {GROUPS.map((g) => (
        <section key={g.kind} className="option-group">
          <h3><span className="option-group-icon"><g.icon size={22} strokeWidth={1.75} /></span>{g.title}</h3>
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

      <StorageGroup />
    </Drawer>
  );
}

/** Where the finished ads go. This computer always; Azure as well once a container link is pasted. */
function StorageGroup() {
  const { storage, setStorage, toast } = useApp();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const until = storage.expires ? new Date(storage.expires).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : null;

  const connect = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api.connectAzure(link.trim());
      setStorage(r.storage); setLink(""); setOpen(false);
      toast(storage.test ? "Azure test server connected." : "Azure connected.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't connect. Try again.");
    } finally { setBusy(false); }
  };
  const disconnect = async () => {
    try { setStorage((await api.disconnectAzure()).storage); toast("Azure disconnected."); }
    catch (err) { toast(err instanceof ApiError ? err.message : "Couldn't disconnect.", "error"); }
  };

  return (
    <section className="option-group">
      <h3><span className="option-group-icon"><Cloud size={22} strokeWidth={1.75} /></span>Storage</h3>
      <p className="option-group-note">Where the finished ads are saved, by product and size.</p>
      <div className="option on static">
        <span className="tick"><Check size={14} strokeWidth={3} /></span>
        <span>
          <span className="option-title">This computer <span className="badge">Always</span></span>
          <span className="option-detail" style={{ display: "block" }}>Every ad, in the outputs folder.</span>
        </span>
      </div>
      {storage.connected ? (
        <div className="option on static">
          <span className="tick"><Check size={14} strokeWidth={3} /></span>
          <span style={{ flex: 1 }}>
            <span className="option-title">Azure Blob Storage{storage.test && <span className="badge warn">Test</span>}</span>
            <span className="option-detail" style={{ display: "block" }}>
              Approved ads can be sent to <b>{storage.account}/{storage.container}</b>{until && <>. Link works until {until}</>}.
            </span>
          </span>
          <button className="connect-link" onClick={disconnect}>Disconnect</button>
        </div>
      ) : (
        <div className={`option connectable ${open ? "open" : ""}`}>
          <button className="option-head" aria-expanded={open} onClick={() => setOpen(!open)}>
            <span className="tick off" />
            <span>
              <span className="option-title">Azure Blob Storage</span>
              <span className="option-detail" style={{ display: "block" }}>Also send the approved ads to your company's Azure storage.</span>
            </span>
            {!open && <span className="connect-link">Connect</span>}
          </button>
          {open && (
            <form className="connect-form" onSubmit={connect}>
              <label className="label" htmlFor="az-link">Container SAS link</label>
              <input id="az-link" className="input" type="password" autoComplete="off" autoFocus
                placeholder="https://….blob.core.windows.net/…?sv=…" value={link} onChange={(e) => setLink(e.target.value)} />
              {error && <p className="field-note fail" style={{ margin: "6px 0 0" }}>{error}</p>}
              <Button kind="primary" className="btn-block" busy={busy} disabled={!link.trim()}>Connect</Button>
              <p className="connect-note">Checked by saving one small file to the container. Saved on this computer only.</p>
              <details>
                <summary>Where do I find this?</summary>
                <ol>
                  <li>In the Azure portal, open your storage account, then the container.</li>
                  <li>Choose <b>Shared access tokens</b>.</li>
                  <li>Tick <b>Create</b> and <b>Write</b>, set an end date, and generate it.</li>
                  <li>Copy the <b>Blob SAS URL</b>.</li>
                </ol>
              </details>
            </form>
          )}
        </div>
      )}
    </section>
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
