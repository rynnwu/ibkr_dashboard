import { useState, useEffect, useCallback, useRef } from "react";
import DonutChart from "./components/DonutChart";
import { fetchPortfolio } from "./api";
import type { PortfolioResponse } from "./types";

const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function App() {
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"byUnd" | "byPos">("byUnd");
  const [hoveredUnd, setHoveredUnd] = useState<string | null>(null);

  // A portfolio fetch takes ~2 min and opens a gateway connection; guard
  // against overlapping loads (React StrictMode double-invokes this effect,
  // and the user can re-click 重試/refresh) so we don't stack requests.
  const inFlight = useRef(false);
  const load = useCallback(() => {
    if (inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    setError(null);
    fetchPortfolio()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => {
        setLoading(false);
        inFlight.current = false;
      });
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- async fetch-on-mount; setState calls happen inside promise callbacks, not synchronously in the effect body
  useEffect(() => { load(); }, [load]);

  const bg = "#070b14", card = "#0c1422", border = "#1a2d45", text = "#c8ddf0", muted = "#4a7a9a", accent = "#2a6fb8", mono = "'JetBrains Mono','Fira Code',monospace";

  const colorFor = (und: string) => data?.underlyings.find((u) => u.symbol === und)?.color ?? "#556";

  if (error) {
    return (
      <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, padding: 24 }}>
        <p>無法載入持倉資料：{error}</p>
        <button onClick={load} style={{ background: accent, color: "#fff", border: "none", padding: "8px 16px", borderRadius: 4, cursor: "pointer" }}>重試</button>
      </div>
    );
  }

  if (loading || !data) {
    return <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, padding: 24 }}>載入中…</div>;
  }

  const undN = data.underlyings.map((u) => ({ und: u.symbol, val: u.notional }));
  const undE = data.underlyings.map((u) => ({ und: u.symbol, val: u.exposure }));
  const posN = data.positions.map((p) => ({ und: p.underlying, label: p.label, val: p.notional }));
  const posE = data.positions.map((p) => ({ und: p.underlying, label: p.label, val: p.exposure }));

  return (
    <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, fontSize: 12, paddingBottom: 40 }}>
      <div style={{ background: card, borderBottom: `1px solid ${border}`, padding: "14px 24px", display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: 10, color: muted, letterSpacing: "0.12em", textTransform: "uppercase" }}>Portfolio Risk Dashboard</div>
          <div style={{ fontSize: 15, color: "#e0eeff", fontWeight: 700, marginTop: 2 }}>Notional &amp; Delta Exposure</div>
        </div>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
          {[["NLV", `$${fmt(data.nlv)}`], ["Notional", `$${fmt(data.totalNotional)}`], ["Notl Lev", `${data.notionalLeverage.toFixed(2)}×`], ["Exposure", `$${fmt(data.totalExposure)}`], ["Exp Lev", `${data.exposureLeverage.toFixed(2)}×`]].map(([l, v]) => (
            <div key={l} style={{ textAlign: "right" }}>
              <div style={{ fontSize: 9, color: muted, letterSpacing: "0.1em" }}>{l}</div>
              <div style={{ fontSize: 13, color: "#e0eeff", fontWeight: 700 }}>{v}</div>
            </div>
          ))}
          <button onClick={load} style={{ background: accent, color: "#fff", border: "none", padding: "6px 14px", borderRadius: 4, cursor: "pointer", fontFamily: mono }}>重新整理</button>
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 0 6px", gap: 8 }}>
        {([["byUnd", "依標的"], ["byPos", "依倉位"]] as const).map(([v, l]) => (
          <button key={v} onClick={() => setView(v)} style={{ background: view === v ? accent : "transparent", border: `1px solid ${view === v ? accent : border}`, color: view === v ? "#fff" : muted, fontFamily: mono, fontSize: 11, letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>{l}</button>
        ))}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 20, padding: "4px 24px" }}>
        <DonutChart data={view === "byUnd" ? undN : posN} total={data.totalNotional} title="名義 Notional" subtitle="Total Notional" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
        <DonutChart data={view === "byUnd" ? undE : posE} total={data.totalExposure} title="曝險 Delta Exposure" subtitle="Δ-Weighted Exp" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
      </div>

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 24px 6px" }}>
        <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: "10px 32px", display: "flex", gap: 40 }}>
          {[["Net Δ (share-eq)", fmt(data.netDelta), "#4a9eff"], ["Net Θ/day", `${data.netTheta >= 0 ? "+" : ""}$${fmt(data.netTheta, 2)}`, "#4fc3a1"], ["Net Vega /1%vol", `${data.netVega >= 0 ? "+" : "-"}$${fmt(Math.abs(data.netVega), 2)}`, "#e8703a"]].map(([l, v, c]) => (
            <div key={l} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 9, color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>{l}</div>
              <div style={{ fontSize: 15, color: c, fontWeight: 700 }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, justifyContent: "center", padding: "6px 24px" }}>
        {data.underlyings.map((u) => (
          <div key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)}
            style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", background: hoveredUnd === u.symbol ? "#1a2d45" : "transparent", borderRadius: 3, padding: "2px 8px" }}>
            {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
            <span style={{ color: muted, fontSize: 9 }}>{u.symbol}</span>
            <span style={{ color: "#607888", fontSize: 9 }}>{data.totalNotional !== 0 ? ((u.notional / data.totalNotional) * 100).toFixed(1) + "%N" : "—"}</span>
            <span style={{ color: "#506070", fontSize: 9 }}>/{data.totalExposure !== 0 ? ((u.exposure / data.totalExposure) * 100).toFixed(1) + "%E" : "—"}</span>
          </div>
        ))}
      </div>

      <div style={{ padding: "10px 24px 0" }}>
        <div style={{ fontSize: 9, color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>標的明細 Underlying Breakdown</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {["標的", "Notional", "Not%", "Exposure", "Exp%", "Discount"].map((h, i) => (
                  <th key={h} style={{ padding: "4px 10px", textAlign: i === 0 ? "left" : "right", fontWeight: 500, fontSize: 9, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.underlyings.map((u) => {
                const disc = 1 - u.exposure / u.notional;
                return (
                  <tr key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #111b2a" }}>
                    <td style={{ padding: "5px 10px", display: "flex", alignItems: "center", gap: 6 }}>
                      {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
                      <span style={{ color: "#c0d8f0", fontWeight: 600 }}>{u.symbol}</span>
                    </td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#a0c0e0" }}>${fmt(u.notional)}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: muted }}>{data.totalNotional !== 0 ? ((u.notional / data.totalNotional) * 100).toFixed(1) + "%" : "—"}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#a0c0e0" }}>${fmt(u.exposure)}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: muted }}>{data.totalExposure !== 0 ? ((u.exposure / data.totalExposure) * 100).toFixed(1) + "%" : "—"}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right" }}>{u.notional !== 0 ? (disc * 100).toFixed(1) + "%" : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ padding: "14px 24px 0" }}>
        <div style={{ fontSize: 9, color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>倉位明細 Position Details</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 10.5, minWidth: 680 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {["倉位", "類型", "Notional", "Exposure", "Discount", "Δ", "IV"].map((h, i) => (
                  <th key={h} style={{ padding: "4px 10px", textAlign: i <= 1 ? "left" : "right", fontWeight: 500, fontSize: 9, whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p, i) => (
                <tr key={i} onMouseEnter={() => setHoveredUnd(p.underlying)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #0e1a28" }}>
                  <td style={{ padding: "4px 10px", color: "#b0ccdf" }}>{p.label}</td>
                  <td style={{ padding: "4px 10px", fontSize: 9 }}>{p.type}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#90b0d0" }}>${fmt(p.notional)}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#90b0d0" }}>${fmt(p.exposure)}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right" }}>{(p.discount * 100).toFixed(1)}%</td>
                  <td style={{ padding: "4px 10px", textAlign: "right" }}>{p.delta !== null ? (p.delta > 0 ? "+" : "") + p.delta.toFixed(3) : "—"}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: muted }}>{p.iv !== null ? p.iv.toFixed(1) + "%" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.warnings.length > 0 && (
        <div style={{ padding: "14px 24px 0", color: "#e8a03a", fontSize: 10 }}>
          {data.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}
    </div>
  );
}
