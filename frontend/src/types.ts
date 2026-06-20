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
}
