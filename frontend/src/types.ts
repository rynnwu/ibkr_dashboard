export interface UnderlyingRow {
  symbol: string;
  notional: number;
  exposure: number;
  color: string;
  iconUrl: string | null;
}

export interface PositionRow {
  label: string;
  underlying: string;
  type: "STK" | "COPT" | "POPT";
  notional: number;
  exposure: number;
  discount: number;
  delta: number | null;
  iv: number | null;
}

export interface MarginSummary {
  maintMargin: number;
  excessLiquidity: number;
  // ExcessLiquidity / NLV (IBKR's "cushion" ratio); drives the risk level.
  cushion: number;
  // ExcessLiquidity / MaintMarginReq; null when there's no maintenance req.
  bufferRatio: number | null;
  level: "safe" | "warning" | "danger";
  // IBKR's projection after the next known margin change; optional.
  lookAheadMaintMargin?: number;
  lookAheadExcessLiquidity?: number;
}

export interface PortfolioResponse {
  nlv: number;
  totalNotional: number;
  totalExposure: number;
  notionalLeverage: number;
  exposureLeverage: number;
  netDelta: number;
  netTheta: number;
  netVega: number;
  underlyings: UnderlyingRow[];
  positions: PositionRow[];
  // Margin-buffer snapshot; null when account margin values were unavailable
  // (cash account, or an older cached snapshot from before this field existed).
  margin: MarginSummary | null;
  warnings: string[];
  // true when IB Gateway was unreachable and this payload is the last cached
  // snapshot rather than a live fetch. cachedAt is the time the data was
  // originally fetched (local-time ISO 8601), used to show how stale it is.
  stale: boolean;
  cachedAt: string | null;
}
