#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// ===== BLE UUIDs =====
#define SERVICE_UUID           "19B10000-E8F2-537E-4F6C-D104768A1214"
#define CHARACTERISTIC_UUID    "19B10001-E8F2-537E-4F6C-D104768A1214"

BLEServer* pServer = NULL;
BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// ===== AD8232 腳位設定 =====
const int pinLOPlus = 35;  // Leads-off detect +
const int pinLOMinus = 34; // Leads-off detect -
const int pinECG = 36;     // 類比訊號輸出 (VP)

// 取樣率設定
const int SAMPLE_RATE = 250; // 250Hz 取樣率
const unsigned long SAMPLE_INTERVAL_US = 1000000 / SAMPLE_RATE; // 每次取樣間隔(微秒)
unsigned long lastSampleTime = 0;

// BLE 打包設定 (每包 10 筆數據，共 20 bytes)
const int BATCH_SIZE = 10;
uint16_t ecgBuffer[BATCH_SIZE];
int bufferIndex = 0;

class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("手機已連線 (BLE)");
    };

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("手機已斷線 (BLE)");
    }
};

void setup() {
  Serial.begin(115200);
  
  pinMode(pinLOPlus, INPUT);
  pinMode(pinLOMinus, INPUT);
  // ESP32 ADC 解析度預設為 12-bit (0-4095)
  analogReadResolution(12);

  // 初始化 BLE
  BLEDevice::init("ESP32_ECG_BLE");
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  // 建立 Characteristic，支援 Read 與 Notify
  pCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID,
                      BLECharacteristic::PROPERTY_READ   |
                      BLECharacteristic::PROPERTY_NOTIFY
                    );

  // 加入 BLE2902 描述符，這樣手機端才能訂閱 (Subscribe)
  pCharacteristic->addDescriptor(new BLE2902());

  pService->start();

  // 開始廣播，讓手機能搜尋到
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(false);
  pAdvertising->setMinPreferred(0x0);
  BLEDevice::startAdvertising();
  
  Serial.println("\n==================================================");
  Serial.println("🩺 --- ESP32 ECG/AD8232 [BLE 低功耗藍牙] 系統啟動 ---");
  Serial.println("👉 藍牙裝置名稱: ESP32_ECG_BLE");
  Serial.println("👉 取樣率: 250 Hz (每包 10 筆數據)");
  Serial.println("==================================================");
  Serial.println("等待手機連線...");
}

void loop() {
  unsigned long currentTime = micros();

  // --- 1. 永遠進行 250Hz 取樣 ---
  if (currentTime - lastSampleTime >= SAMPLE_INTERVAL_US) {
    lastSampleTime = currentTime;
    
    int ecgValue = analogRead(pinECG);
    
    // 讀取導聯脫落狀態 (Leads-Off Detection)
    bool leadsOff = (digitalRead(pinLOPlus) == HIGH || digitalRead(pinLOMinus) == HIGH);
    
    if (leadsOff) {
      // 輸出特殊字串供 PC 端辨識，此時數值強制歸 0
      Serial.println("!LEADS_OFF!");
      ecgValue = 0;
    } else {
      // 正常輸出 ECG 數值
      Serial.println(ecgValue);
    }
    
    // 如果手機有連線 (BLE)，則打包推播給手機
    if (deviceConnected) {
      ecgBuffer[bufferIndex] = (uint16_t)ecgValue;
      bufferIndex++;

      // 當收集滿 10 個取樣點，整包發送
      if (bufferIndex >= BATCH_SIZE) {
        pCharacteristic->setValue((uint8_t*)ecgBuffer, BATCH_SIZE * sizeof(uint16_t));
        pCharacteristic->notify();
        bufferIndex = 0;
      }
    } else {
      bufferIndex = 0; // 沒連線時清空，防殘留舊數據
    }
  }
  
  // --- 2. 斷線處理 (重啟廣播) ---
  if (!deviceConnected && oldDeviceConnected) {
      delay(500); // 給藍牙堆疊一些時間準備
      BLEDevice::getAdvertising()->start(); // 重新廣播
      Serial.println("重新開始廣播 BLE...");
      oldDeviceConnected = deviceConnected;
  }

  // 連線狀態更新
  if (deviceConnected && !oldDeviceConnected) {
      oldDeviceConnected = deviceConnected;
  }
}
