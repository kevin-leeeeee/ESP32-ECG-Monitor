# ⚙️ 系統安裝與執行指南

本專案包含三個核心子系統，請依序完成 **ESP32 韌體端**、**手機 App 端** 或 **PC 接收端** 的環境配置與安裝。

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

手機 App 原始碼位於 `mobile_app/` 目錄下，基於 **Expo** 框架開發。

### 環境需求
* 安裝 [Node.js](https://nodejs.org/) (建議 LTS 版本)。
* 手機端下載安裝 **Expo Go** App：
  * **Android**：請在 Google Play 商店搜尋 「Expo Go」 下載。
  * **iOS**：請在 App Store 搜尋 「Expo Go」 下載。

### 安裝步驟
1. 開啟終端機（PowerShell 或 CMD），進入 `mobile_app` 目錄：
   ```bash
   cd mobile_app
   ```
2. 安裝所有 Node.js 依賴套件：
   ```bash
   npm install
   ```

### 執行步驟
1. 在 `mobile_app` 目錄下啟動 Expo 開發伺服器：
   ```bash
   npx expo start
   ```
2. 控制台會生成一個大 **QR Code**。
3. **手機運行方式**：
   * **Android**：開啟手機上的 **Expo Go** App，點擊 "Scan QR code" 並掃描電腦螢幕上的 QR Code。
   * **iOS**：直接開啟手機內建的 **相機 App** 掃描 QR Code，然後點擊彈出的「在 Expo Go 中開啟」連結。
4. 開發伺服器會將 App 編譯並推送到您的手機上運作。

### 🚨 藍牙設定與權限重要說明
為了能讓 App 透過藍牙成功搜尋並連線 ESP32 裝置，**請務必在手機端完成以下設定**：
1. **啟用藍牙**：確保手機藍牙已開啟。
2. **啟用定位服務 (Location / GPS)**：Android 系統要求藍牙掃描必須啟用定位權限與定位服務。
3. **允許 App 權限**：
   * 當 Expo Go 提示存取「藍牙」或「位置資訊」權限時，**請務必選擇「允許」或「在使用應用程式期間允許」**。
   * 若連線失敗，請至手機的 `設定 ➡️ 應用程式 ➡️ Expo Go ➡️ 權限` 中，確認「藍牙/周邊裝置」與「位置」權限皆已手動啟用。

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
