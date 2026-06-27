import useIsMobile from "../hooks/useIsMobile";
import type { EtfHedge, PortfolioResponse } from "../types";

const FONT_SCALE = 10 / 16;
const fs = (px: number) => `${+(px * FONT_SCALE).toFixed(3)}pt`;
const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

const muted = "#5a7a9a", border = "#d8e0ea", text = "#1a2a3a", accent = "#2a6fb8", card = "#ffffff", mono = "'JetBrains Mono','Fira Code',monospace";
const safe = "#1f7a4d", danger = "#b3261e";

const REASON: Record<EtfHedge["recommendedReason"], (sym: string) => string> = {
  concentrated: (s) => `持股集中在 ${s} 範圍,以 ${s} 避險最貼合、成本最省`,
  broad: (s) => `持股分散,建議以大盤 ${s} 避險`,
  fallback: (s) => `建議以 ${s} 避險`,
  none: () => "無可用持股或候選 ETF",
};

// Color the ×NLV multiple by how stretched the book is in that ETF's terms.
const levColor = (x: number): string => (x >= 1.5 ? danger : x >= 1.0 ? "#b8730a" : safe);

export default function EtfHedgeTable({ data }: { data: PortfolioResponse }) {
  const isMobile = useIsMobile();
  const pad = isMobile ? 12 : 24;
  const etf = data.etfHedge;
  if (!etf || etf.candidates.length === 0) return null;

  return (
    <div style={{ display: "flex", justifyContent: "center", padding: `8px ${pad}px 0` }}>
      <div style={{ background: card, border: `1px solid ${border}`, borderRadius: 4, padding: isMobile ? "14px 14px" : "14px 24px", maxWidth: 1040, width: "100%" }}>
        <div style={{ fontSize: fs(18), fontWeight: 700, color: accent }}>各 ETF 避險比較 (依持股)</div>
        {etf.recommended && (
          <div style={{ fontSize: fs(16), color: text, marginTop: 6, lineHeight: 1.6 }}>
            建議避險工具: <b style={{ color: accent }}>{etf.recommended}</b> —— {REASON[etf.recommendedReason](etf.recommended)}
          </div>
        )}

        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontFamily: mono, fontSize: fs(16.5) }}>
          <thead>
            <tr style={{ color: muted, textAlign: "right", fontSize: fs(14.5), letterSpacing: "0.04em" }}>
              <th style={{ textAlign: "left", paddingBottom: 6 }}>ETF</th>
              <th style={{ paddingBottom: 6 }}>涵蓋持股</th>
              <th style={{ paddingBottom: 6 }}>Beta 加權曝險</th>
              <th style={{ paddingBottom: 6 }}>現為 NLV 倍數</th>
            </tr>
          </thead>
          <tbody>
            {etf.candidates.map((c) => {
              const rec = c.symbol === etf.recommended;
              return (
                <tr key={c.symbol} style={{ borderTop: `1px solid ${border}`, background: rec ? "#eef6ff" : undefined }}>
                  <td style={{ textAlign: "left", padding: "7px 0" }}>
                    <b style={{ color: rec ? accent : text }}>{c.symbol}</b>{rec ? " ★" : ""}
                    <span style={{ color: muted, fontFamily: "inherit", fontSize: fs(13.5) }}> {c.label}</span>
                  </td>
                  <td style={{ textAlign: "right", color: text }}>{(c.coverage * 100).toFixed(0)}%</td>
                  <td style={{ textAlign: "right", color: text }}>${fmt(c.netExposure)}</td>
                  <td style={{ textAlign: "right" }}><b style={{ color: levColor(c.leverage) }}>{c.leverage.toFixed(2)}×</b></td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div style={{ fontSize: fs(14), color: "#90a4b8", marginTop: 12, lineHeight: 1.6 }}>
          ⚠ 數量級參考。「涵蓋持股」= 該 ETF 範圍內持股佔總方向曝險的比例;「NLV 倍數」= 以該 ETF 計價的 Beta 加權淨曝險 ÷ NLV(避險時需對沖的規模)。Beta 對應表為 config.json <code>hedge_etfs</code> 之估計值,可自行調整。集中度門檻 {(etf.concentrationThreshold * 100).toFixed(0)}%。
        </div>
      </div>
    </div>
  );
}
