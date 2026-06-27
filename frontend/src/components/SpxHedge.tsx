import { useEffect, useState } from "react";
import { fetchSpxHedge } from "../api";
import useIsMobile from "../hooks/useIsMobile";
import type { HedgeLeg, HedgeProposal, PortfolioResponse, SpxHedgeResult } from "../types";

const FONT_SCALE = 10 / 16;
const fs = (px: number) => `${+(px * FONT_SCALE).toFixed(3)}pt`;
const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

const muted = "#5a7a9a", border = "#d8e0ea", text = "#1a2a3a", accent = "#2a6fb8", card = "#ffffff", mono = "'JetBrains Mono','Fira Code',monospace";
const danger = "#b3261e", safe = "#1f7a4d", credit = "#b8730a";

const num = (s: string): number => {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : 0;
};

const KIND_LABEL: Record<HedgeProposal["kind"], string> = {
  long_put: "傳統長 Put",
  vertical: "垂直價差 Put",
  seagull: "海鷗 (零成本)",
};
const KIND_DESC: Record<HedgeProposal["kind"], string> = {
  long_put: "買進 Put,下方全保護、成本最高",
  vertical: "買高賣低 Put,成本較低、保護封頂",
  seagull: "買Put+賣低Put+賣Call,信用沖抵≈零成本、封頂上行",
};

const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 3 }}>
    <span style={{ fontSize: fs(15), color: muted, letterSpacing: "0.06em" }}>{label}</span>
    {children}
  </label>
);

const inputStyle: React.CSSProperties = {
  fontFamily: mono, fontSize: fs(18), padding: "4px 8px", border: `1px solid ${border}`,
  borderRadius: 3, color: text, width: 96, background: "#fff",
};

const pct = (strike: number, spx: number): string => {
  if (!(spx > 0)) return "";
  const p = ((strike - spx) / spx) * 100;
  return `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`;
};

const legText = (l: HedgeLeg, spx: number): string => {
  const side = l.contracts >= 0 ? "買" : "賣";
  const qty = Math.abs(l.contracts);
  return `${side} ${fmt(qty)} 口 SPX ${fmt(l.strike)}${l.right} (${pct(l.strike, spx)})`;
};

function ProposalCard({ p, spxLevel, targetLeverage }: { p: HedgeProposal; spxLevel: number; targetLeverage: number | null }) {
  const target = targetLeverage ?? Infinity;
  // Honest read of the shared-N sizing: only the leg-mix that nets enough negative
  // delta actually reaches the target. Above target = misses the goal (red); below
  // zero = over-hedged (orange note); otherwise meets it (green).
  const missed = p.contracts > 0 && p.leverageAfter > target;
  const over = p.netExposureAfter < 0;
  const levColor = missed ? danger : over ? credit : safe;
  const costColor = p.cost > 0 ? text : safe; // credit (≤0) is green
  return (
    <div style={{ flex: "1 1 240px", minWidth: 220, border: `1px solid ${border}`, borderRadius: 4, padding: "12px 14px", background: "#fbfdff" }}>
      <div style={{ fontSize: fs(18), fontWeight: 700, color: accent }}>{KIND_LABEL[p.kind]}</div>
      <div style={{ fontSize: fs(13.5), color: muted, marginTop: 2, lineHeight: 1.5, minHeight: 30 }}>{KIND_DESC[p.kind]}</div>

      <div style={{ fontFamily: mono, fontSize: fs(16.5), color: text, marginTop: 10, lineHeight: 1.85 }}>
        {p.contracts === 0
          ? <span style={{ color: muted }}>毋需避險(已低於目標槓桿)</span>
          : p.legs.map((l, i) => (
              <div key={i} style={{ color: l.contracts >= 0 ? text : credit }}>
                {legText(l, spxLevel)} <span style={{ color: muted }}>· Δ{l.delta.toFixed(2)} · ${fmt(l.price, 2)}</span>
              </div>
            ))}
      </div>

      <div style={{ fontSize: fs(15.5), color: muted, marginTop: 10, lineHeight: 1.8, borderTop: `1px solid ${border}`, paddingTop: 8 }}>
        淨成本: <b style={{ color: costColor }}>{p.cost < 0 ? "+" : ""}${fmt(Math.abs(p.cost))}</b>{p.cost <= 0 && p.contracts > 0 ? "(信用)" : ""}<br />
        對沖後槓桿: {p.leverageBefore.toFixed(2)}× → <b style={{ color: levColor }}>{p.leverageAfter.toFixed(2)}×</b>{missed ? "(未達目標)" : over ? "(超額)" : ""}<br />
        {p.protectionFloor != null && <>保護下限: {fmt(p.protectionFloor)}{p.protectionFloor < spxLevel ? `(−${(((spxLevel - p.protectionFloor) / spxLevel) * 100).toFixed(1)}%)` : ""}<br /></>}
        {p.upsideCap != null && <>上行封頂: {fmt(p.upsideCap)}{p.upsideCap > spxLevel ? `(+${(((p.upsideCap - spxLevel) / spxLevel) * 100).toFixed(1)}%)` : ""}<br /></>}
        {p.maxProtection != null && <span style={{ color: "#90a4b8" }}>價差最大保護 ${fmt(p.maxProtection)}</span>}
      </div>
    </div>
  );
}

export default function SpxHedge({ data }: { data: PortfolioResponse }) {
  const isMobile = useIsMobile();
  const pad = isMobile ? 12 : 24;
  const [open, setOpen] = useState(false);
  // Defaults mirror config.json spx_hedge; the user can override per-run. The
  // default suggestion sizes the minimum hedge to bring leverage under
  // targetLeverage (1.0×) using a near-dated put (DTE ≤ 30).
  const [targetLeverage, setTargetLeverage] = useState("1.0");
  const [targetDelta, setTargetDelta] = useState("0.30");
  const [floorDelta, setFloorDelta] = useState("0.12");
  const [dte, setDte] = useState("30");
  const [iv, setIv] = useState("20");
  const [result, setResult] = useState<SpxHedgeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const netExposure = data.netBetaWeightedExposure;

  const submit = () => {
    setLoading(true);
    setError(null);
    fetchSpxHedge({
      netExposure,
      nlv: data.nlv,
      targetLeverage: num(targetLeverage),
      targetDelta: num(targetDelta),
      floorDelta: num(floorDelta),
      targetDte: Math.max(1, Math.round(num(dte))),
      assumedIv: num(iv),
      spxLevel: data.spxLevel > 0 ? data.spxLevel : undefined,
    })
      .then(setResult)
      .catch((e: Error) => { setError(e.message); setResult(null); })
      .finally(() => setLoading(false));
  };

  // Auto-run the default suggestion the first time the panel is opened, so the
  // user sees the three concrete proposals without clicking.
  useEffect(() => {
    if (open && !result && !loading && !error) submit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const headerBtn = (
    <div style={{ display: "flex", justifyContent: "center", padding: `10px ${pad}px 0` }}>
      <button onClick={() => setOpen((o) => !o)} style={{ background: "transparent", border: `1px solid ${border}`, color: muted, fontFamily: mono, fontSize: fs(18), letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>
        {open ? "▾" : "▸"} SPX 避險試算 Hedge What-If
      </button>
    </div>
  );

  if (!open) return headerBtn;

  return (
    <>
      {headerBtn}
      <div style={{ display: "flex", justifyContent: "center", padding: `8px ${pad}px 0` }}>
        <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: isMobile ? "14px 14px" : "14px 24px", maxWidth: 1040, width: "100%" }}>
          <div style={{ fontSize: fs(16), color: muted, lineHeight: 1.7, marginBottom: 12 }}>
            Beta 加權淨曝險: <b style={{ color: text }}>${fmt(netExposure)}</b>
            {" "}({(data.betaWeightedLeverage).toFixed(2)}× NLV) · SPX {result ? `≈ ${fmt(result.spxLevel, 2)}` : data.spxLevel > 0 ? `≈ ${fmt(data.spxLevel, 2)}` : "—"}
            {result && <> · {result.dte} 天到期 · IV {fmt(result.iv, 1)}% · <span style={{ color: result.source === "model" ? credit : safe }}>{result.source === "model" ? "模型定價" : "現價快照"}{result.cachedAt ? `(${result.cachedAt.slice(5, 16).replace("T", " ")})` : ""}</span></>}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end" }}>
            <Field label="目標槓桿 (×NLV)"><input style={inputStyle} value={targetLeverage} onChange={(e) => setTargetLeverage(e.target.value)} inputMode="decimal" /></Field>
            <Field label="Put Δ 目標"><input style={inputStyle} value={targetDelta} onChange={(e) => setTargetDelta(e.target.value)} inputMode="decimal" /></Field>
            <Field label="下緣 Put Δ"><input style={inputStyle} value={floorDelta} onChange={(e) => setFloorDelta(e.target.value)} inputMode="decimal" /></Field>
            <Field label="到期天數 DTE ≤"><input style={inputStyle} value={dte} onChange={(e) => setDte(e.target.value)} inputMode="decimal" /></Field>
            <Field label="假設 IV (%)"><input style={inputStyle} value={iv} onChange={(e) => setIv(e.target.value)} inputMode="decimal" /></Field>
            <button onClick={submit} disabled={loading} style={{ background: accent, color: "#fff", border: "none", padding: "7px 20px", borderRadius: 4, cursor: loading ? "default" : "pointer", fontFamily: mono, fontSize: fs(18), opacity: loading ? 0.6 : 1, alignSelf: "flex-end" }}>{loading ? "試算中…" : "試算避險"}</button>
          </div>

          {error && <div style={{ color: danger, fontSize: fs(17), marginTop: 12 }}>⚠ {error}</div>}

          {result && (
            <div style={{ marginTop: 16, borderTop: `1px solid ${border}`, paddingTop: 14, display: "flex", flexWrap: "wrap", gap: 14 }}>
              {result.proposals.map((p) => <ProposalCard key={p.kind} p={p} spxLevel={result.spxLevel} targetLeverage={result.targetLeverage} />)}
            </div>
          )}

          <div style={{ fontSize: fs(14), color: "#90a4b8", marginTop: 14, lineHeight: 1.6 }}>
            ⚠ 數量級參考,非精確值。三案共用同一口數 N(以長 Put 對沖至目標槓桿 &lt; {result ? result.targetLeverage?.toFixed(2) ?? targetLeverage : targetLeverage}×;DTE ≤ {dte})。各腿以同一 IV 之 Black-Scholes 定價,海鷗的賣 Call 履約價選為信用≈價差權利金(故 ≈ 零成本)。SPX 點位/期權鏈/IV 取自上次連線快照(現價快照),無快照時改用模型定價。實際避險另受偏度/相關性/到期選擇影響。
          </div>
        </div>
      </div>
    </>
  );
}
