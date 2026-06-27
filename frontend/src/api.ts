import type { PortfolioResponse, RollWhatIfRequest, RollWhatIfResult, PriceOptionRequest, PriceOptionResult, SuggestCallRequest, SuggestCallResult, SpxHedgeRequest, SpxHedgeResult } from "./types";

export async function fetchPortfolio(): Promise<PortfolioResponse> {
  const res = await fetch("/api/portfolio");
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}

export async function fetchRollWhatIf(req: RollWhatIfRequest): Promise<RollWhatIfResult> {
  const res = await fetch("/api/roll-what-if", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}

export async function fetchPriceOption(req: PriceOptionRequest): Promise<PriceOptionResult> {
  const res = await fetch("/api/price-option", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}

export async function fetchSuggestCall(req: SuggestCallRequest): Promise<SuggestCallResult> {
  const res = await fetch("/api/suggest-call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}

export async function fetchSpxHedge(req: SpxHedgeRequest): Promise<SpxHedgeResult> {
  const res = await fetch("/api/spx-hedge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}
