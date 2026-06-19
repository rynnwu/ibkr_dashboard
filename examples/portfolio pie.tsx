import { useState } from "react";

const NLV = 417833.63;
const TOTAL_NOTIONAL = 1132320;
const TOTAL_EXPOSURE = 803601;
const NOTIONAL_LEV = 2.710;
const EXPOSURE_LEV = 1.923;
const NET_DELTA = 10806.6;
const NET_THETA = 567.23;
const NET_VEGA = -326.29;

const COLORS = {
  TSLA:"#e8703a", GOOG:"#4a9eff", MU:"#38c8c8", TSM:"#7eb8f7",
  SMH:"#5f9ea0", ARM:"#6ab8c0", NVDA:"#4fc3a1", SPCX:"#9b8ec4",
  COHR:"#7abfbd", DRAM:"#6ec6c6", MSFT:"#5da5d5", META:"#3d87c8",
  AAOI:"#8ab0c0", IBKR:"#7090a0",
};

const UND_DATA = [
  {und:"TSLA", notional:390232, exposure:358697},
  {und:"GOOG", notional:219111, exposure:145537},
  {und:"MU",   notional:112597, exposure:32255},
  {und:"TSM",  notional:90971,  exposure:50249},
  {und:"SMH",  notional:65761,  exposure:28350},
  {und:"ARM",  notional:42753,  exposure:25300},
  {und:"NVDA", notional:40831,  exposure:40831},
  {und:"COHR", notional:39089,  exposure:17277},
  {und:"SPCX", notional:35400,  exposure:27641},
  {und:"DRAM", notional:34500,  exposure:16387},
  {und:"MSFT", notional:32550,  exposure:32550},
  {und:"META", notional:25837,  exposure:25837},
  {und:"AAOI", notional:1603,   exposure:1603},
  {und:"IBKR", notional:1086,   exposure:1086},
];

const POSITIONS = [
  {label:"TSLA",           und:"TSLA", type:"STK",  notional:39284,  exposure:39284,  discount:0.000, delta:1.000,  iv:null},
  {label:"TSLL→TSLA",      und:"TSLA", type:"STK",  notional:75960,  exposure:75960,  discount:0.000, delta:2.000,  iv:null},
  {label:"TSLA 200C Oct16",und:"TSLA", type:"COPT", notional:39284,  exposure:38117,  discount:0.030, delta:0.970,  iv:71.8},
  {label:"TSLA 250C Oct16",und:"TSLA", type:"COPT", notional:117852, exposure:110959, discount:0.059, delta:0.942,  iv:58.2},
  {label:"TSLA 255C Oct16",und:"TSLA", type:"COPT", notional:78568,  exposure:73696,  discount:0.062, delta:0.938,  iv:56.8},
  {label:"TSLA 400P Jul17",und:"TSLA", type:"POPT", notional:39284,  exposure:20682,  discount:0.474, delta:-0.527, iv:42.6},

  {label:"GOOG",           und:"GOOG", type:"STK",  notional:36519,  exposure:36519,  discount:0.000, delta:1.000,  iv:null},
  {label:"GOOG 410P Aug21",und:"GOOG", type:"POPT", notional:36519,  exposure:27361,  discount:0.251, delta:-0.749, iv:35.2},
  {label:"GOOG 360P Jul17",und:"GOOG", type:"POPT", notional:36519,  exposure:14742,  discount:0.596, delta:-0.404, iv:30.9},
  {label:"GOOG 280C Oct16",und:"GOOG", type:"COPT", notional:73037,  exposure:66745,  discount:0.086, delta:0.914,  iv:38.5},
  {label:"GOOG 250P Jul17",und:"GOOG", type:"POPT", notional:36519,  exposure:171,    discount:0.995, delta:-0.005, iv:54.6},

  {label:"MU 1000P Jul17", und:"MU",   type:"POPT", notional:112597, exposure:32255,  discount:0.714, delta:-0.287, iv:105.0},

  {label:"TSM 480P Jul17", und:"TSM",  type:"POPT", notional:45486,  exposure:27713,  discount:0.391, delta:-0.609, iv:52.8},
  {label:"TSM 460P Jul17", und:"TSM",  type:"POPT", notional:45486,  exposure:22537,  discount:0.504, delta:-0.496, iv:52.0},

  {label:"SMH 650P Jul17", und:"SMH",  type:"POPT", notional:65761,  exposure:28350,  discount:0.569, delta:-0.431, iv:56.0},

  {label:"ARM 480P Jul17", und:"ARM",  type:"POPT", notional:42753,  exposure:25300,  discount:0.408, delta:-0.592, iv:106.9},

  {label:"NVDL→NVDA",      und:"NVDA", type:"STK",  notional:40831,  exposure:40831,  discount:0.000, delta:2.000,  iv:null},
  {label:"COHR 390P Jul17",und:"COHR", type:"POPT", notional:39089,  exposure:17277,  discount:0.558, delta:-0.442, iv:89.2},
  {label:"DRAM 69P Jul02", und:"DRAM", type:"POPT", notional:34500,  exposure:16387,  discount:0.525, delta:-0.475, iv:49.2},
  {label:"SPCX",           und:"SPCX", type:"STK",  notional:17700,  exposure:17700,  discount:0.000, delta:1.000,  iv:null},
  {label:"SPCX 190P Jul17",und:"SPCX", type:"POPT", notional:17700,  exposure:9941,   discount:0.438, delta:-0.562, iv:88.1},
  {label:"MSFU→MSFT",      und:"MSFT", type:"STK",  notional:32550,  exposure:32550,  discount:0.000, delta:2.000,  iv:null},
  {label:"METU→META",      und:"META", type:"STK",  notional:25837,  exposure:25837,  discount:0.000, delta:2.000,  iv:null},
  {label:"AAOI",           und:"AAOI", type:"STK",  notional:1603,   exposure:1603,   discount:0.000, delta:1.000,  iv:null},
  {label:"IBKR",           und:"IBKR", type:"STK",  notional:1086,   exposure:1086,   discount:0.000, delta:1.000,  iv:null},
];

const fmt = (n,d=0) => n.toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtM = n => n>=1e6?`$${(n/1e6).toFixed(2)}M`:`$${fmt(n)}`;

function DonutChart({data, total, title, subtitle, onHover, hoveredUnd}) {
  const cx=160, cy=160, outerR=128, innerR=70;
  const slices=[];
  let angle=-Math.PI/2;
  data.forEach(d => {
    const frac=d.val/total, sa=angle, ea=angle+frac*2*Math.PI, mid=(sa+ea)/2;
    slices.push({...d,frac,sa,ea,mid});
    angle=ea;
  });
  const pol=(a,r)=>[cx+r*Math.cos(a), cy+r*Math.sin(a)];
  const arc=(sa,ea,r,R)=>{
    const lg=ea-sa>Math.PI?1:0;
    const [x1,y1]=pol(sa,R),[x2,y2]=pol(ea,R),[x3,y3]=pol(ea,r),[x4,y4]=pol(sa,r);
    return `M${x1} ${y1} A${R} ${R} 0 ${lg} 1 ${x2} ${y2} L${x3} ${y3} A${r} ${r} 0 ${lg} 0 ${x4} ${y4}Z`;
  };
  return (
    <div style={{display:"flex",flexDirection:"column",alignItems:"center"}}>
      <div style={{fontFamily:"'JetBrains Mono',monospace",fontSize:10,color:"#5a7a9a",letterSpacing:"0.1em",textTransform:"uppercase",marginBottom:4}}>{title}</div>
      <svg width={320} height={320} style={{overflow:"visible"}}>
        {slices.map(s=>{
          const isH=hoveredUnd===s.und, isO=hoveredUnd&&!isH;
          const R=isH?outerR+6:outerR;
          return <path key={s.und} d={arc(s.sa,s.ea,innerR,R)}
            fill={COLORS[s.und]||"#556"} opacity={isO?0.3:1}
            stroke="#070b14" strokeWidth={1.5} style={{cursor:"pointer",transition:"opacity 0.15s"}}
            onMouseEnter={()=>onHover(s.und)} onMouseLeave={()=>onHover(null)}/>;
        })}
        {slices.map(s=>{
          if(s.frac<0.012) return null;
          const [x1,y1]=pol(s.mid,outerR+4),[x2,y2]=pol(s.mid,outerR+14),[tx,ty]=pol(s.mid,outerR+22);
          const anc=Math.cos(s.mid)>0.1?"start":Math.cos(s.mid)<-0.1?"end":"middle";
          return <g key={"l"+s.und}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={COLORS[s.und]} strokeWidth={0.8} opacity={0.7}/>
            <text x={tx} y={ty} textAnchor={anc} dominantBaseline="middle"
              fill={COLORS[s.und]} fontSize={9.5} fontFamily="'JetBrains Mono',monospace" fontWeight="600">{s.und}</text>
          </g>;
        })}
        <text x={cx} y={cy-10} textAnchor="middle" fill="#c8ddf0" fontSize={13} fontFamily="'JetBrains Mono',monospace" fontWeight="700">{fmtM(total)}</text>
        <text x={cx} y={cy+8}  textAnchor="middle" fill="#4a7a9a" fontSize={9}  fontFamily="'JetBrains Mono',monospace">{subtitle}</text>
        <text x={cx} y={cy+22} textAnchor="middle" fill="#3a6a8a" fontSize={9}  fontFamily="'JetBrains Mono',monospace">{(total/NLV).toFixed(2)}× NLV</text>
      </svg>
    </div>
  );
}

export default function App() {
  const [view, setView]=useState("byUnd");
  const [tooltip, setTooltip]=useState(null);
  const [hoveredUnd, setHoveredUnd]=useState(null);

  const undN=UND_DATA.map(d=>({und:d.und,val:d.notional}));
  const undE=UND_DATA.map(d=>({und:d.und,val:d.exposure}));
  const posN=POSITIONS.map(p=>({und:p.und,label:p.label,val:p.notional}));
  const posE=POSITIONS.map(p=>({und:p.und,label:p.label,val:p.exposure}));

  const handleHover = und => {
    if(!und){setTooltip(null);setHoveredUnd(null);return;}
    setHoveredUnd(und);
    const row=UND_DATA.find(d=>d.und===und)||{notional:0,exposure:0};
    setTooltip({und, notional:row.notional, exposure:row.exposure,
      pctN:row.notional/TOTAL_NOTIONAL, pctE:row.exposure/TOTAL_EXPOSURE});
  };

  const bg="#070b14", card="#0c1422", border="#1a2d45", text="#c8ddf0", muted="#4a7a9a", accent="#2a6fb8", mono="'JetBrains Mono','Fira Code',monospace";

  return (
    <div style={{background:bg,minHeight:"100vh",color:text,fontFamily:mono,fontSize:12,paddingBottom:40}}>
      {/* Header */}
      <div style={{background:card,borderBottom:`1px solid ${border}`,padding:"14px 24px",display:"flex",flexWrap:"wrap",gap:16,alignItems:"center",justifyContent:"space-between"}}>
        <div>
          <div style={{fontSize:10,color:muted,letterSpacing:"0.12em",textTransform:"uppercase"}}>Portfolio Risk Dashboard</div>
          <div style={{fontSize:15,color:"#e0eeff",fontWeight:700,marginTop:2}}>Notional &amp; Delta Exposure — Jun 19, 2026</div>
        </div>
        <div style={{display:"flex",gap:20,flexWrap:"wrap"}}>
          {[["NLV",`$${fmt(NLV)}`],["Notional",`$${fmt(TOTAL_NOTIONAL)}`],["Notl Lev",`${NOTIONAL_LEV.toFixed(2)}×`],["Exposure",`$${fmt(TOTAL_EXPOSURE)}`],["Exp Lev",`${EXPOSURE_LEV.toFixed(2)}×`]].map(([l,v])=>(
            <div key={l} style={{textAlign:"right"}}>
              <div style={{fontSize:9,color:muted,letterSpacing:"0.1em"}}>{l}</div>
              <div style={{fontSize:13,color:"#e0eeff",fontWeight:700}}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Toggle */}
      <div style={{display:"flex",justifyContent:"center",padding:"14px 0 6px",gap:8}}>
        {[["byUnd","依標的"],["byPos","依倉位"]].map(([v,l])=>(
          <button key={v} onClick={()=>setView(v)} style={{background:view===v?accent:"transparent",border:`1px solid ${view===v?accent:border}`,color:view===v?"#fff":muted,fontFamily:mono,fontSize:11,letterSpacing:"0.08em",padding:"5px 16px",borderRadius:3,cursor:"pointer",transition:"all 0.15s"}}>{l}</button>
        ))}
      </div>

      {/* Charts */}
      <div style={{display:"flex",flexWrap:"wrap",justifyContent:"center",gap:20,padding:"4px 24px"}}>
        <DonutChart data={view==="byUnd"?undN:posN} total={TOTAL_NOTIONAL} title="名義 Notional" subtitle="Total Notional" onHover={handleHover} hoveredUnd={hoveredUnd}/>
        <DonutChart data={view==="byUnd"?undE:posE} total={TOTAL_EXPOSURE} title="曝險 Delta Exposure" subtitle="Δ-Weighted Exp" onHover={handleHover} hoveredUnd={hoveredUnd}/>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div style={{display:"flex",justifyContent:"center",marginTop:4}}>
          <div style={{background:card,border:`1px solid ${accent}`,borderRadius:4,padding:"8px 20px",display:"flex",gap:20,flexWrap:"wrap",alignItems:"center"}}>
            <div style={{color:"#e0eeff",fontWeight:700,fontSize:13,minWidth:60}}>{tooltip.und}</div>
            <div><span style={{color:muted,fontSize:10}}>Notional </span><span style={{color:"#e0eeff"}}>${fmt(tooltip.notional)}</span><span style={{color:muted,fontSize:10}}> ({(tooltip.pctN*100).toFixed(1)}%)</span></div>
            <div><span style={{color:muted,fontSize:10}}>Exposure </span><span style={{color:"#e0eeff"}}>${fmt(tooltip.exposure)}</span><span style={{color:muted,fontSize:10}}> ({(tooltip.pctE*100).toFixed(1)}%)</span></div>
            <div><span style={{color:muted,fontSize:10}}>Discount </span><span style={{color:tooltip.notional>0?(1-tooltip.exposure/tooltip.notional>0.3?"#4fc3a1":"#e8a03a"):"#fff"}}>{tooltip.notional>0?((1-tooltip.exposure/tooltip.notional)*100).toFixed(1)+"%":"—"}</span></div>
          </div>
        </div>
      )}

      {/* Greeks */}
      <div style={{display:"flex",justifyContent:"center",padding:"14px 24px 6px"}}>
        <div style={{background:card,border:`1px solid ${border}`,borderRadius:4,padding:"10px 32px",display:"flex",gap:40}}>
          {[["Net Δ (share-eq)",`${fmt(NET_DELTA)}`,"#4a9eff"],["Net Θ/day",`+$${fmt(NET_THETA,2)}`,"#4fc3a1"],["Net Vega /1%vol",`-$${fmt(Math.abs(NET_VEGA),2)}`,"#e8703a"]].map(([l,v,c])=>(
            <div key={l} style={{textAlign:"center"}}>
              <div style={{fontSize:9,color:muted,letterSpacing:"0.1em",marginBottom:4}}>{l}</div>
              <div style={{fontSize:15,color:c,fontWeight:700}}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div style={{display:"flex",flexWrap:"wrap",gap:5,justifyContent:"center",padding:"6px 24px"}}>
        {UND_DATA.map(d=>(
          <div key={d.und} onMouseEnter={()=>setHoveredUnd(d.und)} onMouseLeave={()=>setHoveredUnd(null)}
            style={{display:"flex",alignItems:"center",gap:5,cursor:"pointer",background:hoveredUnd===d.und?"#1a2d45":"transparent",border:`1px solid ${hoveredUnd===d.und?border:"transparent"}`,borderRadius:3,padding:"2px 8px",transition:"all 0.1s"}}>
            <div style={{width:7,height:7,borderRadius:1,background:COLORS[d.und]||"#556"}}/>
            <span style={{color:muted,fontSize:9}}>{d.und}</span>
            <span style={{color:"#607888",fontSize:9}}>{(d.notional/TOTAL_NOTIONAL*100).toFixed(1)}%N</span>
            <span style={{color:"#506070",fontSize:9}}>/{(d.exposure/TOTAL_EXPOSURE*100).toFixed(1)}%E</span>
          </div>
        ))}
      </div>

      {/* Underlying Table */}
      <div style={{padding:"10px 24px 0"}}>
        <div style={{fontSize:9,color:muted,letterSpacing:"0.12em",textTransform:"uppercase",marginBottom:6}}>標的明細 Underlying Breakdown</div>
        <div style={{overflowX:"auto"}}>
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:11}}>
            <thead>
              <tr style={{borderBottom:`1px solid ${border}`,color:muted}}>
                {["標的","Notional","Not%","Exposure","Exp%","Discount"].map((h,i)=>(
                  <th key={h} style={{padding:"4px 10px",textAlign:i===0?"left":"right",fontWeight:500,fontSize:9,letterSpacing:"0.08em",whiteSpace:"nowrap",position:i===0?"sticky":"static",left:0,background:i===0?card:"transparent"}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {UND_DATA.map(d=>{
                const disc=1-d.exposure/d.notional, isH=hoveredUnd===d.und;
                return (
                  <tr key={d.und} onMouseEnter={()=>setHoveredUnd(d.und)} onMouseLeave={()=>setHoveredUnd(null)}
                    style={{borderBottom:"1px solid #111b2a",background:isH?"#0f1e30":"transparent",transition:"background 0.1s"}}>
                    <td style={{padding:"5px 10px",position:"sticky",left:0,background:isH?"#0f1e30":card,display:"flex",alignItems:"center",gap:6}}>
                      <div style={{width:7,height:7,borderRadius:1,background:COLORS[d.und]||"#556"}}/>
                      <span style={{color:"#c0d8f0",fontWeight:600}}>{d.und}</span>
                    </td>
                    <td style={{padding:"5px 10px",textAlign:"right",color:"#a0c0e0"}}>${fmt(d.notional)}</td>
                    <td style={{padding:"5px 10px",textAlign:"right",color:muted}}>{(d.notional/TOTAL_NOTIONAL*100).toFixed(1)}%</td>
                    <td style={{padding:"5px 10px",textAlign:"right",color:"#a0c0e0"}}>${fmt(d.exposure)}</td>
                    <td style={{padding:"5px 10px",textAlign:"right",color:muted}}>{(d.exposure/TOTAL_EXPOSURE*100).toFixed(1)}%</td>
                    <td style={{padding:"5px 10px",textAlign:"right",color:disc>0.4?"#4fc3a1":disc>0.1?"#e8a03a":"#e86a3a"}}>{(disc*100).toFixed(1)}%</td>
                  </tr>
                );
              })}
              <tr style={{borderTop:`1px solid ${border}`,fontWeight:700}}>
                <td style={{padding:"6px 10px",position:"sticky",left:0,background:card,color:"#e0eeff"}}>TOTAL</td>
                <td style={{padding:"6px 10px",textAlign:"right",color:"#e0eeff"}}>${fmt(TOTAL_NOTIONAL)}</td>
                <td style={{padding:"6px 10px",textAlign:"right",color:muted}}>100%</td>
                <td style={{padding:"6px 10px",textAlign:"right",color:"#e0eeff"}}>${fmt(TOTAL_EXPOSURE)}</td>
                <td style={{padding:"6px 10px",textAlign:"right",color:muted}}>100%</td>
                <td style={{padding:"6px 10px",textAlign:"right",color:"#4fc3a1"}}>{((1-TOTAL_EXPOSURE/TOTAL_NOTIONAL)*100).toFixed(1)}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Position Table */}
      <div style={{padding:"14px 24px 0"}}>
        <div style={{fontSize:9,color:muted,letterSpacing:"0.12em",textTransform:"uppercase",marginBottom:6}}>倉位明細 Position Details</div>
        <div style={{overflowX:"auto"}}>
          <table style={{width:"100%",borderCollapse:"collapse",fontSize:10.5,minWidth:680}}>
            <thead>
              <tr style={{borderBottom:`1px solid ${border}`,color:muted}}>
                {["倉位","類型","Notional","Exposure","Discount","Δ","IV"].map((h,i)=>(
                  <th key={h} style={{padding:"4px 10px",textAlign:i<=1?"left":"right",fontWeight:500,fontSize:9,letterSpacing:"0.08em",whiteSpace:"nowrap",position:i===0?"sticky":"static",left:0,background:i===0?card:"transparent"}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {POSITIONS.map((p,i)=>{
                const isH=hoveredUnd===p.und;
                const tc=p.type==="STK"?"#4a7a9a":p.type==="COPT"?"#4a9eff":"#e8703a";
                return (
                  <tr key={i} onMouseEnter={()=>setHoveredUnd(p.und)} onMouseLeave={()=>setHoveredUnd(null)}
                    style={{borderBottom:"1px solid #0e1a28",background:isH?"#0f1e30":"transparent",transition:"background 0.1s"}}>
                    <td style={{padding:"4px 10px",position:"sticky",left:0,background:isH?"#0f1e30":card,display:"flex",alignItems:"center",gap:5,minWidth:160}}>
                      <div style={{width:6,height:6,borderRadius:1,background:COLORS[p.und]||"#556",flexShrink:0}}/>
                      <span style={{color:"#b0ccdf"}}>{p.label}</span>
                    </td>
                    <td style={{padding:"4px 10px",color:tc,fontSize:9,letterSpacing:"0.06em"}}>{p.type}</td>
                    <td style={{padding:"4px 10px",textAlign:"right",color:"#90b0d0"}}>${fmt(p.notional)}</td>
                    <td style={{padding:"4px 10px",textAlign:"right",color:"#90b0d0"}}>${fmt(p.exposure)}</td>
                    <td style={{padding:"4px 10px",textAlign:"right",color:p.discount>0.4?"#4fc3a1":p.discount>0.1?"#e8a03a":"#7090a0"}}>{(p.discount*100).toFixed(1)}%</td>
                    <td style={{padding:"4px 10px",textAlign:"right",color:p.delta<0?"#e8703a":"#4a9eff"}}>{p.delta!==null?(p.delta>0?"+":"")+p.delta.toFixed(3):"—"}</td>
                    <td style={{padding:"4px 10px",textAlign:"right",color:muted}}>{p.iv!==null?p.iv.toFixed(1)+"%":"—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
