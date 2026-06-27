import { useEffect, useState } from "react";
import { fetchSpxHedge } from "../api";
import useIsMobile from "../hooks/useIsMobile";
import type { EtfHedgeCandidate, HedgeLeg, HedgeProposal, PortfolioResponse, SpxHedgeResult } from "../types";

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

const pct = (strike: number, spot: number): string => {
  if (!(spot > 0)) return "";
  const p = ((strike - spot) / spot) * 100;
  return `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`;
};

const legText = (l: HedgeLeg, spot: number, symbol: string): string => {
  const side = l.contracts >= 0 ? "買" : "賣";
  const qty = Math.abs(l.contracts);
  return `${side} ${fmt(qty)} 口 ${symbol} ${fmt(l.strike)}${l.right} (${pct(l.strike, spot)})`;
};

function ProposalCard({ p, spotLevel, symbol, targetLeverage }: { p: HedgeProposal; spotLevel: number; symbol: string; targetLeverage: number | null }) {
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
                {legText(l, spotLevel, symbol)} <span style={{ color: muted }}>· Δ{l.delta.toFixed(2)} · ${fmt(l.price, 2)}</span>
              </div>
            ))}
      </div>

      <div style={{ fontSize: fs(15.5), color: muted, marginTop: 10, lineHeight: 1.8, borderTop: `1px solid ${border}`, paddingTop: 8 }}>
        淨成本: <b style={{ color: costColor }}>{p.cost < 0 ? "+" : ""}${fmt(Math.abs(p.cost))}</b>{p.cost <= 0 && p.contracts > 0 ? "(信用)" : ""}<br />
        對沖後槓桿: {p.leverageBefore.toFixed(2)}× → <b style={{ color: levColor }}>{p.leverageAfter.toFixed(2)}×</b>{missed ? "(未達目標)" : over ? "(超額)" : ""}<br />
        {p.protectionFloor != null && <>保護下限: {fmt(p.protectionFloor)}{p.protectionFloor < spotLevel ? `(−${(((spotLevel - p.protectionFloor) / spotLevel) * 100).toFixed(1)}%)` : ""}<br /></>}
        {p.upsideCap != null && <>上行封頂: {fmt(p.upsideCap)}{p.upsideCap > spotLevel ? `(+${(((p.upsideCap - spotLevel) / spotLevel) * 100).toFixed(1)}%)` : ""}<br /></>}
        {p.maxProtection != null && <span style={{ color: "#90a4b8" }}>價差最大保護 ${fmt(p.maxProtection)}</span>}
      </div>
    </div>
  );
}

export default function SpxHedge({ data }: { data: PortfolioResponse }) {
  const isMobile = useIsMobile();
  const pad = isMobile ? 12 : 24;
  const [open, setOpen] = useState(false);

  // Hedge-instrument options: SPX plus each compared ETF candidate (DESIGN §13).
  const candidates: EtfHedgeCandidate[] = data.etfHedge?.candidates ?? [];
  const candidateBySymbol = new Map(candidates.map((c) => [c.symbol, c]));
  // Default to the recommended ETF when it's present as a candidate, else SPX.
  const recommended = data.etfHedge?.recommended;
  const defaultSymbol = recommended && candidateBySymbol.has(recommended) ? recommended : "SPX";
  const [symbol, setSymbol] = useState(defaultSymbol);
  const selected = symbol === "SPX" ? null : candidateBySymbol.get(symbol) ?? null;
  const isSpx = symbol === "SPX";

  // Defaults mirror config.json spx_hedge; the user can override per-run. The
  // default suggestion sizes the minimum hedge to bring leverage under
  // targetLeverage (1.0×) using a near-dated put (DTE ≤ 30).
  const [targetLeverage, setTargetLeverage] = useState("1.0");
  const [targetDelta, setTargetDelta] = useState("0.30");
  const [floorDelta, setFloorDelta] = useState("0.12");
  const [dte, setDte] = useState("30");
  const [iv, setIv] = useState("20");
  // Editable ETF spot, only used when the selected candidate has no `level`.
  const [etfSpot, setEtfSpot] = useState("");
  const [result, setResult] = useState<SpxHedgeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The exposure base + instrument spot depend on the selection: SPX uses the
  // beta-weighted net exposure + SPX level; an ETF uses its own ETF-weighted
  // netExposure + its spot (candidate.level, or the manually-typed spot).
  const netExposure = isSpx ? data.netBetaWeightedExposure : selected?.netExposure ?? 0;
  const candidateLevel = selected?.level ?? null;
  const needsManualSpot = !isSpx && (candidateLevel == null || !(candidateLevel > 0));
  const etfLevel = needsManualSpot ? num(etfSpot) : candidateLevel ?? 0;
  const submitDisabled = loading || (needsManualSpot && !(etfLevel > 0));

  const submit = () => {
    setLoading(true);
    setError(null);
    const base = {
      nlv: data.nlv,
      targetLeverage: num(targetLeverage),
      targetDelta: num(targetDelta),
      floorDelta: num(floorDelta),
      targetDte: Math.max(1, Math.round(num(dte))),
      assumedIv: num(iv),
    };
    const req = isSpx
      ? { ...base, netExposure, symbol: "SPX", spxLevel: data.spxLevel > 0 ? data.spxLevel : undefined }
      : { ...base, netExposure, symbol, level: etfLevel, dividendYield: 0 };
    fetchSpxHedge(req)
      .then(setResult)
      .catch((e: Error) => { setError(e.message); setResult(null); })
      .finally(() => setLoading(false));
  };

  // Auto-run the default suggestion the first time the panel is opened, then
  // re-run whenever the hedge instrument changes (clearing the prior result so
  // the user sees the three concrete proposals for the new instrument).
  useEffect(() => {
    if (!open) return;
    setResult(null);
    setError(null);
    // For an ETF whose spot must be typed, wait for the user to enter it.
    if (!isSpx && needsManualSpot && !(etfLevel > 0)) return;
    submit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, symbol]);

  // Instrument-aware header figures: which exposure base + leverage to show.
  const baseLeverage = data.nlv ? netExposure / data.nlv : 0;
  const spotForResult = result ? result.spxLevel : isSpx ? data.spxLevel : etfLevel;

  const headerBtn = (
    <div style={{ display: "flex", justifyContent: "center", padding: `10px ${pad}px 0` }}>
      <button onClick={() => setOpen((o) => !o)} style={{ background: "transparent", border: `1px solid ${border}`, color: muted, fontFamily: mono, fontSize: fs(18), letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>
        {open ? "▾" : "▸"} 避險試算 Hedge What-If ({symbol})
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
            {isSpx ? "Beta 加權淨曝險" : `${symbol} 加權淨曝險`}: <b style={{ color: text }}>${fmt(netExposure)}</b>
            {" "}({baseLeverage.toFixed(2)}× NLV) · {symbol} {result ? `≈ ${fmt(result.spxLevel, 2)}` : spotForResult > 0 ? `≈ ${fmt(spotForResult, 2)}` : "—"}
            {result && <> · {result.dte} 天到期 · IV {fmt(result.iv, 1)}% · <span style={{ color: result.source === "model" ? credit : safe }}>{result.source === "model" ? "模型定價" : "現價快照"}{result.cachedAt ? `(${result.cachedAt.slice(5, 16).replace("T", " ")})` : ""}</span></>}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 14, alignItems: "flex-end" }}>
            <Field label="避險工具">
              <select style={{ ...inputStyle, width: 120 }} value={symbol} onChange={(e) => setSymbol(e.target.value)}>
                <option value="SPX">SPX{recommended === "SPX" ? " ★" : ""}</option>
                {candidates.map((c) => (
                  <option key={c.symbol} value={c.symbol}>{c.symbol}{recommended === c.symbol ? " ★" : ""}</option>
                ))}
              </select>
            </Field>
            {needsManualSpot && (
              <Field label={`${symbol} 現價`}><input style={inputStyle} value={etfSpot} onChange={(e) => setEtfSpot(e.target.value)} inputMode="decimal" placeholder="輸入現價" /></Field>
            )}
            <Field label="目標槓桿 (×NLV)"><input style={inputStyle} value={targetLeverage} onChange={(e) => setTargetLeverage(e.target.value)} inputMode="decimal" /></Field>
            <Field label="Put Δ 目標"><input style={inputStyle} value={targetDelta} onChange={(e) => setTargetDelta(e.target.value)} inputMode="decimal" /></Field>
            <Field label="下緣 Put Δ"><input style={inputStyle} value={floorDelta} onChange={(e) => setFloorDelta(e.target.value)} inputMode="decimal" /></Field>
            <Field label="到期天數 DTE ≤"><input style={inputStyle} value={dte} onChange={(e) => setDte(e.target.value)} inputMode="decimal" /></Field>
            <Field label="假設 IV (%)"><input style={inputStyle} value={iv} onChange={(e) => setIv(e.target.value)} inputMode="decimal" /></Field>
            <button onClick={submit} disabled={submitDisabled} style={{ background: accent, color: "#fff", border: "none", padding: "7px 20px", borderRadius: 4, cursor: submitDisabled ? "default" : "pointer", fontFamily: mono, fontSize: fs(18), opacity: submitDisabled ? 0.6 : 1, alignSelf: "flex-end" }}>{loading ? "試算中…" : "試算避險"}</button>
          </div>

          {needsManualSpot && !(etfLevel > 0) && <div style={{ color: muted, fontSize: fs(15), marginTop: 10 }}>請輸入 {symbol} 現價以進行模型試算。</div>}
          {error && <div style={{ color: danger, fontSize: fs(17), marginTop: 12 }}>⚠ {error}</div>}

          {result && (
            <div style={{ marginTop: 16, borderTop: `1px solid ${border}`, paddingTop: 14, display: "flex", flexWrap: "wrap", gap: 14 }}>
              {result.proposals.map((p) => <ProposalCard key={p.kind} p={p} spotLevel={result.spxLevel} symbol={result.symbol} targetLeverage={result.targetLeverage} />)}
            </div>
          )}

          <div style={{ fontSize: fs(14), color: "#90a4b8", marginTop: 14, lineHeight: 1.6 }}>
            ⚠ 數量級參考,非精確值。三案共用同一口數 N(以長 Put 對沖至目標槓桿 &lt; {result ? result.targetLeverage?.toFixed(2) ?? targetLeverage : targetLeverage}×;DTE ≤ {dte})。各腿以同一 IV 之 Black-Scholes 定價,海鷗的賣 Call 履約價選為信用≈價差權利金(故 ≈ 零成本)。{isSpx ? "SPX 點位/期權鏈/IV 取自上次連線快照(現價快照),無快照時改用模型定價。" : `${symbol} 採模型定價(合成履約價網格,以輸入現價與假設 IV 估算)。`}實際避險另受偏度/相關性/到期選擇影響。
          </div>
        </div>
      </div>
    </>
  );
}
