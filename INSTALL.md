# ⚙️ 系統安裝與執行指南

本專案支援兩種不同的連線量測方式。在開始安裝前，您可以根據需求與硬體條件，選擇最適合的方案：

---

## 🚀 連線量測方案選擇與利弊分析

| 方案 | 連線媒介 | 適合場景 | 優點 (Pros) | 缺點 (Cons) |
| :--- | :--- | :--- | :--- | :--- |
| **📱 手機 App 方案** | 藍牙 BLE (無線) | 隨身攜帶、居家量測、日常自律神經健康監測 | 1. **極佳便攜性**：擺脫電腦與線路束縛，隨處可測。<br>2. **安全抗干擾**：無線傳輸，杜絕電腦漏電電擊風險。<br>3. **精美 UI**：整合 SVG 歷史波形重播與 HRV 統計圖表。 | 1. **首次部署較繁瑣**：因原生藍牙套件限制，需透過 Expo EAS 雲端編譯客製 APK 安裝包，無法直接用標準 Expo Go。 |
| **💻 電腦 PC 方案** | USB 序列埠 (有線)<br>或 藍牙 BLE | 實驗室測試、長時間數據採集、學術研發、二次濾波開發 | 1. **極速部署**：只需安裝 Python 與依賴庫，即可一鍵執行運作，不需打包安裝 App。<br>2. **數據傳輸極穩定**：USB 有線連接無封包遺失問題。<br>3. **易於二次開發**：可輕鬆將數據匯出為 CSV/DataFrame 做科研分析。 | 1. **缺乏便攜性**：量測時受限於 USB 線長度。<br>2. **電源噪聲挑戰**：若電腦接地不良，極易透過 USB 引入工頻雜訊。*（建議使用 USB 隔離器或改用行動電源供電+電腦藍牙連線）* |

---

## 🔌 1. ESP32 韌體端 (Firmware)

韌體代碼位於專案根目錄下的 `src/` 中，採用 **PlatformIO** 進行專案管理。

### 環境需求
* 安裝 [VS Code](https://code.visualstudio.com/)。
* 在 VS Code 的 Extensions (擴充功能) 中搜尋並安裝 **PlatformIO IDE**。

### 燒錄步驟
1. 使用 VS Code 開啟本專案的根目錄 `自律神經檢測/`。
2. PlatformIO 會自動識別根目錄下的 `platformio.ini` 並載入專案。
3. 將 ESP32 開發板透過 USB 數據線連接至電腦。
4. 點擊 VS Code 左下角狀態列的 **PlatformIO: Build (打勾圖示)** 進行編譯。
5. 編譯成功後，點擊 **PlatformIO: Upload (右箭頭圖示)** 將韌體燒錄至 ESP32。

---

## 📱 2. 手機 App 端 (React Native / Expo)

手機 App 原始碼位於 `mobile_app/` 目錄下，基於 **Expo** 框架與原生藍牙庫 `react-native-ble-plx` 開發。

### 🚨 藍牙功能運作原理與 Expo Go 限制 (極重要！)
* **標準 Expo Go 限制**：由於原生藍牙模組需要特定的硬體驅動權限，官方標準的 **Expo Go** App **並不內建原生藍牙套件**。若您直接在標準 Expo Go 中啟動專案，App 將會因找不到藍牙驅動而**崩潰或無法搜尋裝置**。
* **解決方案**：您必須透過 **Expo 官方網站的雲端編譯服務 (EAS Build)**，編譯一個專屬於您本專案的「客製化開發版 App (Development Build)」。

---

### 第一步：環境準備
1. 安裝 [Node.js](https://nodejs.org/) (建議 LTS 版本)。
2. 在 `mobile_app` 目錄下安裝 Node.js 依賴套件：
   ```bash
   cd mobile_app
   npm install
   ```

---

### 第二步：使用 Expo 官網雲端編譯客製化 App (EAS Build)
這會將原生的藍牙驅動代碼編譯進您的安裝包中，並生成安裝於手機的客製化 App：

1. **註冊 Expo 帳號**：至 [Expo 官方網站 (expo.dev)](https://expo.dev/) 免費註冊一個開發者帳號。
2. **安裝 EAS 終端機工具**：在電腦的終端機執行命令安裝：
   ```bash
   npm install -g eas-cli
   ```
3. **登入您的帳號**：在終端機中執行並輸入您的帳號密碼登入：
   ```bash
   eas login
   ```
4. **初始化專案關聯**：
   ```bash
   eas project:init
   ```
5. **啟動雲端編譯 (以 Android APK 為例)**：
   執行以下命令，指示 Expo 官網伺服器在雲端為您編譯 Android 開發版安裝包 (APK)：
   ```bash
   eas build --platform android --profile development
   ```
   * *編譯過程中，系統會提示您生成 Android 憑證，請一路輸入 `Yes` 或直接按 Enter 同意。*
   * *Expo 雲端伺服器會將您的專案代碼與原生藍牙套件進行打包編譯。*
6. **下載與安裝客製化 App**：
   * 編譯完成後（通常需要 3~5 分鐘），終端機會印出下載連結以及一個 **QR Code**。
   * 使用手機掃描該 QR Code 下載產生的 **`.apk` 檔案** 並安裝到手機上。
   * 此時手機上會多出一個名稱為您專案名稱的客製化 App（它內部已打包了藍牙原生驅動）。

---

### 第三步：本地開發伺服器連線與執行
1. 在電腦終端機啟動支援開發端的 Expo 伺服器 (注意加上 `--dev-client` 參數)：
   ```bash
   npx expo start --dev-client
   ```
2. 開啟手機上剛才安裝好的 **客製化 App** (而非官方標準 Expo Go)。
3. 使用該 App 內建的掃描器，掃描電腦終端機出現的 QR Code。
4. App 便會順利載入本地代碼，此時即可正常使用藍牙 BLE 連線和 Leads-off 檢測功能！

---

### 🚨 藍牙設定與手機端權限
在客製化 App 啟動後，請確保手機完成了以下設定以保證搜尋正常：
1. **開啟手機藍牙與定位 (GPS) 服務**。
2. 系統彈出提示時，**必須允許 App 使用「藍牙/周邊裝置掃描」與「精確位置資訊」權限**（Android 系統限制藍牙掃描必須配合定位權限）。
3. 若連線異常，請手動前往手機的 `設定 ➡️ 應用程式管理 ➡️ 您的 App ➡️ 權限` 中，確認「藍牙」與「位置」皆已開啟。

---

## 💻 3. PC 接收端 (Python Client)

Python 接收與示波器程式位於 `pc_client/` 目錄。

### 環境需求
* 安裝 [Python 3.8 或以上版本](https://www.python.org/)。

### 安裝步驟
1. 開啟終端機，進入 `pc_client` 目錄：
   ```bash
   cd pc_client
   ```
2. 安裝必要的 Python 第三方套件（包含 `bleak`, `pyserial`, `numpy`, `matplotlib`）：
   ```bash
   pip install -r requirements.txt
   ```

### 執行步驟
1. 將 `receiver.py` 頂部的連線模式設定為您所需的模式：
   - **USB 序列埠模式**：將 `SERIAL_PORT` 改為您 ESP32 的 COM Port（例如 `'COM3'` 或 `'/dev/ttyUSB0'`）。
   - **藍牙 BLE 模式**：將 `SERIAL_PORT` 改為 `'BLE'`，程式將會自動透過藍牙搜尋名稱為 `ESP32_ECG_BLE` 的裝置。
2. 執行接收端程式：
   ```bash
   python receiver.py
   ```
3. 系統將會啟動動態繪圖儀表板，您可以即時觀察 ECG 訊號並進行 HRV 分析。

---

## 🔗 4. 藍牙 BLE 連線機制說明

* **裝置廣播名稱**：`ESP32_ECG_BLE`
* **連線流程**：
  1. 確保 ESP32 已接上行動電源供電。
  2. 開啟手機 App，系統會自動在背景搜尋名為 `ESP32_ECG_BLE` 的裝置。
  3. 連線成功後，App 上的「藍牙未連線」提示將變更為「藍牙已連線」，此時即可預覽即時心電訊號並啟動量測。
