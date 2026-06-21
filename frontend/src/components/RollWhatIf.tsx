import { useEffect, useMemo, useState } from "react";
import { fetchRollWhatIf, fetchPriceOption, fetchSuggestCall } from "../api";
import useIsMobile from "../hooks/useIsMobile";
import type { PortfolioResponse, PositionRow, RollWhatIfResult, MarginLevel } from "../types";

const FONT_SCALE = 10 / 16;
const fs = (px: number) => `${+(px * FONT_SCALE).toFixed(3)}pt`;
const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

const LEVEL_STYLE: Record<MarginLevel, { fg: string; bg: string; border: string; label: string }> = {
  safe: { fg: "#1f7a4d", bg: "#e8f6ee", border: "#bfe3cd", label: "安全" },
  warning: { fg: "#8a5a00", bg: "#fff4e0", border: "#f0d29a", label: "注意" },
  danger: { fg: "#b3261e", bg: "#fde8e6", border: "#f3b8b2", label: "危險" },
};

const muted = "#5a7a9a", border = "#d8e0ea", text = "#1a2a3a", accent = "#2a6fb8", card = "#ffffff", mono = "'JetBrains Mono','Fira Code',monospace";

// Replacement long-call defaults: a longer-dated (~180 DTE) call whose delta
// replicates the short put's, floored at 0.85 so the call stays comfortably ITM.
const CALL_DTE = 180;
const CALL_MIN_DELTA = 0.85;

// Mirror of calc.regt_short_put_maint for an at-a-glance preview of the
// auto-derived MM_SP fallback (the backend is authoritative on submit).
const regtShortPutMaint = (contracts: number, S: number, K: number, putMark: number) =>
  Math.abs(contracts) * 100 * (Math.max(0.2 * S - Math.max(S - K, 0), 0.1 * K) + putMark);

// Every short put is offered. The live `mark` may be null (no quote / no OPRA
// feed); in that case the panel model-prices the leg off its IV, so we do NOT
// require `mark` here — only that it's a short put position.
const isShortPut = (p: PositionRow) => p.type === "POPT" && p.quantity < 0 && p.strike !== null;

const num = (s: string): number => {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : 0;
};

const LevelChip = ({ level }: { level: MarginLevel }) => (
  <span style={{ background: LEVEL_STYLE[level].bg, border: `1px solid ${LEVEL_STYLE[level].border}`, color: LEVEL_STYLE[level].fg, borderRadius: 3, padding: "1px 8px", fontSize: fs(15), fontWeight: 700 }}>
    {LEVEL_STYLE[level].label}
  </span>
);

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
    <span style={{ fontSize: fs(15), color: muted, letterSpacing: "0.06em" }}>{label}</span>
    {children}
  </label>
);

const inputStyle: React.CSSProperties = {
  fontFamily: mono, fontSize: fs(18), padding: "4px 8px", border: `1px solid ${border}`,
  borderRadius: 3, color: text, width: 110, background: "#fff",
};

const linkBtn: React.CSSProperties = {
  background: "transparent", border: "none", color: accent, fontFamily: mono,
  fontSize: fs(15), cursor: "pointer", padding: 0, textDecoration: "underline",
};

export default function RollWhatIf({ data }: { data: PortfolioResponse }) {
  const isMobile = useIsMobile();
  const pad = isMobile ? 12 : 24;
  const [open, setOpen] = useState(false);
  const [spIdx, setSpIdx] = useState(0);
  const [repl, setRepl] = useState<"call" | "etf">("call");
  // Short-put mark: live when available, else model-priced off its IV.
  const [spMark, setSpMark] = useState<number | null>(null);
  const [spMarkSource, setSpMarkSource] = useState<"市場" | "模型" | null>(null);
  // Long-call leg (premium can be filled by the model from strike/expiry/IV).
  const [callStrike, setCallStrike] = useState("");
  const [callDays, setCallDays] = useState("");
  const [callIv, setCallIv] = useState("");
  const [callMark, setCallMark] = useState("");
  const [callQty, setCallQty] = useState("");
  const [callDelta, setCallDelta] = useState<number | null>(null);
  const [callPricing, setCallPricing] = useState(false);
  const [etfValue, setEtfValue] = useState("");
  const [etfRate, setEtfRate] = useState("0.5");
  const [mmOverride, setMmOverride] = useState("");
  const [result, setResult] = useState<RollWhatIfResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Listed alphabetically by label (asc) for a stable, scannable order.
  const shortPuts = useMemo(
    () => data.positions.filter(isShortPut).sort((a, b) => a.label.localeCompare(b.label)),
    [data.positions],
  );
  const sp = shortPuts[spIdx];

  // When the selected short put changes: resolve its mark (live or model),
  // default Q to the SP's own contract count, and pre-fill the long-call leg.
  // The call defaults to ~180 DTE with a strike whose model delta replicates
  // the SP's (floored at 0.85), priced off the SP's IV — every manually-editable
  // field thus starts from a model default the user can override.
  useEffect(() => {
    if (!sp) { setSpMark(null); setSpMarkSource(null); return; }
    setResult(null);
    setError(null);
    const S = sp.underlying_price, K = sp.strike as number;
    const days = sp.daysToExpiry ?? 30, iv = sp.iv ?? 50;
    setCallDays(String(CALL_DTE));
    setCallIv(String(+iv.toFixed(1)));
    setCallQty(String(Math.abs(sp.quantity)));
    setCallStrike(""); setCallMark(""); setCallDelta(null);
    let cancelled = false;

    if (sp.mark !== null) {
      setSpMark(sp.mark);
      setSpMarkSource("市場");
    } else {
      setSpMark(null);
      setSpMarkSource(null);
      fetchPriceOption({ underlyingPrice: S, strike: K, daysToExpiry: Math.max(1, Math.round(days)), right: "P", iv })
        .then((r) => { if (!cancelled) { setSpMark(r.mark); setSpMarkSource("模型"); } })
        .catch((e: Error) => { if (!cancelled) setError(`無法估算 SP 價格：${e.message}`); });
    }

    // Suggest a replacement call strike at the target delta, then price it.
    fetchSuggestCall({ underlyingPrice: S, shortPutDelta: sp.delta ?? 0, iv, daysToExpiry: CALL_DTE, minDelta: CALL_MIN_DELTA })
      .then((r) => { if (!cancelled) { setCallStrike(String(r.strike)); setCallDays(String(r.daysToExpiry)); setCallMark(r.mark.toFixed(2)); setCallDelta(r.delta); } })
      .catch((e: Error) => { if (!cancelled) setError(`無法建議 Call 履約價：${e.message}`); });

    return () => { cancelled = true; };
  }, [sp]);

  const derived = useMemo(() => {
    if (!sp || spMark === null) return null;
    const contracts = Math.abs(sp.quantity);
    const S = sp.underlying_price, K = sp.strike as number, P = spMark;
    return { contracts, S, K, P, debit: P * 100 * contracts, regt: regtShortPutMaint(contracts, S, K, P) };
  }, [sp, spMark]);

  // Re-price the call at the strike/DTE/IV currently in the fields.
  const estimateCall = () => {
    if (!sp) return;
    setCallPricing(true);
    setError(null);
    fetchPriceOption({
      underlyingPrice: sp.underlying_price,
      strike: num(callStrike),
      daysToExpiry: Math.max(1, Math.round(num(callDays))),
      right: "C",
      iv: num(callIv),
    })
      .then((r) => { setCallMark(r.mark.toFixed(2)); setCallDelta(r.delta); })
      .catch((e: Error) => setError(`無法估算 Call 價格：${e.message}`))
      .finally(() => setCallPricing(false));
  };

  // Re-derive the strike for the target delta at the current DTE/IV, then price.
  const suggestStrike = () => {
    if (!sp) return;
    setCallPricing(true);
    setError(null);
    fetchSuggestCall({
      underlyingPrice: sp.underlying_price,
      shortPutDelta: sp.delta ?? 0,
      iv: num(callIv),
      daysToExpiry: Math.max(1, Math.round(num(callDays))),
      minDelta: CALL_MIN_DELTA,
    })
      .then((r) => { setCallStrike(String(r.strike)); setCallMark(r.mark.toFixed(2)); setCallDelta(r.delta); })
      .catch((e: Error) => setError(`無法建議 Call 履約價：${e.message}`))
      .finally(() => setCallPricing(false));
  };

  // Size the call to match the short put's current delta exposure
  // (calc.exposure_match_sizing): Q = E_target / (100 * S * call_delta).
  const matchExposure = () => {
    if (!sp || !derived || callDelta === null || callDelta === 0) return;
    const eTarget = derived.contracts * 100 * derived.S * Math.abs(sp.delta ?? 0);
    setCallQty((eTarget / (100 * derived.S * callDelta)).toFixed(2));
  };

  const submit = () => {
    if (!sp || !derived || !data.margin) return;
    setLoading(true);
    setError(null);
    const premium = repl === "call" ? num(callMark) * 100 * num(callQty) : 0;
    fetchRollWhatIf({
      excessLiquidity: data.margin.excessLiquidity,
      nlv: data.nlv,
      cash: data.margin.cash,
      availableFunds: data.margin.availableFunds,
      spContracts: derived.contracts,
      spUnderlyingPrice: derived.S,
      spStrike: derived.K,
      spPutMark: derived.P,
      mmSpOverride: mmOverride.trim() === "" ? undefined : num(mmOverride),
      openCallPremium: premium,
      openEtfValue: repl === "etf" ? num(etfValue) : 0,
      etfMaintRate: repl === "etf" ? num(etfRate) : 0.5,
    })
      .then(setResult)
      .catch((e: Error) => { setError(e.message); setResult(null); })
      .finally(() => setLoading(false));
  };

  const headerBtn = (
    <div style={{ display: "flex", justifyContent: "center", padding: `10px ${pad}px 0` }}>
      <button onClick={() => setOpen((o) => !o)} style={{ background: "transparent", border: `1px solid ${border}`, color: muted, fontFamily: mono, fontSize: fs(18), letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>
        {open ? "▾" : "▸"} 換倉試算 Roll What-If
      </button>
    </div>
  );

  if (!open) return headerBtn;

  return (
    <>
      {headerBtn}
      <div style={{ display: "flex", justifyContent: "center", padding: `8px ${pad}px 0` }}>
        <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: isMobile ? "14px 14px" : "14px 24px", maxWidth: 920, width: "100%" }}>
          {!data.margin ? (
            <div style={{ color: muted, fontSize: fs(18) }}>無保證金資料(可能為現金帳戶),無法試算。</div>
          ) : shortPuts.length === 0 ? (
            <div style={{ color: muted, fontSize: fs(18) }}>目前沒有 short put 倉位可供換倉試算。</div>
          ) : (
            <>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 18, alignItems: "flex-end" }}>
                <Field label="要平倉的 Short Put">
                  <select value={spIdx} onChange={(e) => setSpIdx(+e.target.value)} style={{ ...inputStyle, width: 230 }}>
                    {shortPuts.map((p, i) => (
                      <option key={`${p.label}-${i}`} value={i}>{p.label} ×{Math.abs(p.quantity)}</option>
                    ))}
                  </select>
                </Field>
                {sp && (
                  <div style={{ fontSize: fs(15), color: muted, lineHeight: 1.6 }}>
                    S ${fmt(sp.underlying_price, 2)} · K ${fmt(sp.strike as number, 2)} · IV {sp.iv !== null ? sp.iv.toFixed(1) + "%" : "—"} · {sp.daysToExpiry ?? "—"}天<br />
                    {derived
                      ? <>Put 價 ${fmt(derived.P, 2)} <span style={{ color: spMarkSource === "模型" ? "#b8730a" : "#1f7a4d" }}>({spMarkSource})</span> · 平倉借方 D ${fmt(derived.debit)} · Reg T MM≈${fmt(derived.regt)}</>
                      : <span>估算 Put 價格中…</span>}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", gap: 10, margin: "14px 0 8px" }}>
                {([["call", "改開 Long Call"], ["etf", "改買 2x ETF"]] as const).map(([v, l]) => (
                  <button key={v} onClick={() => { setRepl(v); setResult(null); }} style={{ background: repl === v ? accent : "transparent", border: `1px solid ${repl === v ? accent : border}`, color: repl === v ? "#fff" : muted, fontFamily: mono, fontSize: fs(17), padding: "4px 14px", borderRadius: 3, cursor: "pointer" }}>{l}</button>
                ))}
              </div>

              {repl === "call" ? (
                <>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end" }}>
                    <Field label="Call 履約價 K"><input style={inputStyle} value={callStrike} onChange={(e) => setCallStrike(e.target.value)} inputMode="decimal" /></Field>
                    <Field label="到期天數"><input style={inputStyle} value={callDays} onChange={(e) => setCallDays(e.target.value)} inputMode="decimal" /></Field>
                    <Field label="IV (%)"><input style={inputStyle} value={callIv} onChange={(e) => setCallIv(e.target.value)} inputMode="decimal" /></Field>
                    <button onClick={suggestStrike} disabled={callPricing} style={{ background: "#eef4fb", border: `1px solid ${border}`, color: accent, padding: "6px 12px", borderRadius: 3, cursor: callPricing ? "default" : "pointer", fontFamily: mono, fontSize: fs(16), alignSelf: "flex-end" }}>{callPricing ? "…" : "依 Δ 建議履約價"}</button>
                    <button onClick={estimateCall} disabled={callPricing} style={{ background: "#eef4fb", border: `1px solid ${border}`, color: accent, padding: "6px 12px", borderRadius: 3, cursor: callPricing ? "default" : "pointer", fontFamily: mono, fontSize: fs(16), alignSelf: "flex-end" }}>{callPricing ? "…" : "依模型估算 Call"}</button>
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end", marginTop: 10 }}>
                    <Field label="Call Mark (每股 $)"><input style={inputStyle} value={callMark} onChange={(e) => setCallMark(e.target.value)} inputMode="decimal" placeholder="模型/手動" /></Field>
                    <Field label="Call 口數 Q"><input style={inputStyle} value={callQty} onChange={(e) => setCallQty(e.target.value)} inputMode="decimal" /></Field>
                    <div style={{ fontSize: fs(15), color: muted, alignSelf: "center", lineHeight: 1.6 }}>
                      權利金 ${fmt(num(callMark) * 100 * num(callQty))}
                      {callDelta !== null && <> · Δ {callDelta.toFixed(3)} · <button style={linkBtn} onClick={matchExposure}>依曝險配對口數</button></>}
                    </div>
                  </div>
                </>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end" }}>
                  <Field label="ETF 市值 V ($)"><input style={inputStyle} value={etfValue} onChange={(e) => setEtfValue(e.target.value)} inputMode="decimal" placeholder="例如 20000" /></Field>
                  <Field label="ETF 維持率 m"><input style={inputStyle} value={etfRate} onChange={(e) => setEtfRate(e.target.value)} inputMode="decimal" /></Field>
                </div>
              )}

              <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end", marginTop: 12 }}>
                <Field label="MM_SP 覆寫 (留空=Reg T)"><input style={{ ...inputStyle, width: 150 }} value={mmOverride} onChange={(e) => setMmOverride(e.target.value)} inputMode="decimal" placeholder="TWS What-If 值" /></Field>
                <button onClick={submit} disabled={loading || !derived} style={{ background: accent, color: "#fff", border: "none", padding: "7px 20px", borderRadius: 4, cursor: loading || !derived ? "default" : "pointer", fontFamily: mono, fontSize: fs(18), opacity: loading || !derived ? 0.6 : 1 }}>{loading ? "試算中…" : "試算"}</button>
              </div>

              {error && <div style={{ color: LEVEL_STYLE.danger.fg, fontSize: fs(17), marginTop: 12 }}>⚠ {error}</div>}

              {result && (
                <div style={{ marginTop: 16, borderTop: `1px solid ${border}`, paddingTop: 14, display: "flex", flexWrap: "wrap", gap: 28 }}>
                  <div>
                    <div style={{ fontSize: fs(15), color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>保證金緩衝 (換倉前 → 後)</div>
                    <div style={{ fontSize: fs(19), color: text, display: "flex", alignItems: "center", gap: 8 }}>
                      <LevelChip level={result.levelBefore} /> → <LevelChip level={result.levelAfter} />
                    </div>
                    <div style={{ fontSize: fs(16), color: muted, marginTop: 6, lineHeight: 1.7 }}>
                      Excess Liq: ${fmt(result.excessLiquidityBefore)} → <b style={{ color: LEVEL_STYLE[result.levelAfter].fg }}>${fmt(result.excessLiquidityAfter)}</b><br />
                      Cushion: {(result.cushionBefore * 100).toFixed(1)}% → <b style={{ color: LEVEL_STYLE[result.levelAfter].fg }}>{(result.cushionAfter * 100).toFixed(1)}%</b><br />
                      MM_SP 釋放: +${fmt(result.mmSp)} {result.mmSpAuto ? "(Reg T 估算)" : "(手動覆寫)"}
                    </div>
                  </div>

                  {result.canExecute !== undefined && (
                    <div>
                      <div style={{ fontSize: fs(15), color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>換倉資金可行性</div>
                      <div style={{ fontSize: fs(20), fontWeight: 700, color: result.canExecute ? LEVEL_STYLE.safe.fg : LEVEL_STYLE.danger.fg }}>
                        {result.canExecute ? "✓ 資金足夠執行" : `✗ 資金不足,缺口 $${fmt(result.shortfall ?? 0)}`}
                      </div>
                      <div style={{ fontSize: fs(16), color: muted, marginTop: 6, lineHeight: 1.7 }}>
                        現金流出 (買回 SP + 權利金/ETF): ${fmt(result.fundingOutflow ?? 0)}<br />
                        盈餘 Surplus: <b style={{ color: (result.surplus ?? 0) >= 0 ? LEVEL_STYLE.safe.fg : LEVEL_STYLE.danger.fg }}>${fmt(result.surplus ?? 0)}</b>
                        {result.availableFundsAfter !== undefined && <><br />Avail Funds 換倉後 ≈ ${fmt(result.availableFundsAfter)}</>}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div style={{ fontSize: fs(14), color: "#90a4b8", marginTop: 14, lineHeight: 1.6 }}>
                ⚠ 數量級參考,非精確值。模型估算的 Put/Call 價以 Black-Scholes + IV 推得(無即時報價時的備援);MM_SP 是最脆弱輸入,建議以 TWS What-If 覆寫。IBKR 實際用 TIMS/SPAN 情境模型(尤其 Portfolio Margin 整戶非線性)。
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
