import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check as CheckIcon, Loader2, X } from "lucide-react";
import type { Check, Status, View } from "./api";

// ---------------------------------------------------------------- app context

export interface Ctx {
  view: View;
  setView: (v: View) => void;
  /** Runs an action and tracks it as busy. Errors show as a toast, or in place for long-running work. */
  run: (key: string, fn: () => Promise<View | void>) => Promise<boolean>;
  busy: Set<string>;
  /** Resolves with the reviewer's name, asking for it once if needed. */
  reviewer: () => Promise<string>;
  reviewerName: string;
  toast: (msg: string, kind?: "info" | "error") => void;
  goTo: (step: number) => void;
  /** True when IT has connected a Slack channel for requests. */
  slack: boolean;
  /** Errors that stay where they happened, keyed like `run`'s keys. */
  errors: Record<string, string>;
  retry: (key: string) => void;
  dismissError: (key: string) => void;
}

export const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => {
  const c = useContext(AppCtx);
  if (!c) throw new Error("AppCtx missing");
  return c;
};

// ---------------------------------------------------------------- small pieces

export function Button({
  kind = "secondary", size, busy, icon, children, className = "", ...rest
}: {
  kind?: "primary" | "secondary" | "ghost" | "approve" | "danger";
  size?: "sm" | "lg";
  busy?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`btn btn-${kind} ${size ? `btn-${size}` : ""} ${className}`}
      disabled={busy || rest.disabled}
      {...rest}
    >
      {busy ? <Loader2 size={16} className="spin" /> : icon}
      {children}
    </button>
  );
}

export function StatusBadge({ status, children }: { status: Status | "neutral"; children: ReactNode }) {
  return <span className={`badge ${status === "pass" ? "ok" : status === "neutral" ? "" : status}`}>{children}</span>;
}

export function CheckIconDot({ status }: { status: Status }) {
  return (
    <span className={`check-icon ${status}`}>
      {status === "pass" ? <CheckIcon size={12} strokeWidth={3} /> : status === "warn" ? "!" : <X size={12} strokeWidth={3} />}
    </span>
  );
}

/** Problem boxes drawn on the image itself, numbered to match the list. */
export function Markers({ checks }: { checks: Check[] }) {
  const flagged = checks.filter((c) => c.status !== "pass" && c.box);
  return (
    <>
      {flagged.map((c, i) => {
        const [x0, y0, x1, y1] = c.box!;
        return (
          <div
            key={c.id}
            className={`marker ${c.status}`}
            style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }}
            title={c.message}
          >
            <span className="marker-pin">{i + 1}</span>
          </div>
        );
      })}
    </>
  );
}

export function Modal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEscape(onClose);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">{children}</div>
    </>
  );
}

export function Drawer({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEscape(onClose);
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <button className="btn btn-ghost icon-btn close-x" onClick={onClose} aria-label="Close"><X size={18} /></button>
        {children}
      </aside>
    </>
  );
}

export function useEscape(fn: () => void) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && ref.current();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
}

/** Closes a popover on Escape or on a click anywhere outside `ref`. */
export function useDismiss(ref: React.RefObject<HTMLElement>, active: boolean, close: () => void) {
  const fn = useRef(close);
  fn.current = close;
  useEffect(() => {
    if (!active) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) fn.current();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && fn.current();
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [active, ref]);
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function FormatGlyph({ ratio, h = 26 }: { ratio: string; h?: number }) {
  const [a, b] = ratio.split(":").map(Number);
  const w = Math.round((h * a) / b);
  return <span style={{ width: w > 46 ? 46 : w, height: w > 46 ? Math.round((46 * b) / a) : h }} />;
}

/** A failure that stays put, next to the thing that failed, until it's retried or dismissed. */
/** The next-step panel: top of the right-hand column on every step, so the main
 *  button is always in the same place. */
export function NextPanel({ label, figure, detail, children }: {
  label: string; figure: ReactNode; detail?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="summary-panel">
      <div className="summary-label">{label}</div>
      <div className="summary-figure">{figure}</div>
      {detail && <div className="summary-detail">{detail}</div>}
      {children}
    </section>
  );
}

export function ErrorNote({ k, action = "Try again" }: { k: string; action?: string }) {
  const { errors, retry, dismissError, busy } = useApp();
  const msg = errors[k];
  if (!msg) return null;
  return (
    <div className="error-note" role="alert">
      <AlertTriangle size={16} />
      <span>{msg}</span>
      <div className="error-note-actions">
        <Button size="sm" busy={busy.has(k)} onClick={() => retry(k)}>{action}</Button>
        <button className="error-note-close" aria-label="Dismiss" onClick={() => dismissError(k)}><X size={15} /></button>
      </div>
    </div>
  );
}
