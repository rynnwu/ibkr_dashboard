# TODO

> 待辦/未來工作清單。先讀 [`DESIGN.md`](DESIGN.md) 了解整體架構,再動工。

## ✅ 換倉資金可行性 + 保證金 what-if 工具(已實作)

> **已完成** — 見 [`DESIGN.md`](DESIGN.md) §11。後端 `calc.roll_what_if` /
> `regt_short_put_maint` / `exposure_match_sizing`(純函式、有單元測試)+
> `POST /api/roll-what-if`(無 I/O);前端 `components/RollWhatIf.tsx` 面板。
> 下方原始設計筆記保留作為公式/限制的參考。
>
> 未來可延伸:把 `exposure_match_sizing`(曝險匹配 sizing)接進 UI 自動帶入
> call 口數 / ETF 市值;支援多腿 SP 同時平倉;建模 LookAhead。

**目標**:在 dashboard 上估算「平倉 short put → 改開 long call / 買 2x ETF」
換倉後的 (a) 保證金緩衝變化、(b) 是否有足夠現金/可動用資金執行換倉。
這是現有「保證金緩衝監控」功能的延伸,**前置欄位都已備齊**
(`margin.cash`、`margin.availableFunds`、option ticker marks)。

### 背景:已具備的東西

- 後端 `ibkr_client.ACCOUNT_VALUE_TAGS` 已抓:`NetLiquidation`、`MaintMarginReq`、
  `ExcessLiquidity`、`LookAhead*`、`TotalCashValue`、`AvailableFunds`。
- `calc.margin_summary()` 已輸出 `level`(強平軸)與 `cash`/`availableFunds`/
  `canOpenNew`(銀彈軸)。詳見 DESIGN §4「Margin-buffer block」。
- SP 的 mark 可由 `_collect_positions` 取得的 `option_ticker_map` 取得。

### 設計(建議)

- **後端**:在 `calc.py` 加**純函式** `roll_what_if(...)`(可單元測試,無 I/O),
  回傳換倉後估計值。前端加一個輸入面板(要平的 SP、要建的 long call/ETF)。
- `MM_SP`(該 SP 目前佔的維持保證金)是**最脆弱的輸入**:
  - 預設用 Reg T 裸 put 近似式(下方),允許使用者**手動覆寫**為 TWS What-If 的實際值。

### 公式(來自本專案的討論;單位:每口 option = 100 股)

定義:
```
D       = Σ_SP   put_mark × 100 × |contracts|      # 平倉 SP 借方(下跌時膨脹)
Premium = Σ_call call_mark × 100 × Q               # 開 long call 權利金
```

**(1) 保證金緩衝試算**(EL = Excess Liquidity):
```
平倉 SP:        ΔEL = +MM_SP            (mark 換倉 NLV 中性,釋放維持保證金)
開 long call:   ΔEL = −Premium          (long option 無 loan value、不佔保證金)
買 2x ETF:      ΔEL = −(m × V)          (m=槓桿 ETF 維持率~50%+,V=ETF 市值,現金買)

EL₁ = EL₀ + ΣΔEL
Cushion₁ = EL₁ / NLV    (NLV 換倉近似不變)
level₁  = 複用 calc.margin_summary 的門檻判定
```

**(2) 換倉資金可行性**(long call 不能融資、須全額付):
```
Cash₀           = TotalCashValue
LoanValue_other = Σ(其他可質押證券市值 × (1 − 維持率))   # 不含 long option 本身

Surplus  = Cash₀ + LoanValue_other − D − Premium
可開倉   ⟺ Surplus ≥ 0
缺口     = −Surplus

# 純現金/裸 put 帳戶(LoanValue_other = 0)簡化:
可開倉   ⟺ TotalCashValue ≥ D + Premium

# 等價聚合版(用 IBKR 現成欄位):
AvailableFunds₁ = AvailableFunds₀ + 釋放的 IM_SP
可開倉   ⟺ AvailableFunds₁ ≥ Premium
```
> 陷阱:下跌時 `D` 膨脹,同時壓低 `AvailableFunds₀`(SP 市值是負債)→ 雙重打擊。

**曝險匹配的 sizing**:
```
E_target = |contracts| × 100 × S × |delta_SP|     # 或想要的前瞻曝險
long call: Q = E_target / (100 × S × delta_call)
2x ETF:    V = E_target / 2,  shares = V / p
```

**MM_SP 的 Reg T 裸 put 近似式**(fallback,允許手動覆寫):
```
MM_SP ≈ |n| × 100 × [ max( 0.20×S − max(S−K, 0),  0.10×K ) + P_put ]
```

### 必記限制

- IBKR 實際用 TIMS/SPAN 情境模型(尤其 Portfolio Margin),**整戶非線性、無法逐筆線性拆解**
  → 本試算是數量級參考,非精確值;PM 帳戶務必以 TWS What-If 為準。
- long option loan value 假設為 0(Reg T);PM 下不同。
- 忽略 bid/ask 價差、手續費;未建模 LookAhead。

### 相關討論

「清掉其他正股、改用 long call 維持 exposure 同時釋放現金」也適用同一套公式:
釋放現金 ≈ `V × (1 − f/d)`(f=權利金/正股比例,d=call delta);
這是 SP 換倉時現金的來源之一。
