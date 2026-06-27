export interface UnderlyingRow {
  symbol: string;
  notional: number;
  exposure: number;
  color: string;
  iconUrl: string | null;
  // Beta vs SPX used for the hedge calc; null when defaulted to 1.0.
  beta?: number | null;
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
  // Surfaced for the roll what-if SP picker; null for stock / when unpriced.
  strike: number | null;
  mark: number | null;
  quantity: number;
  underlying_price: number;
  // Calendar days to expiry (null for stock); used to model-price legs.
  daysToExpiry: number | null;
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
  // Funding axis (separate from `level`): can we still open/roll positions?
  // canOpenNew is availableFunds > 0; availableFunds hits 0 before liquidation.
  cash?: number;
  availableFunds?: number;
  canOpenNew?: boolean;
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
  // Net signed beta-weighted dollar exposure (the SPX-equivalent $ to hedge) and
  // its leverage vs NLV; SPX index level. See DESIGN §12.
  netBetaWeightedExposure: number;
  betaWeightedLeverage: number;
  spxLevel: number;
  // Beta-weighted leverage above which the hedge-suggestion banner shows.
  spxHedgeWarningLeverage: number;
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

// ─── Roll what-if (POST /api/roll-what-if) ──────────────────────────────────
export interface RollWhatIfRequest {
  excessLiquidity: number;
  nlv: number;
  cash?: number;
  availableFunds?: number;
  loanValueOther?: number;
  spContracts: number;
  spUnderlyingPrice: number;
  spStrike: number;
  spPutMark: number;
  mmSpOverride?: number;
  openCallPremium?: number;
  openEtfValue?: number;
  etfMaintRate?: number;
}

export type MarginLevel = "safe" | "warning" | "danger";

export interface RollWhatIfResult {
  excessLiquidityBefore: number;
  excessLiquidityAfter: number;
  cushionBefore: number;
  cushionAfter: number;
  levelBefore: MarginLevel;
  levelAfter: MarginLevel;
  deltaExcessLiquidity: {
    closeShortPut: number;
    openLongCall: number;
    buyLeveragedEtf: number;
  };
  mmSp: number;
  mmSpAuto: boolean;
  closeSpDebit: number;
  openCallPremium: number;
  openEtfValue: number;
  // Funding axis — present only when `cash` was supplied.
  fundingOutflow?: number;
  surplus?: number;
  canExecute?: boolean;
  shortfall?: number;
  // Present only when `availableFunds` was supplied.
  availableFundsAfter?: number;
}

// ─── Model option pricing (POST /api/price-option) ──────────────────────────
export interface PriceOptionRequest {
  underlyingPrice: number;
  strike: number;
  daysToExpiry: number;
  right: "C" | "P";
  iv: number; // implied volatility in percent
  dividendYield?: number;
}

export interface PriceOptionResult {
  mark: number;
  delta: number;
  theta: number;
  vega: number;
  iv: number;
}

// ─── Suggest replacement call (POST /api/suggest-call) ──────────────────────
export interface SuggestCallRequest {
  underlyingPrice: number;
  shortPutDelta: number;
  iv: number; // percent
  daysToExpiry?: number;
  minDelta?: number;
  dividendYield?: number;
}

export interface SuggestCallResult {
  strike: number;
  daysToExpiry: number;
  iv: number;
  targetDelta: number;
  mark: number;
  delta: number;
}

// ─── SPX-put hedge (POST /api/spx-hedge) ────────────────────────────────────
export interface SpxHedgeRequest {
  netExposure: number;
  nlv: number;
  hedgeFraction?: number;
  targetLeverage?: number; // size the minimum hedge to get post-hedge leverage under this
  targetDelta?: number;
  floorDelta?: number; // lower (short) put leg for vertical/seagull
  targetDte?: number; // treated as an upper cap on the chosen expiry's DTE
  assumedIv?: number; // percent
  spxLevel?: number; // fallback if no live SPX cache this session
}

export interface HedgeLeg {
  right: "P" | "C";
  strike: number;
  contracts: number; // signed: long +, short −
  price: number; // per-share premium
  delta: number; // per-share BS delta
  cost: number; // whole-position cost: +debit / −credit
}

export interface HedgeProposal {
  kind: "long_put" | "vertical" | "seagull";
  contracts: number; // shared N
  legs: HedgeLeg[];
  cost: number; // net cost: +debit / −credit (≈0 for seagull)
  deltaOffset: number;
  netExposureBefore: number;
  netExposureAfter: number;
  leverageBefore: number;
  leverageAfter: number;
  protectionFloor: number | null; // short-put strike (vertical/seagull); null for long put
  upsideCap: number | null; // short-call strike (seagull); else null
  maxProtection: number | null; // capped payoff between long & floor strikes
}

export interface SpxHedgeResult {
  contracts: number; // whole tradeable contracts shared across proposals
  targetLeverage: number | null; // null when sized by fraction instead of target leverage
  netExposureBefore: number;
  leverageBefore: number;
  spxLevel: number;
  dte: number;
  iv: number;
  longPutStrike: number;
  floorPutStrike: number;
  proposals: HedgeProposal[];
  source: "live" | "model";
  cachedAt: string | null; // when the SPX market snapshot was taken
  targetDelta: number;
  floorPutDelta: number;
}
