# TODO

> 待辦/未來工作清單。先讀 [`DESIGN.md`](DESIGN.md) 了解整體架構,再動工。

## 換倉資金/保證金 what-if 的後續延伸

核心功能已實作,見 [`DESIGN.md`](DESIGN.md) §11(後端 `calc.roll_what_if` /
`regt_short_put_maint` / `call_strike_for_delta` / `exposure_match_sizing` +
三個無 I/O 端點;前端 `components/RollWhatIf.tsx` 面板)。以下為尚未做的延伸:

### 1. 建模 LookAhead(把換倉效果投影到 look-ahead 軸)

- 背景:IBKR 帳戶摘要除了當下的 `MaintMarginReq` / `ExcessLiquidity`,還給
  `LookAheadMaintMarginReq` / `LookAheadExcessLiquidity` —— 對「下一個已知保證金
  變動時點之後」的預測。兩個驅動:(a) 交易所每日更新的 SPAN 參數,(b) 接近到期的
  期權(到期/行權/ITM 處理會改變保證金待遇)。對 short option 特別關鍵:快到期的
  SP,其 current 與 look-ahead margin 可能差很多。
- 現況:這條軸已顯示在保證金卡(DESIGN §4),但 `roll_what_if` 只算 current 軸
  (現在的 EL/cushion before→後),**沒有投影到 look-ahead 軸**。
- 要做:估 `LookAhead EL₁` / cushion / level,回答「換倉後等下一次 SPAN 更新或
  SP 到期事件之後,緩衝會變怎樣」。
- 難點/取捨:
  - 只有整戶的兩個 LookAhead 數字,沒有逐筆 look-ahead 保證金。
  - 最簡版:假設 ΔEL 對 look-ahead 軸相同 → `LookAhead EL₁ = LookAhead EL₀ + ΣΔEL`
    (便宜但粗略;與現有 current 軸同公式)。
  - 較準版:若 look-ahead 變動正是「要平的 SP 接近到期」驅動,平掉它會直接移除該
    事件 → 不能只線性加減,需要 SP 到期日與 look-ahead 時點的對應關係(目前沒抓)。
  - 與整個 what-if 的限制一致:non-PM 線性近似;PM 帳戶務必以 TWS What-If 為準。

### 2. ETF 替代腿的自動 sizing

- 現況:`calc.exposure_match_sizing` 已可由曝險反算 call 口數(前端「依曝險配對口數」
  按鈕已接),但 **2x ETF 路徑的 V/股數還沒接 UI**(使用者目前手動輸入 ETF 市值)。
- 要做:選 ETF 替代腿時,用 `exposure_match_sizing(etf_leverage, etf_price)` 自動帶入
  曝險匹配的 ETF 市值與股數(需要 ETF 的價格輸入或從持倉/報價取得)。

> 已捨棄(deprecated):多腿 SP 同時平倉 —— 不再追蹤。
