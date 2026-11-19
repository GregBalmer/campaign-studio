import { useState } from "react";
import { api, ApiError, type DemoAccount, type Person } from "./api";
import { Button } from "./ui";
import { AppMark } from "./App";

/** Stand-in for the client's single sign-on. Approvals are stamped with whoever signs in here. */
export default function SignIn({ demo, onSignedIn }: { demo: DemoAccount[]; onSignedIn: (p: Person) => void }) {
  // For the sample, a demo account is filled in so a walkthrough starts with one click.
  const [email, setEmail] = useState(demo[0]?.email ?? "");
  const [password, setPassword] = useState(demo[0]?.password ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const em = email, pw = password;
    if (!em || !pw) return;
    setBusy(true);
    setError("");
    try {
      const { user } = await api.signIn(em, pw);
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign in. Try again.");
      setBusy(false);
    }
  };

  return (
    <div className="signin">
      <div className="signin-card">
        <div className="signin-brand">
          <span className="wordmark-mark"><AppMark /></span>
          <span className="wordmark">Campaign Studio</span>
          <span className="tagline">Built for Adobe Firefly Services</span>
        </div>
        <h1>Sign in</h1>
        <p className="muted">Every approval is signed with your name and the time.</p>
        <form onSubmit={submit} className="stack" style={{ marginTop: 20 }}>
          <div className="field">
            <label className="label" htmlFor="si-email">Work email</label>
            <input id="si-email" className="input" type="email" autoComplete="username" autoFocus={!demo.length}
              value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label className="label" htmlFor="si-pw">Password</label>
            <input id="si-pw" className="input" type="password" autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <div className="field-note fail" role="alert">{error}</div>}
          <Button kind="primary" size="lg" className="btn-block" type="submit" busy={busy} autoFocus={demo.length > 0}
            disabled={!email || !password}>Sign in</Button>
        </form>

        {demo.length > 0 && (
          <p className="signin-demo muted small">
            A demo account for the sample is filled in{demo.length > 1 && <>. Also try <code>{demo[1].email}</code> ({demo[1].role}), same password</>}.
          </p>
        )}
        <p className="muted small" style={{ marginTop: 24, lineHeight: 1.5 }}>
          In production this is your company's single sign-on (Adobe, Okta or Microsoft).
        </p>
      </div>
    </div>
  );
}
