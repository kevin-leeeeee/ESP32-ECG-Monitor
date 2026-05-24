# 🩺 ESP32 ECG 自律神經檢測系統

基於 **ESP32 + AD8232** 的即時心電圖 (ECG) 擷取與自律神經 (HRV) 分析系統，支援手機 App 與 PC 端雙平台同步量測。

---

## 📸 系統架構

```
┌─────────────┐     BLE 藍牙      ┌──────────────────┐
│  ESP32 +    │ ◄──────────────► │  📱 手機 App      │
│  AD8232     │     250Hz        │  (React Native)   │
│  心電感測器  │                   └──────────────────┘
│             │     USB Serial    ┌──────────────────┐
│             │ ◄──────────────► │  💻 PC 端         │
└─────────────┘     250Hz        │  (Python + Web)   │
                                  └──────────────────┘
```

## ✨ 核心功能

### 🔬 訊號處理與分析
- **Pan-Tompkins 自適應雙閾值 R 波偵測演算法**：自動校準訊號與噪聲閾值，支援回溯搜尋機制補償漏判
- **訊號品質評估 (SQI)**：即時偵測雜訊干擾，自動啟用低通濾波平滑處理
- **HRV 自律神經分析**：計算 SDNN、RMSSD、交感/副交感活性比例、神經活力分數
- **ACLS 心電傳導間期分析**：PR 間期、QRS 波寬、QT 間期自動量測與診斷
- **呼吸率推估**：透過 RR 間隔變異分析推算呼吸頻率

### 📱 手機 App (React Native / Expo)
- BLE 低功耗藍牙即時連線與數據串流
- 待機狀態即時心電圖波形預覽（連線即顯示）
- 電極貼片脫落 (Leads-off) 即時偵測與 UI 警告
- 自訂量測時間 (10~600 秒)
- 分離式高效波形儲存（分析指標 JSON + 原始波形 CSV 分檔）
- 橫向滑動式 SVG 歷史心電圖重播
- 身心健康狀態評估與專家調整建議

### 💻 PC 端 (Python + Matplotlib + Web)
- USB Serial / BLE 雙模式連線
- Matplotlib 即時波形繪圖與 R 波標記
- Web Dashboard 即時監控介面
- 原始數據 CSV 自動存檔與波形截圖

### 🔧 ESP32 韌體 (PlatformIO / Arduino)
- AD8232 類比訊號 12-bit ADC 採集 (250Hz)
- Leads-off Detection (LO+/LO-) 電極脫落偵測
- BLE Notify 批次打包傳輸 (每包 10 筆 = 20 bytes)
- USB Serial 同步輸出（支援 PC 端接收）

---

## 🛠️ 技術棧與開發工具

### 硬體
| 元件 | 說明 |
|------|------|
| **ESP32 DevKit** | 主控 MCU，負責 ADC 採集與 BLE 藍牙傳輸 |
| **AD8232** | 單導程心電圖 (ECG) 類比前端模組 |
| **Ag/AgCl 電極貼片** | 三電極配置 (RA/LA/LL) |

### 軟體與框架
| 工具 / 框架 | 用途 |
|-------------|------|
| **PlatformIO** | ESP32 韌體編譯與燒錄環境 |
| **Arduino Framework** | ESP32 開發框架 |
| **React Native (Expo)** | 手機 App 跨平台開發 |
| **react-native-ble-plx** | BLE 藍牙通訊函式庫 |
| **react-native-svg** | 高效能 SVG 心電圖渲染 |
| **expo-file-system** | 本地波形檔案讀寫 |
| **AsyncStorage** | 手機端歷史紀錄持久化儲存 |
| **Python 3** | PC 端接收器與數據分析 |
| **Matplotlib** | PC 端即時波形視覺化 |
| **Bleak** | Python BLE 藍牙通訊 |

### 開發環境
| 工具 | 說明 |
|------|------|
| **VS Code** | 主要程式碼編輯器 |
| **GitHub CLI (gh)** | 版本控制與專案管理 |
| **Expo Go** | 手機端即時預覽與測試 |

---

## 🤖 AI 輔助開發

本專案在開發過程中大量運用 **AI 輔助開發工具** 加速迭代：

| AI 工具 | 輔助範圍 |
|---------|---------|
| **Google Gemini (Antigravity)** | 架構設計、演算法實作、即時除錯與程式碼重構 |
| **Claude (Anthropic)** | 複雜邏輯分析、React 閉包陷阱診斷、效能優化建議 |

### AI 輔助的關鍵貢獻
- **Pan-Tompkins 演算法實作**：自適應雙閾值 R 波偵測邏輯、回溯搜尋機制的數學建模與程式轉譯
- **React 狀態管理除錯**：診斷出藍牙訂閱回呼函數中的 State Closure 陷阱，並以函數式更新 (Functional Updates) 修復 Leads-off 警報無法消除的 Bug
- **儲存架構設計**：設計分離式波形儲存方案 (JSON 索引 + CSV 原始數據分檔)，優化大量數據的 I/O 效能
- **訊號處理流程**：SQI 品質評估、自適應低通濾波、基線漂移校正等數位訊號處理鏈的實作
- **UI/UX 互動設計**：橫向滑動式 SVG 心電圖重播、分析失敗的降級 UI 與使用者引導

> 💡 AI 工具作為開發加速器，負責程式碼生成與技術方案建議；所有功能設計決策、硬體接線、實機測試與驗證均由開發者主導完成。

---

## 📁 專案結構

```
自律神經檢測/
├── src/
│   └── main.cpp              # ESP32 韌體 (ADC + BLE + Leads-off)
├── platformio.ini             # PlatformIO 編譯設定
├── mobile_app/
│   ├── App.js                 # 手機 App 主程式
│   ├── src/utils/
│   │   └── ecgAnalyzer.js     # Pan-Tompkins HRV 分析引擎
│   ├── package.json           # Node.js 依賴管理
│   └── app.json               # Expo 設定
├── pc_client/
│   ├── receiver.py            # PC 端接收器 (Serial + BLE + Matplotlib)
│   ├── web/
│   │   └── index.html         # Web Dashboard 即時監控介面
│   └── raw_data/              # 歷史量測原始數據 (CSV + PNG)
├── .gitignore
└── README.md
```

---

## 🚀 快速開始

### 1. ESP32 韌體燒錄
```bash
# 使用 PlatformIO 編譯並燒錄
pio run --target upload
```

### 2. 手機 App 啟動
```bash
cd mobile_app
npm install
npx expo start --tunnel
```
使用 **Expo Go** App 掃描 QR Code 即可連線。

### 3. PC 端接收器
```bash
cd pc_client
pip install matplotlib bleak pyserial numpy
python receiver.py
```

---

## ⚡ 接線圖

| AD8232 腳位 | ESP32 腳位 | 說明 |
|-------------|-----------|------|
| GND | GND | 接地 |
| 3.3V | 3.3V | 供電 |
| OUTPUT | GPIO 36 (VP) | ECG 類比訊號輸出 |
| LO+ | GPIO 35 | Leads-off 偵測 + |
| LO- | GPIO 34 | Leads-off 偵測 - |

### 電極貼片位置
| 顏色 | 標記 | 位置 |
|------|------|------|
| 🔴 紅色 | RA | 右鎖骨下方 |
| 🟡 黃色 | LA | 左鎖骨下方 |
| 🟢 綠色 | LL | 左下腹 (參考電極) |

---

## 📄 授權

MIT License
