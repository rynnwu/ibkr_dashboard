# IBKR 持倉名義／曝險圓餅圖儀表板 — 設計規格

## 動機與目標

目前的流程是把 `examples/Prompt of notional pie chart.md` 貼進 Claude 對話，
靠 MCP 工具抓資料、Claude 跑 Python 算 Greeks、輸出一個 React 元件
（`examples/portfolio pie.tsx` 即為一次輸出結果）。這個流程每次都要燒
大量 LLM token，且無法獨立於 Claude 重複執行。

目標：把整套邏輯改寫成**獨立的 Python + React 程式**，往後刷新持倉/報價
只需要本機程式呼叫 IBKR API，完全不需要 LLM 介入。

**非目標**
- 不做下單、不做任何寫入類操作（read-only）
- 不需要 realtime 推送；資料只在使用者按「重新整理」時才重新抓取
- 不取代 IBKR Desktop／TWS，只是額外的個人分析儀表板

## 整體架構

```
┌─────────────┐   ib_insync (socket, :4001)   ┌──────────────┐
│  IB Gateway  │ ◄──────────────────────────── │  Python 後端  │
│ (IB API 模式,│ ──────────────────────────────►│  (FastAPI)   │
│  已手動登入)  │                                └──────┬───────┘
└─────────────┘                                        │ GET /api/portfolio
                                                        │ (按「重新整理」才打)
                                                ┌───────▼────────┐
                                                │   React 前端    │
                                                │ (Vite + TS,    │
                                                │ 沿用範例 UI/邏輯)│
                                                └────────────────┘
```

- 使用者需自行先開啟 **IB Gateway**，登入模式選 **IB API**（不是 FXI CTCI），
  port 用 **4001**（live 帳戶），並建議勾選 Gateway 端的 **Read-Only API** 選項。
- 後端與前端是兩個獨立可重複啟動的程式，彼此用 HTTP 溝通；後端不快取資料，
  每次 `/api/portfolio` 被呼叫就即時重新抓一次。

## 後端設計（`backend/`，Python）

### 技術選擇
- `ib_insync`（或其維護分支 `ib_async`）連接 IB Gateway
- `FastAPI` 提供單一端點 `GET /api/portfolio`
- `scipy`（或自寫二分法）作為 Greeks 的 fallback 計算

### 連線設定
- Host `127.0.0.1`，Port `4001`，固定 `clientId`（例如 `7`）
- 程式啟動時建立一條 `IB()` 連線，供 FastAPI 請求重用；若連線中斷，
  在下次請求時嘗試重連，重連失敗則回傳 503 並附上「請確認 IB Gateway
  已啟動並登入」的錯誤訊息

### 資料抓取流程（`GET /api/portfolio` 處理邏輯）
1. `ib.positions()` 取得全部持倉（含股票與選擇權）
2. `ib.accountSummary()` 取得 `NetLiquidation`（NLV）
3. 對每個 contract：
   - 股票／ETF：`reqMktData` 拿 last/mark 現價
   - 選擇權：`reqMktData` 拿 mark 與 `ticker.modelGreeks`
     - **優先用 A 方案**：直接讀 `modelGreeks.delta/theta/vega/impliedVol`
     - **若逾時或無市場數據訂閱（`modelGreeks` 為 `None`）**：fallback 用
       B 方案——以 mark price 二分法反推 IV，再用 Black-Scholes 公式算
       Delta/Theta/Vega（`r≈4.25%`，股利率查 config，年化以「日曆天/365」）
4. 套用 `config.json` 裡的**槓桿 ETF → 母股映射表**（預設
   `TSLL→TSLA×2`、`NVDL→NVDA×2`、`MSFU→MSFT×2`、`METU→META×2`，
   可自行擴充新的對應）
5. 依下列公式逐倉計算：
   - `Notional`：選擇權 `|口數|×100×標的現價`；股票 `股數×現價`；
     槓桿 ETF `倍數×市值`（歸到母股）
   - `Exposure`：`Notional × |Delta|`（股票/槓桿 ETF 的 Delta 視為
     1／倍數，故 Notional＝Exposure）
   - `Discount`：`1 − Exposure / Notional`
6. 依標的（underlying）彙總出 `Notional`、`Exposure` 加總
7. 計算整戶指標：
   - `名義槓桿 = 總 Notional / NLV`，`曝險槓桿 = 總 Exposure / NLV`
   - **Greeks 卡**（僅計選擇權）：淨 Delta（股當量）、淨 Theta/日、
     淨 Vega（每 1 vol point）
8. 回傳 JSON，結構對應前端所需的 `UND_DATA` / `POSITIONS` / 總額 / NLV /
   Greeks 卡欄位

### 設定檔（`backend/config.json`）
```json
{
  "leveraged_etf_map": {
    "TSLL": {"underlying": "TSLA", "multiplier": 2},
    "NVDL": {"underlying": "NVDA", "multiplier": 2},
    "MSFU": {"underlying": "MSFT", "multiplier": 2},
    "METU": {"underlying": "META", "multiplier": 2}
  },
  "dividend_yield": {
    "GOOG": 0.005, "MU": 0.004, "TSM": 0.012
  },
  "risk_free_rate": 0.0425,
  "ib_gateway": {"host": "127.0.0.1", "port": 4001, "client_id": 7},
  "logo_api": {"provider": "TBD-於實作階段挑選", "api_key": ""}
}
```
未列在 `dividend_yield` 的標的預設股利率為 0。此檔案可直接編輯，不需改程式碼。
`logo_api.api_key` 需使用者自行申請後填入；缺值時圖示一律走文字 fallback。

### 錯誤處理
- IB Gateway 未啟動／未登入 → 回傳 503 + 友善訊息，前端顯示提示而非整頁壞掉
- 個別 contract 查無資料／市場數據逾時 → 該筆倉位跳過並在回應中附 `warnings`
  列表，不讓單一倉位卡死整個請求

### 標的圖示與顏色同步

- 對每個標的（underlying），後端嘗試向公開 logo API（依 ticker 查圖，
  具體服務與免費 API key 在實作階段研究挑選，填入 `config.json`）抓取圖示，
  存到本機快取目錄 `backend/icon_cache/<SYMBOL>.png`，**只抓一次、長期重用**
  （除非快取被手動清除）
- 抓圖成功時，用 Pillow 算出該圖的主色／平均色（hex），一併存進
  `backend/icon_cache/colors.json`；之後圓餅圖該標的的顏色直接用這個色碼，
  取代原範例中手動維護的 `COLORS` 表
- 抓圖失敗（API 無此標的圖／逾時）的標的：
  - 圖示 fallback 為「圓底＋代號縮寫文字」的本機產生圖（不需外部服務）
  - 顏色 fallback 為「標的代號雜湊產生的固定色」（同代號永遠同色，但與
    品牌色無關，純粹保證圖表顏色穩定不重複）
- `/api/portfolio` 回應內每個標的物件附上 `iconUrl`（後端靜態檔路徑）與
  `color`（hex），前端不再需要自己維護顏色表

## 前端設計（`frontend/`，Vite + React + TypeScript）

- 直接沿用 `examples/portfolio pie.tsx` 的視覺與互動邏輯
  （`DonutChart` SVG 甜甜圈、依標的/依倉位切換、hover tooltip、
  Greeks 卡、標的明細表、倉位明細表、深色終端機風格）
- 移除檔案開頭寫死的 `NLV`/`UND_DATA`/`POSITIONS`/`COLORS` 等常數，
  改成元件掛載時或按下「重新整理」按鈕時 `fetch('/api/portfolio')`
- `COLORS` 表改為直接使用後端回傳的每個標的 `color` 欄位；圖例與明細表
  標的名稱旁加上後端回傳的 `iconUrl` 小圖示（16~20px 圓形/方形 icon）
- 新增三種畫面狀態：載入中（spinner/骨架）、錯誤（顯示後端回的友善訊息，
  附「重試」按鈕）、正常顯示（沿用原 UI）
- 開發時 Vite dev server 代理 `/api` 到後端（例如 `127.0.0.1:8000`）

## 專案結構

```
ibkrpiechart/
├── backend/
│   ├── main.py          # FastAPI app, /api/portfolio
│   ├── ibkr_client.py   # ib_insync 連線與資料抓取
│   ├── calc.py          # notional/exposure/discount/Black-Scholes 計算
│   ├── icons.py          # logo 抓取／快取／主色萃取／文字 fallback 產生
│   ├── icon_cache/       # 快取的圖示檔 + colors.json
│   ├── config.json
│   └── requirements.txt
├── frontend/
│   ├── src/App.tsx       # 改自 examples/portfolio pie.tsx
│   ├── src/components/DonutChart.tsx
│   └── ...（Vite 標準結構）
└── examples/              # 既有參考檔案，保留不動
```

## 測試策略

- **計算邏輯單元測試**（`backend/calc.py`）：用 `examples/portfolio pie.tsx`
  裡的既有數字當測試 fixture（例如 TSLA 200C Oct16：Notional 39284、
  Delta 0.970 → Exposure ≈ 38117、Discount ≈ 3%），驗證
  notional/exposure/discount/Black-Scholes 公式正確
- **IB 連線部分無法自動化測試**（需要真實 Gateway 連線），採手動驗收：
  啟動後端＋前端，對照 IB Gateway/IBKR Desktop 上看到的持倉與市值，
  確認圖表數字一致

## 安全性

- 程式碼中不引入、不呼叫任何下單/修改類 API（`placeOrder`、
  `cancelOrder` 等一律不使用）
- 建議使用者在 IB Gateway 設定中啟用 **Read-Only API**，從帳戶端再加一層防護
