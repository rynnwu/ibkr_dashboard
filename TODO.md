# TODO

> 待辦/未來工作清單。先讀 [`DESIGN.md`](DESIGN.md) 了解整體架構,再動工。

## 換倉資金/保證金 what-if 的後續延伸

核心功能已實作,見 [`DESIGN.md`](DESIGN.md) §11(後端 `calc.roll_what_if` /
`regt_short_put_maint` / `call_strike_for_delta` / `exposure_match_sizing` +
三個無 I/O 端點;前端 `components/RollWhatIf.tsx` 面板)。以下為尚未做的延伸:

### 1. ETF 替代腿的自動 sizing

- 現況:`calc.exposure_match_sizing` 已可由曝險反算 call 口數(前端「依曝險配對口數」
  按鈕已接),但 **2x ETF 路徑的 V/股數還沒接 UI**(使用者目前手動輸入 ETF 市值)。
- 要做:選 ETF 替代腿時,用 `exposure_match_sizing(etf_leverage, etf_price)` 自動帶入
  曝險匹配的 ETF 市值與股數(需要 ETF 的價格輸入或從持倉/報價取得)。

> 已捨棄(deprecated):
> - 多腿 SP 同時平倉。
> - 建模 LookAhead —— 使用者的換倉策略是 DTE ≤ 14 就 roll,不依賴 look-ahead 投影。
