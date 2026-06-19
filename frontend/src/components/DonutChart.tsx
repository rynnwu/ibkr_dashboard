interface SliceDatum {
  und: string;
  label?: string;
  val: number;
}

interface DonutChartProps {
  data: SliceDatum[];
  total: number;
  title: string;
  subtitle: string;
  nlv: number;
  colorFor: (und: string) => string;
  onHover: (und: string | null) => void;
  hoveredUnd: string | null;
}

const fmt = (n: number, d = 0) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtM = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : `$${fmt(n)}`);

export default function DonutChart({ data, total, title, subtitle, nlv, colorFor, onHover, hoveredUnd }: DonutChartProps) {
  const cx = 160, cy = 160, outerR = 128, innerR = 70;
  const slices: Array<SliceDatum & { frac: number; sa: number; ea: number; mid: number }> = [];
  let angle = -Math.PI / 2;
  if (total !== 0) {
    data.forEach((d) => {
      const frac = d.val / total, sa = angle, ea = angle + frac * 2 * Math.PI, mid = (sa + ea) / 2;
      slices.push({ ...d, frac, sa, ea, mid });
      angle = ea;
    });
  }
  const pol = (a: number, r: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const arc = (sa: number, ea: number, r: number, R: number) => {
    const lg = ea - sa > Math.PI ? 1 : 0;
    const [x1, y1] = pol(sa, R), [x2, y2] = pol(ea, R), [x3, y3] = pol(ea, r), [x4, y4] = pol(sa, r);
    return `M${x1} ${y1} A${R} ${R} 0 ${lg} 1 ${x2} ${y2} L${x3} ${y3} A${r} ${r} 0 ${lg} 0 ${x4} ${y4}Z`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: "#5a7a9a", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{title}</div>
      <svg width={320} height={320} style={{ overflow: "visible" }}>
        {slices.map((s, i) => {
          const isH = hoveredUnd === s.und, isO = hoveredUnd && !isH;
          const R = isH ? outerR + 6 : outerR;
          return (
            <path key={`${s.und}-${i}`} d={arc(s.sa, s.ea, innerR, R)}
              fill={colorFor(s.und)} opacity={isO ? 0.3 : 1}
              stroke="#070b14" strokeWidth={1.5} style={{ cursor: "pointer", transition: "opacity 0.15s" }}
              onMouseEnter={() => onHover(s.und)} onMouseLeave={() => onHover(null)} />
          );
        })}
        {slices.map((s, i) => {
          if (s.frac < 0.012) return null;
          const [x1, y1] = pol(s.mid, outerR + 4), [x2, y2] = pol(s.mid, outerR + 14), [tx, ty] = pol(s.mid, outerR + 22);
          const anc = Math.cos(s.mid) > 0.1 ? "start" : Math.cos(s.mid) < -0.1 ? "end" : "middle";
          return (
            <g key={"l-" + s.und + "-" + i}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colorFor(s.und)} strokeWidth={0.8} opacity={0.7} />
              <text x={tx} y={ty} textAnchor={anc} dominantBaseline="middle" fill={colorFor(s.und)} fontSize={9.5} fontFamily="'JetBrains Mono',monospace" fontWeight="600">{s.und}</text>
            </g>
          );
        })}
        <text x={cx} y={cy - 10} textAnchor="middle" fill="#c8ddf0" fontSize={13} fontFamily="'JetBrains Mono',monospace" fontWeight="700">{fmtM(total)}</text>
        <text x={cx} y={cy + 8} textAnchor="middle" fill="#4a7a9a" fontSize={9} fontFamily="'JetBrains Mono',monospace">{subtitle}</text>
        <text x={cx} y={cy + 22} textAnchor="middle" fill="#3a6a8a" fontSize={9} fontFamily="'JetBrains Mono',monospace">{nlv !== 0 ? (total / nlv).toFixed(2) + "× NLV" : "—"}</text>
      </svg>
    </div>
  );
}
