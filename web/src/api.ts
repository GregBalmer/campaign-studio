// Types and calls for the local Python server. Every mutating call returns the
// full campaign view, so the UI never has to stitch state together.

export type Status = "pass" | "warn" | "fail";

export interface Check {
  id: string;
  label: string;
  status: Status;
  message: string;
  box: [number, number, number, number] | null;
}

export interface Approval {
  by: string;
  at: string;
}

export interface Product {
  id: string;
  name: string;
  description?: string;
  photo?: string;
  photo_focal?: [number, number];
}

export interface Market {
  region: string;
  name: string;
  language: string;
}

export interface Brief {
  campaign: string;
  brand: {
    name: string;
    logo?: string;
    colors: Record<string, string>;
    voice?: string;
  };
  message: string;
  message_language: string;
  audience: string;
  markets: Market[];
  products: Product[];
  mood?: string;
  banned_words?: Record<string, string[]>;
}

export interface ProductState {
  master?: string | null;
  origin?: "supplied" | "generated" | null;
  provider?: string | null;
  model?: string | null;
  prompt?: string | null;
  attempt?: number;
  focal?: [number, number];
  approved?: Approval | null;
  seconds?: number;
  force_generate?: boolean;
  size?: [number, number];
  zone?: [number, number];
}

export interface CopyEntry {
  text: string;
  back_translation: string;
  note: string;
  origin: "source" | "machine" | "edited";
  approved: Approval | null;
}

export interface Frame {
  product: string;
  format: string;
  region: string;
  language: string;
  path: string;
  checks: Check[];
  status: Status;
  stale: boolean;
  rendered_at: string;
  decision: { value: "approved" | "rejected"; by: string; at: string; note: string } | null;
}

export interface FormatSpec {
  label: string;
  ratio: string;
  size: [number, number];
}

export interface LogEntry {
  at: string;
  by: string;
  event: string;
  detail: string;
}

export type Stage = "setup" | "master" | "words" | "review";

export interface View {
  id: string;
  brief: Brief;
  problems: string[];
  stage: Stage;
  provider: "mock" | "openai";
  products: Record<string, ProductState>;
  copy: Record<string, CopyEntry>;
  languages: string[];
  frames: Record<string, Frame>;
  formats: Record<string, FormatSpec>;
  log: LogEntry[];
  sample: boolean;
  has_outputs: boolean;
}

export interface ProviderInfo {
  id: string;
  label: string;
  ready: boolean;
  detail: string;
}

export interface CampaignSummary {
  id: string;
  name: string;
  stage: Stage;
  sample: boolean;
}

export class ApiError extends Error {}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/${path}`, {
      method,
      headers: body instanceof Blob ? {} : { "Content-Type": "application/json" },
      body: body instanceof Blob ? body : body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Can't reach Campaign Studio. Is the window running start.py still open?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `Something went wrong (${res.status}).`);
  return data as T;
}

export const api = {
  status: () => call<{ providers: ProviderInfo[]; default_provider: string }>("GET", "status"),
  saveKey: (key: string) => call<{ providers: ProviderInfo[] }>("POST", "settings/key", { key }),
  campaigns: () => call<CampaignSummary[]>("GET", "campaigns"),
  createCampaign: (name: string) => call<View>("POST", "campaigns", { name }),
  get: (id: string) => call<View>("GET", `campaigns/${id}`),
  reset: (id: string) => call<View>("POST", `campaigns/${id}/reset`),
  patchBrief: (id: string, patch: Partial<Brief>) => call<View>("PATCH", `campaigns/${id}/brief`, patch),
  setProvider: (id: string, provider: string) => call<View>("POST", `campaigns/${id}/provider`, { provider }),
  upload: (id: string, target: string, file: File) =>
    call<View>("POST", `campaigns/${id}/upload?target=${encodeURIComponent(target)}&name=${encodeURIComponent(file.name)}`, file),
  removePhoto: (id: string, pid: string) => call<View>("DELETE", `campaigns/${id}/products/${pid}/photo`),
  setSource: (id: string, pid: string, generate: boolean) =>
    call<View>("POST", `campaigns/${id}/products/${pid}/source`, { generate }),
  makeMaster: (id: string, pid: string, by: string) =>
    call<View>("POST", `campaigns/${id}/products/${pid}/master`, { by }),
  setFocal: (id: string, pid: string, x: number, y: number, w: number, h: number) =>
    call<View>("POST", `campaigns/${id}/products/${pid}/focal`, { x, y, w, h }),
  approveMaster: (id: string, pid: string, by: string) =>
    call<View>("POST", `campaigns/${id}/products/${pid}/approve`, { by }),
  reopenMaster: (id: string, pid: string, by: string) =>
    call<View>("POST", `campaigns/${id}/products/${pid}/reopen`, { by }),
  translate: (id: string, by: string, force = false) => call<View>("POST", `campaigns/${id}/translate`, { by, force }),
  editCopy: (id: string, lang: string, text: string, by: string) =>
    call<View>("POST", `campaigns/${id}/copy/${lang}`, { text, by }),
  reopenCopy: (id: string, lang: string, by: string) =>
    call<View>("POST", `campaigns/${id}/copy/${lang}/reopen`, { by }),
  approveCopy: (id: string, lang: string, by: string) =>
    call<View>("POST", `campaigns/${id}/copy/${lang}/approve`, { by }),
  preview: (id: string, product: string, format: string, lang: string, text?: string, w = 720) =>
    call<{ image: string; checks: Check[] }>(
      "GET",
      `campaigns/${id}/preview?product=${product}&format=${format}&lang=${lang}&w=${w}` +
        (text !== undefined ? `&text=${encodeURIComponent(text)}` : ""),
    ),
  fanOut: (id: string, by: string) => call<View>("POST", `campaigns/${id}/fanout`, { by }),
  decide: (id: string, key: string, decision: "approved" | "rejected" | null, by: string, note = "") =>
    call<View>("POST", `campaigns/${id}/decide`, { key, decision, by, note }),
};

export const masterUrl = (v: View, pid: string) => {
  const ps = v.products[pid];
  return ps?.master ? `/files/workspace/${v.id}/${ps.master}` : null;
};

export const photoUrl = (v: View, p: Product) => (p.photo ? `/files/workspace/${v.id}/${p.photo}` : null);

export const frameUrl = (v: View, f: Frame) => `/files/outputs/${v.id}/${f.path}?v=${encodeURIComponent(f.rendered_at)}`;

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English", ja: "Japanese", de: "German", fr: "French", es: "Spanish", it: "Italian",
  pt: "Portuguese", nl: "Dutch", sv: "Swedish",
};

export const MARKET_PRESETS: Market[] = [
  { region: "US", name: "United States", language: "en" },
  { region: "GB", name: "United Kingdom", language: "en" },
  { region: "JP", name: "Japan", language: "ja" },
  { region: "DE", name: "Germany", language: "de" },
  { region: "FR", name: "France", language: "fr" },
  { region: "ES", name: "Spain", language: "es" },
  { region: "IT", name: "Italy", language: "it" },
  { region: "BR", name: "Brazil", language: "pt" },
  { region: "NL", name: "Netherlands", language: "nl" },
];

export function restrictedHits(text: string, lang: string, brief: Brief): string[] {
  const words = brief.banned_words?.[lang] ?? [];
  const lower = text.toLowerCase();
  return words.filter((w) => {
    if (["ja", "zh", "ko"].includes(lang) || !/^[\p{L}]+$/u.test(w)) return lower.includes(w.toLowerCase());
    return new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(text);
  });
}
