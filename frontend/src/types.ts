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
  warnings: string[];
  // true when IB Gateway was unreachable and this payload is the last cached
  // snapshot rather than a live fetch. cachedAt is the time the data was
  // originally fetched (local-time ISO 8601), used to show how stale it is.
  stale: boolean;
  cachedAt: string | null;
}
