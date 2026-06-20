import type { PortfolioResponse } from "./types";

export async function fetchPortfolio(): Promise<PortfolioResponse> {
  const res = await fetch("/api/portfolio");
  if (!res.ok) {
    const body = await res.json().catch(() => ({} as { detail?: string }));
    throw new Error(body.detail ?? `請求失敗 (${res.status})`);
  }
  return res.json();
}
