import { useState, useEffect, useCallback, useRef } from "react";
import DonutChart from "./components/DonutChart";
import RollWhatIf from "./components/RollWhatIf";
import { fetchPortfolio } from "./api";
import type { PortfolioResponse, UnderlyingRow, PositionRow, MarginSummary } from "./types";

const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtCachedAt = (iso: string | null): string => {
  if (!iso) return "未知時間";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("zh-TW", { hour12: false });
};

// Margin risk-level palette: text/accent + background tint per level, used by
// the margin-buffer card and the danger banner.
const MARGIN_STYLE: Record<MarginSummary["level"], { fg: string; bg: string; border: string; label: string }> = {
  safe: { fg: "#1f7a4d", bg: "#e8f6ee", border: "#bfe3cd", label: "安全" },
  warning: { fg: "#8a5a00", bg: "#fff4e0", border: "#f0d29a", label: "注意" },
  danger: { fg: "#b3261e", bg: "#fde8e6", border: "#f3b8b2", label: "危險" },
};

// Font scaling: the smallest size used in the design was 16 → 10pt.
// Every size is scaled by the same ratio so proportions are preserved.
const FONT_SCALE = 10 / 16;
const fs = (px: number) => `${+(px * FONT_SCALE).toFixed(3)}pt`;

type SortDir = "asc" | "desc";
type UndKey = "symbol" | "notional" | "notPct" | "exposure" | "expPct" | "discount";
type PosKey = "label" | "type" | "notional" | "exposure" | "discount" | "delta" | "iv";

function nextSort<K extends string>(cur: { key: K; dir: SortDir }, key: K): { key: K; dir: SortDir } {
  if (cur.key === key) return { key, dir: cur.dir === "asc" ? "desc" : "asc" };
  return { key, dir: "desc" };
}

const cmp = (a: string | number, b: string | number, dir: SortDir) => {
  const r = typeof a === "string" && typeof b === "string" ? a.localeCompare(b) : (a as number) - (b as number);
  return dir === "asc" ? r : -r;
};

// Some icon-derived colors are near-black/desaturated (picked for a dark
// theme's backdrop); on this light theme they read as muddy. Lift lightness
// and saturation into a range that stays legible on a white background
// without disturbing the hue (so the brand-color identity is preserved).
const hexToHsl = (hex: string): [number, number, number] => {
  const r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  let h = 0, s = 0;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return [h, s * 100, l * 100];
};
const hslToHex = (h: number, s: number, l: number): string => {
  s /= 100; l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h / 60) % 2 - 1)), m = l - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const toHex = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
};
const lightenForLightTheme = (hex: string): string => {
  const [h, s, l] = hexToHsl(hex);
  // Achromatic colors (black/white/gray) have no real hue, so boosting
  // saturation would tint them with the meaningless default hue (0 = red).
  // Keep them neutral and only adjust lightness.
  if (s === 0) return hslToHex(0, 0, Math.min(Math.max(l, 45), 65));
  return hslToHex(h, Math.min(Math.max(s, 45), 80), Math.min(Math.max(l, 45), 65));
};

const undVal = (u: UnderlyingRow, key: UndKey): string | number => {
  switch (key) {
    case "symbol": return u.symbol;
    case "notional": case "notPct": return u.notional;
    case "exposure": case "expPct": return u.exposure;
    case "discount": return u.notional !== 0 ? 1 - u.exposure / u.notional : 0;
  }
};

const posVal = (p: PositionRow, key: PosKey): string | number => {
  switch (key) {
    case "label": return p.label;
    case "type": return p.type;
    case "notional": return p.notional;
    case "exposure": return p.exposure;
    case "discount": return p.discount;
    case "delta": return p.delta ?? -Infinity;
    case "iv": return p.iv ?? -Infinity;
  }
};

export default function App() {
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"byUnd" | "byPos">("byUnd");
  const [hoveredUnd, setHoveredUnd] = useState<string | null>(null);
  const [undSort, setUndSort] = useState<{ key: UndKey; dir: SortDir }>({ key: "notional", dir: "desc" });
  const [posSort, setPosSort] = useState<{ key: PosKey; dir: SortDir }>({ key: "notional", dir: "desc" });

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

  const bg = "#f5f7fa", card = "#ffffff", border = "#d8e0ea", text = "#1a2a3a", muted = "#5a7a9a", accent = "#2a6fb8", mono = "'JetBrains Mono','Fira Code',monospace";

  const colorFor = (und: string) => lightenForLightTheme(data?.underlyings.find((u) => u.symbol === und)?.color ?? "#556699");

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

  // Legend under the pie: sorted by notional share (percentage) descending.
  const legendUnd = [...data.underlyings].sort((a, b) => b.notional - a.notional);

  const sortedUnd = [...data.underlyings].sort((a, b) => cmp(undVal(a, undSort.key), undVal(b, undSort.key), undSort.dir));
  const sortedPos = [...data.positions].sort((a, b) => cmp(posVal(a, posSort.key), posVal(b, posSort.key), posSort.dir));

  const undCols: { label: string; key: UndKey; align: "left" | "right" }[] = [
    { label: "標的", key: "symbol", align: "left" },
    { label: "Notional", key: "notional", align: "right" },
    { label: "Not%", key: "notPct", align: "right" },
    { label: "Exposure", key: "exposure", align: "right" },
    { label: "Exp%", key: "expPct", align: "right" },
    { label: "Discount", key: "discount", align: "right" },
  ];
  const posCols: { label: string; key: PosKey; align: "left" | "right" }[] = [
    { label: "倉位", key: "label", align: "left" },
    { label: "類型", key: "type", align: "left" },
    { label: "Notional", key: "notional", align: "right" },
    { label: "Exposure", key: "exposure", align: "right" },
    { label: "Discount", key: "discount", align: "right" },
    { label: "Δ", key: "delta", align: "right" },
    { label: "IV", key: "iv", align: "right" },
  ];

  const arrow = (active: boolean, dir: SortDir) => (active ? (dir === "asc" ? " ▲" : " ▼") : "");

  return (
    <div style={{ background: bg, minHeight: "100vh", color: text, fontFamily: mono, fontSize: fs(21), paddingBottom: 40 }}>
      <div style={{ background: card, borderBottom: `1px solid ${border}`, padding: "14px 24px", display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontSize: fs(18), color: muted, letterSpacing: "0.12em", textTransform: "uppercase" }}>Portfolio Risk Dashboard</div>
          <div style={{ fontSize: fs(27), color: "#0d2438", fontWeight: 700, marginTop: 2 }}>Notional &amp; Delta Exposure</div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center" }}>
          {[
            [{ label: "NLV", value: `$${fmt(data.nlv)}`, bold: false, size: "12pt" }],
            [{ label: "Notional", value: `$${fmt(data.totalNotional)}`, bold: false, size: "12pt" }, { label: "Notl Lev", value: `${data.notionalLeverage.toFixed(2)}×`, bold: true, size: "16pt" }],
            [{ label: "Exposure", value: `$${fmt(data.totalExposure)}`, bold: false, size: "12pt" }, { label: "Exp Lev", value: `${data.exposureLeverage.toFixed(2)}×`, bold: true, size: "16pt" }],
          ].map((group, gi) => (
            <div key={gi} style={{ display: "flex", gap: 20, alignItems: "center", padding: "0 16px", borderLeft: gi > 0 ? `1px solid ${border}` : "none" }}>
              {group.map((m) => (
                <div key={m.label} style={{ textAlign: "right" }}>
                  <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.1em" }}>{m.label}</div>
                  <div style={{ fontSize: m.size, color: "#0d2438", fontWeight: m.bold ? 700 : 400 }}>{m.value}</div>
                </div>
              ))}
            </div>
          ))}
          <button onClick={load} style={{ background: accent, color: "#fff", border: "none", padding: "6px 14px", borderRadius: 4, cursor: "pointer", fontFamily: mono, marginLeft: 16 }}>重新整理</button>
        </div>
      </div>

      {data.stale && (
        <div style={{ background: "#fff4e0", borderBottom: "1px solid #f0d29a", color: "#8a5a00", padding: "8px 24px", textAlign: "center", fontSize: fs(18) }}>
          ⚠ 無法連線到 IB Gateway，顯示的是上次成功擷取的快照資料（{fmtCachedAt(data.cachedAt)}）。請確認 Gateway 已啟動並登入，再按「重新整理」。
        </div>
      )}

      {data.margin && data.margin.level === "danger" && (
        <div style={{ background: MARGIN_STYLE.danger.bg, borderBottom: `1px solid ${MARGIN_STYLE.danger.border}`, color: MARGIN_STYLE.danger.fg, padding: "8px 24px", textAlign: "center", fontSize: fs(18), fontWeight: 600 }}>
          ⚠ 保證金緩衝偏低（Cushion {(data.margin.cushion * 100).toFixed(1)}%）—— 已接近 IBKR 強制平倉門檻。Excess Liquidity 歸零即觸發自動平倉，請儘速補入資金或減倉。
        </div>
      )}

      {data.margin && (
        <div style={{ display: "flex", justifyContent: "center", padding: "14px 24px 0" }}>
          <div style={{ background: MARGIN_STYLE[data.margin.level].bg, border: `1px solid ${MARGIN_STYLE[data.margin.level].border}`, borderRadius: 4, padding: "10px 24px", display: "flex", flexWrap: "wrap", gap: 36, alignItems: "center" }}>
            <div style={{ textAlign: "center", paddingRight: 16, borderRight: `1px solid ${MARGIN_STYLE[data.margin.level].border}` }}>
              <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4 }}>保證金緩衝 Margin</div>
              <div style={{ fontSize: "13pt", color: MARGIN_STYLE[data.margin.level].fg, fontWeight: 700 }}>{MARGIN_STYLE[data.margin.level].label}</div>
            </div>
            {[
              { label: "Excess Liq (距強平)", value: `$${fmt(data.margin.excessLiquidity)}`, strong: true },
              { label: "Cushion", value: `${(data.margin.cushion * 100).toFixed(1)}%`, strong: true },
              { label: "Maint Margin", value: `$${fmt(data.margin.maintMargin)}`, strong: false },
              { label: "Buffer ×Maint", value: data.margin.bufferRatio !== null ? `${data.margin.bufferRatio.toFixed(2)}×` : "—", strong: false },
              ...(data.margin.lookAheadExcessLiquidity !== undefined
                ? [{ label: "LookAhead Excess", value: `$${fmt(data.margin.lookAheadExcessLiquidity)}`, strong: false }]
                : []),
              ...(data.margin.cash !== undefined
                ? [{ label: "Cash 現金", value: `$${fmt(data.margin.cash)}`, strong: false, color: data.margin.cash < 0 ? MARGIN_STYLE.danger.fg : undefined }]
                : []),
              ...(data.margin.availableFunds !== undefined
                ? [{ label: "Avail Funds (可開倉)", value: `$${fmt(data.margin.availableFunds)}`, strong: false, color: data.margin.availableFunds < 0 ? MARGIN_STYLE.danger.fg : undefined }]
                : []),
            ].map((m) => (
              <div key={m.label} style={{ textAlign: "center" }}>
                <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: "12pt", color: ("color" in m && m.color) ? m.color : (m.strong ? MARGIN_STYLE[data.margin!.level].fg : "#0d2438"), fontWeight: m.strong ? 700 : 400 }}>{m.value}</div>
              </div>
            ))}
            {data.margin.canOpenNew === false && (
              <div style={{ background: MARGIN_STYLE.warning.bg, border: `1px solid ${MARGIN_STYLE.warning.border}`, color: MARGIN_STYLE.warning.fg, borderRadius: 3, padding: "4px 10px", fontSize: fs(16), fontWeight: 600, alignSelf: "center" }}>
                ⚠ 無法開新倉（Available Funds ≤ 0）
              </div>
            )}
          </div>
        </div>
      )}

      <RollWhatIf data={data} />

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 0 6px", gap: 8 }}>
        {([["byUnd", "依標的"], ["byPos", "依倉位"]] as const).map(([v, l]) => (
          <button key={v} onClick={() => setView(v)} style={{ background: view === v ? accent : "transparent", border: `1px solid ${view === v ? accent : border}`, color: view === v ? "#fff" : muted, fontFamily: mono, fontSize: fs(20), letterSpacing: "0.08em", padding: "5px 16px", borderRadius: 3, cursor: "pointer" }}>{l}</button>
        ))}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "flex-start", gap: 20, padding: "4px 24px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingTop: 36 }}>
          {legendUnd.map((u) => (
            <div key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)}
              style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", background: hoveredUnd === u.symbol ? "#e8eef6" : "transparent", borderRadius: 3, padding: "2px 8px" }}>
              {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
              <span style={{ color: muted, fontSize: fs(16) }}>{u.symbol}</span>
              <span style={{ color: "#607888", fontSize: fs(16) }}>{data.totalNotional !== 0 ? ((u.notional / data.totalNotional) * 100).toFixed(1) + "%N" : "—"}</span>
              <span style={{ color: "#506070", fontSize: fs(16) }}>/{data.totalExposure !== 0 ? ((u.exposure / data.totalExposure) * 100).toFixed(1) + "%E" : "—"}</span>
            </div>
          ))}
        </div>
        <DonutChart data={view === "byUnd" ? undN : posN} total={data.totalNotional} title="名義 Notional" subtitle="Total Notional" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
        <DonutChart data={view === "byUnd" ? undE : posE} total={data.totalExposure} title="曝險 Delta Exposure" subtitle="Δ-Weighted Exp" nlv={data.nlv} colorFor={colorFor} onHover={setHoveredUnd} hoveredUnd={hoveredUnd} />
      </div>

      <div style={{ display: "flex", justifyContent: "center", padding: "14px 24px 6px" }}>
        <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: "10px 32px", display: "flex", gap: 40 }}>
          {[
            { label: "Net Δ (share-eq)", raw: data.netDelta, value: fmt(data.netDelta), color: "#2f7fd0" },
            { label: "Net Θ/day", raw: data.netTheta, value: `${data.netTheta >= 0 ? "+" : ""}$${fmt(data.netTheta, 2)}`, color: "#1f9e7a" },
            { label: "Net Vega /1%vol", raw: data.netVega, value: `${data.netVega >= 0 ? "+" : "-"}$${fmt(Math.abs(data.netVega), 2)}`, color: "#d2601f" },
          ].map((m) => {
            const pct = data.nlv !== 0 ? (m.raw / data.nlv) * 100 : null;
            return (
              <div key={m.label} style={{ textAlign: "center" }}>
                <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.1em", marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: "12pt", color: m.color, fontWeight: 700 }}>
                  {m.value}
                  {pct !== null && <span style={{ fontSize: fs(15), color: muted, fontWeight: 400, marginLeft: 6 }}>({pct >= 0 ? "+" : ""}{pct.toFixed(2)}% NLV)</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ padding: "10px 24px 0" }}>
        <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>標的明細 Underlying Breakdown</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: fs(20) }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {undCols.map((c) => (
                  <th key={c.key} onClick={() => setUndSort(nextSort(undSort, c.key))}
                    style={{ padding: "4px 10px", textAlign: c.align, fontWeight: 500, fontSize: fs(20), whiteSpace: "nowrap", cursor: "pointer", userSelect: "none", color: undSort.key === c.key ? accent : muted }}>
                    {c.label}{arrow(undSort.key === c.key, undSort.dir)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedUnd.map((u) => {
                const disc = 1 - u.exposure / u.notional;
                return (
                  <tr key={u.symbol} onMouseEnter={() => setHoveredUnd(u.symbol)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #eef2f7" }}>
                    <td style={{ padding: "5px 10px", display: "flex", alignItems: "center", gap: 6 }}>
                      {u.iconUrl && <img src={u.iconUrl} alt={u.symbol} width={14} height={14} style={{ borderRadius: 2 }} />}
                      <span style={{ color: "#1a2a3a", fontWeight: 600 }}>{u.symbol}</span>
                    </td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#3a5a7a" }}>${fmt(u.notional)}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: muted }}>{data.totalNotional !== 0 ? ((u.notional / data.totalNotional) * 100).toFixed(1) + "%" : "—"}</td>
                    <td style={{ padding: "5px 10px", textAlign: "right", color: "#3a5a7a" }}>${fmt(u.exposure)}</td>
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
        <div style={{ fontSize: fs(16), color: muted, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>倉位明細 Position Details</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: fs(19), minWidth: 680 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${border}`, color: muted }}>
                {posCols.map((c) => (
                  <th key={c.key} onClick={() => setPosSort(nextSort(posSort, c.key))}
                    style={{ padding: "4px 10px", textAlign: c.align, fontWeight: 500, fontSize: fs(19), whiteSpace: "nowrap", cursor: "pointer", userSelect: "none", color: posSort.key === c.key ? accent : muted }}>
                    {c.label}{arrow(posSort.key === c.key, posSort.dir)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedPos.map((p, i) => (
                <tr key={`${p.underlying}-${p.label}-${i}`} onMouseEnter={() => setHoveredUnd(p.underlying)} onMouseLeave={() => setHoveredUnd(null)} style={{ borderBottom: "1px solid #eef2f7" }}>
                  <td style={{ padding: "4px 10px", color: "#2a4a6a" }}>{p.label}</td>
                  <td style={{ padding: "4px 10px", fontSize: fs(19) }}>{p.type}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#3a5a7a" }}>${fmt(p.notional)}</td>
                  <td style={{ padding: "4px 10px", textAlign: "right", color: "#3a5a7a" }}>${fmt(p.exposure)}</td>
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
        <div style={{ padding: "14px 24px 0", color: "#b8730a", fontSize: fs(18) }}>
          {data.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}
    </div>
  );
}
