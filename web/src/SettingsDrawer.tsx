import { useState } from "react";
import { KeyRound, Lock } from "lucide-react";
import { api, type ProviderInfo } from "./api";
import { Button, Drawer, useApp } from "./ui";

export default function SettingsDrawer({ providers, setProviders, onClose }: {
  providers: ProviderInfo[];
  setProviders: (p: ProviderInfo[]) => void;
  onClose: () => void;
}) {
  const { view, run, busy, toast } = useApp();
  const [key, setKey] = useState("");
  const openai = providers.find((p) => p.id === "openai");

  const pick = (id: string) => run("provider", () => api.setProvider(view.id, id));

  return (
    <Drawer onClose={onClose}>
      <h2>Image generator</h2>
      <p className="muted small" style={{ marginTop: 0, lineHeight: 1.5 }}>
        Which service creates key visuals and translates the message. Your team sees the same steps either way.
      </p>

      {providers.map((p) => (
        <button
          key={p.id}
          className={`option ${view.provider === p.id ? "on" : ""}`}
          disabled={!p.ready || busy.has("provider")}
          onClick={() => pick(p.id)}
        >
          <span className="radio" />
          <span>
            <span className="option-title">{p.label}{p.id === "mock" && <span className="badge">Free</span>}</span>
            <span className="option-detail" style={{ display: "block" }}>{p.detail}</span>
          </span>
        </button>
      ))}

      <button className="option" disabled>
        <span className="radio" />
        <span>
          <span className="option-title">Adobe Firefly <Lock size={13} /></span>
          <span className="option-detail" style={{ display: "block" }}>
            Commercially safe images from your company's Firefly Services licence. Connected by your Adobe team
            during setup, with your organisation's credentials.
          </span>
        </span>
      </button>

      {!openai?.ready && (
        <div className="card card-pad" style={{ marginTop: 24, boxShadow: "none" }}>
          <div className="card-title"><span className="row"><KeyRound size={16} /> Connect OpenAI</span></div>
          <p className="card-hint">
            Paste an API key from platform.openai.com. It's checked, then saved on this computer only, in the
            project's <code>.env</code> file.
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              await run("key", async () => {
                const r = await api.saveKey(key.trim());
                setProviders(r.providers);
                setKey("");
                toast("OpenAI connected.");
                return api.setProvider(view.id, "openai");
              });
            }}
          >
            <input
              className="input"
              type="password"
              autoComplete="off"
              placeholder="sk-…"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <Button kind="primary" className="btn-block" style={{ marginTop: 12 }} busy={busy.has("key")} disabled={key.trim().length < 20}>
              Check and save
            </Button>
          </form>
        </div>
      )}
    </Drawer>
  );
}
