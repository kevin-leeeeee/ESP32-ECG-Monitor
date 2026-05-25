import React, { useState, useEffect, useRef } from 'react';
import { StyleSheet, Text, View, TouchableOpacity, ScrollView, Platform, PermissionsAndroid, ActivityIndicator, Modal, FlatList, Alert, TextInput } from 'react-native';
import { BleManager } from 'react-native-ble-plx';
import * as FileSystem from 'expo-file-system/legacy';
import { Buffer } from 'buffer'; // Base64 解碼
import Svg, { Polyline, Line, Rect } from 'react-native-svg';
import { EcgAnalyzer } from './src/utils/ecgAnalyzer';

// 安全初始化 BleManager (防止在 Expo Go 中因缺少原生模組而崩潰)
let manager = null;
try {
  manager = new BleManager();
} catch (e) {
  console.log("BLE Manager 初始化失敗，此為 Expo Go 預期現象:", e.message);
}

const SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214";
const CHARACTERISTIC_UUID = "19b10001-e8f2-537e-4f6c-d104768a1214";
const MEASURE_SECONDS = 120;

export default function App() {
  const [device, setDevice] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState(manager ? '未連線' : '預覽模式 (無藍牙)');
  const [appState, setAppState] = useState('READY'); // READY, MEASURING, FINISHED
  const [historyList, setHistoryList] = useState([]);
  const [showHistory, setShowHistory] = useState(false);
  const [leadsOffActive, setLeadsOffActive] = useState(false);

  const [measureDuration, setMeasureDuration] = useState('120'); // 預設自訂 120 秒
  const [activeDuration, setActiveDuration] = useState(120);
  const [timeLeft, setTimeLeft] = useState(120);
  const [ecgPath, setEcgPath] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [activeRecordId, setActiveRecordId] = useState(null);
  const [historyRawData, setHistoryRawData] = useState([]);

  // 當 activeRecordId 改變時，異步讀取對應的波形文字檔案並解析回數字陣列
  useEffect(() => {
    if (!activeRecordId) {
      setHistoryRawData([]);
      return;
    }

    const loadRawData = async () => {
      try {
        const rawFileName = `${FileSystem.documentDirectory}ecg_raw_${activeRecordId}.txt`;
        const fileInfo = await FileSystem.getInfoAsync(rawFileName);
        if (fileInfo.exists) {
          const dataStr = await FileSystem.readAsStringAsync(rawFileName);
          if (dataStr) {
            const parsed = dataStr.split(',').map(Number);
            setHistoryRawData(parsed);
          } else {
            setHistoryRawData([]);
          }
        } else {
          setHistoryRawData([]);
        }
      } catch (e) {
        console.log("讀取歷史原始波形失敗", e);
        setHistoryRawData([]);
      }
    };

    loadRawData();
  }, [activeRecordId]);

  // 用於量測與顯示的緩衝區
  const dataBuffer = useRef([]);
  const displayBuffer = useRef([]);
  const analyzer = useRef(new EcgAnalyzer(250));

  const appStateRef = useRef('READY');
  const consecutiveNormalPoints = useRef(0);
  useEffect(() => {
    appStateRef.current = appState;
  }, [appState]);

  const HISTORY_FILE = FileSystem.documentDirectory + 'ecg_history.json';

  const loadHistory = async () => {
    try {
      const fileInfo = await FileSystem.getInfoAsync(HISTORY_FILE);
      if (fileInfo.exists) {
        const stored = await FileSystem.readAsStringAsync(HISTORY_FILE);
        setHistoryList(JSON.parse(stored));
      }
    } catch (e) {
      console.log("載入歷史紀錄失敗", e);
    }
  };

  const saveToHistory = async (recordId, newResult, rawData) => {
    try {
      const timestamp = new Date().toLocaleString('zh-TW', { hour12: false });
      
      // 1. 異步將原始波形陣列轉換為逗號分隔的緊湊 CSV 字串，寫入獨立檔案
      if (rawData && rawData.length > 0) {
        const rawFileName = `${FileSystem.documentDirectory}ecg_raw_${recordId}.txt`;
        await FileSystem.writeAsStringAsync(rawFileName, rawData.join(','));
      }

      // 2. 將統計結果寫入歷史總表
      const record = {
        id: recordId,
        time: timestamp,
        result: newResult
      };
      
      const updatedList = [record, ...historyList];
      setHistoryList(updatedList);
      await FileSystem.writeAsStringAsync(HISTORY_FILE, JSON.stringify(updatedList));
      console.log("歷史紀錄與檔案已成功寫入:", HISTORY_FILE);
    } catch (e) {
      console.log("儲存歷史紀錄失敗", e);
    }
  };

  const handleClearHistory = () => {
    Alert.alert(
      "清除確認",
      "確定要刪除所有的歷史量測紀錄與心電波形嗎？此動作無法復原。",
      [
        { text: "取消", style: "cancel" },
        { 
          text: "確定清除", 
          style: "destructive",
          onPress: async () => {
            try {
              // 1. 刪除總清單檔案
              await FileSystem.deleteAsync(HISTORY_FILE, { idempotent: true });
              
              // 2. 尋找並刪除所有波形文字檔
              const files = await FileSystem.readDirectoryAsync(FileSystem.documentDirectory);
              const rawFiles = files.filter(f => f.startsWith('ecg_raw_') && f.endsWith('.txt'));
              for (const file of rawFiles) {
                await FileSystem.deleteAsync(`${FileSystem.documentDirectory}${file}`, { idempotent: true });
              }

              setHistoryList([]);
              Alert.alert("已完成", "所有紀錄與波形資料已全部清除。");
            } catch (e) {
              console.log("清除歷史紀錄失敗", e);
            }
          }
        }
      ]
    );
  };

  useEffect(() => {
    loadHistory();
    if (manager) {
      requestPermissions();
    }
    return () => {
      if (manager) {
        manager.destroy();
      }
    };
  }, []);

  const requestPermissions = async () => {
    if (Platform.OS === 'android') {
      try {
        const granted = await PermissionsAndroid.requestMultiple([
          PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
          PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
          PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
        ]);
        scanAndConnect();
      } catch (err) {
        console.warn(err);
      }
    } else {
      scanAndConnect();
    }
  };

  const scanAndConnect = () => {
    if (!manager) return;
    setConnectionStatus('掃描 ESP32_ECG_BLE...');
    manager.startDeviceScan(null, null, (error, scannedDevice) => {
      if (error) {
        console.log("Scan error:", error);
        setConnectionStatus('掃描失敗/藍牙未開啟');
        return;
      }
      if (scannedDevice && scannedDevice.name === 'ESP32_ECG_BLE') {
        manager.stopDeviceScan();
        connectToDevice(scannedDevice);
      }
    });
  };

  const connectToDevice = async (device) => {
    try {
      setConnectionStatus('連線中...');
      const connectedDevice = await manager.connectToDevice(device.id);
      setDevice(connectedDevice);

      const discoveredDevice = await connectedDevice.discoverAllServicesAndCharacteristics();
      setConnectionStatus('已連線');

      discoveredDevice.monitorCharacteristicForService(
        SERVICE_UUID,
        CHARACTERISTIC_UUID,
        (error, characteristic) => {
          if (error) {
            console.log("Error monitoring:", error);
            return;
          }
          handleEcgData(characteristic.value);
        }
      );

      connectedDevice.onDisconnected((error, disconnectedDevice) => {
        setConnectionStatus('斷線，重新掃描...');
        setDevice(null);
        scanAndConnect();
      });

    } catch (e) {
      console.log('Connection error', e);
      setConnectionStatus('連線失敗');
      setTimeout(scanAndConnect, 2000);
    }
  };

  const handleEcgData = (base64Value) => {
    if (appStateRef.current === 'FINISHED') return;

    // 解碼 Base64 數據為位元組數組
    const buffer = Buffer.from(base64Value, 'base64');
    const samples = [];
    let hasZero = false;
    for (let i = 0; i < buffer.length; i += 2) {
      if (i + 1 < buffer.length) {
        const value = buffer[i] | (buffer[i + 1] << 8);
        samples.push(value);
        if (value === 0) {
          hasZero = true;
          consecutiveNormalPoints.current = 0;
        } else {
          consecutiveNormalPoints.current += 1;
        }
      }
    }

    // 判定貼片脫落狀態 (使用函數式更新，解決藍牙訂閱閉包中 leadsOffActive 狀態過期導致警報無法消除的 Bug)
    if (hasZero) {
      setLeadsOffActive(prev => {
        if (!prev) return true;
        return prev;
      });
    } else if (consecutiveNormalPoints.current >= 50) {
      setLeadsOffActive(prev => {
        if (prev) return false;
        return prev;
      });
    }

    // 只有在量測狀態下才把數據計入完整的 dataBuffer 中 (存檔與分析)
    if (appStateRef.current === 'MEASURING') {
      dataBuffer.current.push(...samples);
    }

    // 不論是 READY 還是 MEASURING 都推入即時滾動顯示 displayBuffer
    displayBuffer.current.push(...samples);

    // 限制滾動顯示的數據長度 (只保留最新的 800 個點)
    if (displayBuffer.current.length > 800) {
      displayBuffer.current = displayBuffer.current.slice(-800);
    }

    updateEcgPath();
  };

  const updateEcgPath = () => {
    const width = 350;
    const height = 200;
    const maxVal = 4095;

    const points = displayBuffer.current.map((val, index) => {
      const x = (index / 800) * width;
      // 反轉 Y 軸以便正確顯示 (4095 映射到頂部，0 映射到底部)
      const y = height - (val / maxVal) * height;
      return `${x},${y}`;
    }).join(' ');

    setEcgPath(points);
  };

  const startMeasurement = () => {
    const duration = parseInt(measureDuration, 10) || 120;
    setActiveDuration(duration);

    // 模擬預覽模式下的數據生成
    if (!manager || !device) {
      runDemoSimulation(duration);
      return;
    }

    dataBuffer.current = [];
    displayBuffer.current = [];
    setTimeLeft(duration);
    setAppState('MEASURING');
    setAnalysisResult(null);

    let time = duration;
    const interval = setInterval(() => {
      time -= 1;
      setTimeLeft(time);
      if (time <= 0) {
        clearInterval(interval);
        finishMeasurement();
      }
    }, 1000);
  };

  // 模擬模式 (實作含隨機心跳變異 HRV 的逼真模擬)
  const runDemoSimulation = (duration) => {
    dataBuffer.current = [];
    displayBuffer.current = [];
    setTimeLeft(duration);
    setAppState('MEASURING');
    setAnalysisResult(null);

    let time = duration;
    const intervalId = setInterval(() => {
      time -= 1;
      setTimeLeft(time);
      if (time <= 0) {
        clearInterval(intervalId);
        clearInterval(dataTimerId);
        finishMeasurement();
      }
    }, 1000);

    let simIndex = 0;
    let nextBeatIndex = 40;
    let currentInterval = 200; // 預設 800ms (75 BPM)

    // 每 100ms 產生 25 個點，保證總數據量精確度與執行效率
    const dataTimerId = setInterval(() => {
      const pointsToGenerate = 25;
      
      for (let p = 0; p < pointsToGenerate; p++) {
        let val = 2000; // 基線
        const offset = simIndex - (nextBeatIndex - 40);

        if (offset >= 0 && offset < 50) {
          // 合成 QRS-T 波形
          if (offset === 0) val = 1800; // Q
          else if (offset === 5) val = 3800; // R
          else if (offset === 10) val = 1400; // S
          else if (offset === 25) val = 2300; // T
          else val = 2000;
        } else {
          // 微小背景雜訊
          val += Math.sin(simIndex * 0.1) * 30 + (Math.random() - 0.5) * 20;
        }

        dataBuffer.current.push(val);
        displayBuffer.current.push(val);
        
        simIndex++;

        // 當到達下一個心跳特徵點時，隨機產生 R-R 間期變異 (180 ~ 230 個點，約 72 ~ 83 BPM)
        if (simIndex >= nextBeatIndex) {
          currentInterval = 180 + Math.floor(Math.random() * 50);
          nextBeatIndex = simIndex + currentInterval;
        }
      }
      
      // 限制滾動顯示的數據長度 (只保留最新的 800 個點)
      if (displayBuffer.current.length > 800) {
        displayBuffer.current = displayBuffer.current.slice(-800);
      }
      updateEcgPath();
    }, 100);
  };

  const finishMeasurement = () => {
    setAppState('FINISHED');
    const result = analyzer.current.analyze(dataBuffer.current);
    // 如果是模擬展示，稍作狀態註記
    if (!manager || !device) {
      result.status = "分析成功 (模擬展示)";
    }
    setAnalysisResult(result);

    // 只有在分析成功時，才生成 ID 並儲存歷史紀錄，避免寫入無效數據導致 UI 崩潰
    if (result.status === "分析成功" || result.status.includes("模擬展示")) {
      const recordId = Date.now().toString();
      setHistoryRawData([...dataBuffer.current]);
      setActiveRecordId(recordId);
      saveToHistory(recordId, result, dataBuffer.current);
    } else {
      // 失敗時清除狀態
      setHistoryRawData([]);
      setActiveRecordId(null);
      Alert.alert(
        "💡 量測未達分析標準", 
        `本次量測數據「${result.status}」。\n\n原因通常為：\n1. 量測時間過短 (建議大於 10 秒)\n2. 貼片接觸不良造成雜訊太大。\n\n本次結果將不會被寫入歷史紀錄。`
      );
    }
  };

  // 生成網格背景 (模擬 ECG 方格紙)
  const renderGridLines = () => {
    const lines = [];
    const width = 350;
    const height = 200;

    // 垂直方格線 (每 20 像素一條)
    for (let x = 0; x <= width; x += 20) {
      lines.push(
        <Line
          key={`v-${x}`}
          x1={x} y1={0} x2={x} y2={height}
          stroke={x % 100 === 0 ? "rgba(239, 68, 68, 0.25)" : "rgba(239, 68, 68, 0.1)"}
          strokeWidth="1"
        />
      );
    }

    // 水平方格線
    for (let y = 0; y <= height; y += 20) {
      lines.push(
        <Line
          key={`h-${y}`}
          x1={0} y1={y} x2={width} y2={y}
          stroke={y % 100 === 0 ? "rgba(239, 68, 68, 0.25)" : "rgba(239, 68, 68, 0.1)"}
          strokeWidth="1"
        />
      );
    }
    return lines;
  };

  return (
    <>
      <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.title}>自律神經心電檢測 (BLE)</Text>

      {/* 連線狀態標籤 */}
      <View style={[
        styles.statusBadge,
        connectionStatus === '已連線' ? styles.statusConnected : styles.statusDisconnected
      ]}>
        <Text style={styles.statusText}>狀態: {connectionStatus}</Text>
      </View>

      {/* Expo Go 專用警語 */}
      {!manager && (
        <View style={styles.expoGoWarning}>
          <Text style={styles.warningText}>⚠️ 偵測到 Expo Go 預覽環境 (無法呼叫實體藍牙)。系統已開啟「模擬量測模式」供您預覽介面。</Text>
        </View>
      )}

      {/* 貼片脫落獨立警告條 */}
      {leadsOffActive && (
        <View style={styles.leadsOffBanner}>
          <Text style={styles.leadsOffBannerText}>⚠️ 偵測到貼片脫落！請檢查紅(RA)、黃(LA)、綠(LL)貼片與導線是否貼緊身體</Text>
        </View>
      )}

      {/* 心電圖示波器 (含紅色網格) */}
      <View style={[styles.graphContainer, leadsOffActive && styles.graphContainerLeadsOff]}>
        <Svg height="200" width="350">
          {/* 背景網格 */}
          {renderGridLines()}
          {/* 心電波形 */}
          {ecgPath ? (
            <Polyline points={ecgPath} fill="none" stroke="#EF4444" strokeWidth="2.5" />
          ) : (
            <Text style={styles.noDataText}>等待數據流中...</Text>
          )}
        </Svg>
      </View>

      {appState === 'READY' && (
        <View style={{ width: '100%', alignItems: 'center' }}>
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>⏳ 量測時間 (秒)：</Text>
            <TextInput
              style={styles.textInput}
              keyboardType="numeric"
              value={measureDuration}
              onChangeText={(text) => {
                // 過濾非數字
                const filtered = text.replace(/[^0-9]/g, '');
                setMeasureDuration(filtered);
              }}
              maxLength={4}
              placeholder="120"
              placeholderTextColor="#64748B"
            />
          </View>

          <TouchableOpacity
            style={styles.button}
            onPress={startMeasurement}>
            <Text style={styles.buttonText}>
              {!manager ? "開始模擬量測" : "開始即時量測"}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.historyBtn}
            onPress={() => setShowHistory(true)}>
            <Text style={styles.historyBtnText}>📊 歷史量測紀錄 ({historyList.length})</Text>
          </TouchableOpacity>
        </View>
      )}

      {appState === 'MEASURING' && (
        <View style={styles.measuringBox}>
          <Text style={styles.countdown}>{timeLeft} <Text style={{ fontSize: 16 }}>秒</Text></Text>
          <Text style={styles.infoText}>正在採集 ECG 訊號，請保持安靜...</Text>
          <View style={styles.progressBarBg}>
            <View style={[styles.progressBar, { width: `${((activeDuration - timeLeft) / activeDuration) * 100}%` }]} />
          </View>
        </View>
      )}

      {appState === 'FINISHED' && analysisResult && (
        <View style={styles.resultBox}>
          {analysisResult.status !== "分析成功" && !analysisResult.status.includes("模擬展示") ? (
            // 失敗頁面
            <View style={{ alignItems: 'center', padding: 20, width: '100%' }}>
              <Text style={{ fontSize: 48, marginBottom: 15 }}>⚠️</Text>
              <Text style={[styles.resultTitle, { color: '#F59E0B', marginBottom: 10 }]}>量測未達分析標準</Text>
              <Text style={{ color: '#F8FAFC', fontSize: 16, fontWeight: 'bold', marginVertical: 10 }}>狀態：{analysisResult.status}</Text>
              <Text style={{ color: '#94A3B8', fontSize: 14, textAlign: 'center', lineHeight: 22, marginVertical: 10 }}>
                本次量測的時間過短 (檢測演算法至少需要 5-10 秒以上的穩定數據) 或貼片接觸不良造成雜訊太大，無法偵測到有效的心跳 R 波。
              </Text>
              <Text style={{ color: '#E2E8F0', fontSize: 13, backgroundColor: 'rgba(245, 158, 11, 0.1)', padding: 12, borderRadius: 8, marginTop: 15, borderWidth: 1, borderColor: 'rgba(245, 158, 11, 0.2)', width: '100%', textAlign: 'center' }}>
                💡 建議：請清潔皮膚，確保紅(RA)、黃(LA)、綠(LL)電極貼片緊密貼合，並輸入 30 秒以上的量測時間再次嘗試。
              </Text>
              <TouchableOpacity style={[styles.button, { marginTop: 30, width: '100%' }]} onPress={() => setAppState('READY')}>
                <Text style={styles.buttonText}>重新量測</Text>
              </TouchableOpacity>
            </View>
          ) : (
            // 成功分析頁面
            <>
              <Text style={styles.resultTitle}>📋 {analysisResult.status}</Text>

              {/* 生理指標卡片區 (兩列排版，對齊電腦版) */}
              <View style={styles.cardRow}>
                <View style={styles.metricCard3}>
                  <Text style={styles.cardLabel}>平均心率</Text>
                  <Text style={styles.cardVal}>{analysisResult.hr} <Text style={styles.cardUnit}>BPM</Text></Text>
                </View>
                <View style={styles.metricCard3}>
                  <Text style={styles.cardLabel}>平均呼吸率</Text>
                  <Text style={styles.cardVal}>{analysisResult.rsp} <Text style={styles.cardUnit}>次/分</Text></Text>
                </View>
                <View style={styles.metricCard3}>
                  <Text style={styles.cardLabel}>神經活力</Text>
                  <Text style={[styles.cardVal, { color: '#10B981' }]}>{analysisResult.vitality} <Text style={styles.cardUnit}>分</Text></Text>
                </View>
              </View>

              <View style={styles.cardRow}>
                <View style={styles.metricCard2}>
                  <Text style={styles.cardLabel}>SDNN (總體調節能力)</Text>
                  <Text style={styles.cardVal}>{analysisResult.sdnn} <Text style={styles.cardUnit}>ms</Text></Text>
                </View>
                <View style={styles.metricCard2}>
                  <Text style={styles.cardLabel}>RMSSD (副交感調節)</Text>
                  <Text style={styles.cardVal}>{analysisResult.rmssd} <Text style={styles.cardUnit}>ms</Text></Text>
                </View>
              </View>

              {/* 自律神經平衡儀表盤 (交感 vs 副交感能量條，含活性對比) */}
              <View style={styles.balanceContainer}>
                <Text style={styles.balanceTitle}>自律神經活性平衡 (SNS vs PNS)</Text>
                <View style={styles.balanceRow}>
                  <Text style={[styles.balancePercentText, { color: '#EF4444' }]}>交感活性: {analysisResult.sns_active}/100 ({analysisResult.sns}%)</Text>
                  <Text style={[styles.balancePercentText, { color: '#3B82F6' }]}>副交感活性: {analysisResult.pns_active}/100 ({analysisResult.pns}%)</Text>
                </View>

                {/* 雙向平衡能量條 */}
                <View style={styles.gaugeBarBg}>
                  <View style={[styles.snsBar, { width: `${analysisResult.sns}%` }]} />
                  <View style={[styles.pnsBar, { width: `${analysisResult.pns}%` }]} />
                </View>
                <Text style={styles.balanceStatus}>
                  {analysisResult.sns > 60 ? "🔥 交感神經偏高 (壓力稍大)" :
                    analysisResult.pns > 60 ? "💤 副交感神經活躍 (身心放鬆)" : "⚖️ 自律神經處於平衡狀態"}
                </Text>
              </View>

              {/* ACLS 心電傳導間期分析表 */}
              <View style={styles.sectionContainer}>
                <Text style={styles.sectionTitle}>⚡ ACLS 心電傳導間期分析</Text>

                <View style={styles.tableHeader}>
                  <Text style={[styles.tableCell, styles.cellHeader, { flex: 2 }]}>指標名稱</Text>
                  <Text style={[styles.tableCell, styles.cellHeader, { flex: 1.5 }]}>量測值</Text>
                  <Text style={[styles.tableCell, styles.cellHeader, { flex: 1.5 }]}>診斷狀態</Text>
                </View>

                <View style={styles.tableRow}>
                  <Text style={[styles.tableCell, { flex: 2, textAlign: 'left', paddingLeft: 8 }]}>PR 間期 (房室傳導)</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: '#38BDF8', fontWeight: 'bold' }]}>{analysisResult.pr_val}</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: analysisResult.pr_status === '正常' ? '#10B981' : '#F59E0B' }]}>{analysisResult.pr_status}</Text>
                </View>

                <View style={styles.tableRow}>
                  <Text style={[styles.tableCell, { flex: 2, textAlign: 'left', paddingLeft: 8 }]}>QRS 波寬 (心室去極化)</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: '#38BDF8', fontWeight: 'bold' }]}>{analysisResult.qrs_val}</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: analysisResult.qrs_status === '正常' ? '#10B981' : '#EF4444' }]}>{analysisResult.qrs_status}</Text>
                </View>

                <View style={styles.tableRow}>
                  <Text style={[styles.tableCell, { flex: 2, textAlign: 'left', paddingLeft: 8 }]}>QT 間期 (心室復極化)</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: '#38BDF8', fontWeight: 'bold' }]}>{analysisResult.qt_val}</Text>
                  <Text style={[styles.tableCell, { flex: 1.5, color: analysisResult.qt_status === '正常' ? '#10B981' : '#EF4444' }]}>{analysisResult.qt_status}</Text>
                </View>
              </View>

              {/* 身心綜合診斷與專家建議卡片 */}
              <View style={styles.diagContainer}>
                <Text style={styles.diagTitle}>🩺 身心健康狀態評估</Text>
                <View style={styles.diagCard}>
                  <Text style={styles.diagLabel}>綜合狀態：<Text style={styles.diagStateText}>{analysisResult.state}</Text></Text>
                  <Text style={styles.diagText}><Text style={{ fontWeight: 'bold', color: '#94A3B8' }}>成因分析：</Text>{analysisResult.cause}</Text>
                  <Text style={styles.diagText}><Text style={{ fontWeight: 'bold', color: '#94A3B8' }}>平衡狀態：</Text>{analysisResult.balance_desc}</Text>
                  <View style={styles.recommendBox}>
                    <Text style={styles.recommendTitle}>💡 專家調整建議：</Text>
                    <Text style={styles.recommendText}>{analysisResult.recommendation}</Text>
                  </View>
                </View>
              </View>

              {/* 歷史心電圖波形查看 (左右滑動，自適應縮放，高效抽樣) */}
              {historyRawData && historyRawData.length > 0 && (() => {
                const sampled = [];
                for (let i = 0; i < historyRawData.length; i += 2) {
                  sampled.push(historyRawData[i]);
                }

                const hHeight = 140;
                const hWidth = Math.max(350, sampled.length * 1.2);
                
                const minVal = Math.min(...sampled);
                const maxVal = Math.max(...sampled);
                const range = (maxVal - minVal) || 1;

                const hPoints = sampled.map((val, idx) => {
                  const x = idx * 1.2;
                  const y = hHeight - ((val - minVal) / range) * (hHeight - 30) - 15;
                  return `${x.toFixed(1)},${y.toFixed(1)}`;
                }).join(' ');

                const hGridLines = [];
                for (let x = 0; x <= hWidth; x += 30) {
                  hGridLines.push(
                    <Line key={`h-v-${x}`} x1={x} y1={0} x2={x} y2={hHeight} stroke="rgba(239, 68, 68, 0.12)" strokeWidth="0.8" />
                  );
                }
                for (let y = 0; y <= hHeight; y += 30) {
                  hGridLines.push(
                    <Line key={`h-h-${y}`} x1={0} y1={y} x2={hWidth} y2={y} stroke="rgba(239, 68, 68, 0.12)" strokeWidth="0.8" />
                  );
                }

                return (
                  <View style={styles.historyWaveContainer}>
                    <Text style={styles.historyWaveTitle}>📈 心電圖原始完整波形 (左右滑動檢視)</Text>
                    <ScrollView horizontal={true} style={styles.historyWaveScroll} showsHorizontalScrollIndicator={true}>
                      <View style={styles.historyWaveCanvasBg}>
                        <Svg height={hHeight} width={hWidth}>
                          {hGridLines}
                          <Polyline points={hPoints} fill="none" stroke="#EF4444" strokeWidth="1.8" />
                        </Svg>
                      </View>
                    </ScrollView>
                  </View>
                );
              })()}

              <TouchableOpacity style={[styles.button, { marginTop: 25 }]} onPress={() => setAppState('READY')}>
                <Text style={styles.buttonText}>重新量測</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      )}
    </ScrollView>

    <Modal
      visible={showHistory}
      animationType="slide"
      transparent={true}
      onRequestClose={() => setShowHistory(false)}
    >
      <View style={styles.modalBg}>
        <View style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>📊 歷史量測紀錄</Text>
            <TouchableOpacity onPress={() => setShowHistory(false)}>
              <Text style={styles.modalCloseBtn}>關閉</Text>
            </TouchableOpacity>
          </View>

          {historyList.length === 0 ? (
            <View style={styles.emptyHistoryBox}>
              <Text style={styles.emptyHistoryText}>目前尚無任何量測紀錄。</Text>
              <Text style={styles.emptyHistorySub}>開始您的第一次 120 秒 ECG 檢測吧！</Text>
            </View>
          ) : (
            <>
              <FlatList
                data={historyList}
                keyExtractor={(item) => item.id}
                contentContainerStyle={{ paddingBottom: 20 }}
                renderItem={({ item }) => (
                  <TouchableOpacity 
                    style={styles.historyCard}
                    onPress={() => {
                      // 點選歷史紀錄：加載報告、設定 activeRecordId，並切換到 FINISHED 狀態
                      setAnalysisResult(item.result);
                      setActiveRecordId(item.id);
                      setAppState('FINISHED');
                      setShowHistory(false);
                    }}
                  >
                    <View style={styles.historyCardHeader}>
                      <Text style={styles.historyTime}>{item.time}</Text>
                      <Text style={[
                        styles.historyBadge, 
                        (item.result.state || "").includes("平衡") ? styles.badgeGood : styles.badgeAlert
                      ]}>
                        {item.result.state || "分析失敗"}
                      </Text>
                    </View>
                    <View style={styles.historyMetrics}>
                      <Text style={styles.historyMetricText}>心率: <Text style={{color: '#FFF'}}>{item.result.hr || 0} BPM</Text></Text>
                      <Text style={styles.historyMetricText}>SDNN: <Text style={{color: '#FFF'}}>{item.result.sdnn || 0} ms</Text></Text>
                      <Text style={styles.historyMetricText}>RMSSD: <Text style={{color: '#FFF'}}>{item.result.rmssd || 0} ms</Text></Text>
                    </View>
                    <Text style={styles.historyTip} numberOfLines={1}>
                      💡 {item.result.recommendation || "無建議"}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              
              <TouchableOpacity 
                style={styles.clearAllBtn}
                onPress={handleClearHistory}
              >
                <Text style={styles.clearAllBtnText}>🗑️ 清除所有紀錄</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      </View>
    </Modal>
  </>
);
}

const styles = StyleSheet.create({
  historyWaveContainer: {
    width: '100%',
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 12,
    marginTop: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  historyWaveTitle: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 8,
    textAlign: 'center',
  },
  historyWaveScroll: {
    width: '100%',
    borderRadius: 8,
    backgroundColor: '#1E1B1B',
  },
  historyWaveCanvasBg: {
    backgroundColor: '#1E1B1B',
    paddingVertical: 5,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.25)',
  },
  container: {
    flexGrow: 1,
    backgroundColor: '#0F172A', // Slate-900 深色背景
    alignItems: 'center',
    paddingTop: 60,
    paddingBottom: 40,
  },
  title: {
    fontSize: 24,
    color: '#F8FAFC',
    fontWeight: 'bold',
    marginBottom: 8,
  },
  statusBadge: {
    paddingHorizontal: 16,
    paddingVertical: 6,
    borderRadius: 20,
    marginBottom: 20,
  },
  statusConnected: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
    borderWidth: 1,
    borderColor: '#10B981',
  },
  statusDisconnected: {
    backgroundColor: 'rgba(148, 163, 184, 0.2)',
    borderWidth: 1,
    borderColor: '#94A3B8',
  },
  statusText: {
    color: '#F8FAFC',
    fontSize: 14,
    fontWeight: '500',
  },
  expoGoWarning: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderWidth: 1,
    borderColor: '#F59E0B',
    padding: 12,
    borderRadius: 12,
    width: '90%',
    marginBottom: 20,
  },
  warningText: {
    color: '#FBBF24',
    fontSize: 12,
    textAlign: 'center',
    lineHeight: 18,
  },
  graphContainer: {
    width: 350,
    height: 200,
    backgroundColor: '#1E293B', // Slate-800
    borderRadius: 16,
    overflow: 'hidden',
    marginBottom: 25,
    borderWidth: 1,
    borderColor: '#334155',
    justifyContent: 'center',
    alignItems: 'center',
  },
  noDataText: {
    color: '#64748B',
    fontSize: 16,
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#3B82F6', // Blue-500
    paddingHorizontal: 45,
    paddingVertical: 14,
    borderRadius: 30,
    shadowColor: '#3B82F6',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 5,
  },
  buttonText: {
    color: '#F8FAFC',
    fontSize: 18,
    fontWeight: 'bold',
  },
  measuringBox: {
    alignItems: 'center',
    width: '90%',
  },
  countdown: {
    fontSize: 48,
    color: '#38BDF8',
    fontWeight: 'bold',
    marginBottom: 10,
  },
  infoText: {
    color: '#94A3B8',
    fontSize: 15,
    marginBottom: 15,
  },
  progressBarBg: {
    height: 8,
    backgroundColor: '#334155',
    borderRadius: 4,
    width: '80%',
    overflow: 'hidden',
  },
  progressBar: {
    height: '100%',
    backgroundColor: '#38BDF8',
  },
  resultBox: {
    backgroundColor: '#1E293B',
    padding: 16,
    borderRadius: 20,
    width: '92%',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#334155',
  },
  resultTitle: {
    fontSize: 18,
    color: '#10B981',
    fontWeight: 'bold',
    marginBottom: 20,
  },
  cardRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '100%',
    marginBottom: 12,
  },
  metricCard3: {
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
    paddingVertical: 12,
    paddingHorizontal: 4,
    borderRadius: 12,
    width: '31%',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  metricCard2: {
    backgroundColor: 'rgba(15, 23, 42, 0.6)',
    paddingVertical: 12,
    paddingHorizontal: 8,
    borderRadius: 12,
    width: '48%',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.05)',
  },
  cardLabel: {
    color: '#94A3B8',
    fontSize: 11,
    marginBottom: 6,
  },
  cardVal: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: 'bold',
  },
  cardUnit: {
    fontSize: 10,
    fontWeight: 'normal',
    color: '#64748B',
  },
  balanceContainer: {
    width: '100%',
    alignItems: 'center',
    marginTop: 15,
    backgroundColor: 'rgba(15, 23, 42, 0.4)',
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.03)',
  },
  balanceTitle: {
    color: '#F8FAFC',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 10,
  },
  balanceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    width: '100%',
    marginBottom: 6,
  },
  balancePercentText: {
    fontSize: 11,
    fontWeight: 'bold',
  },
  gaugeBarBg: {
    height: 12,
    backgroundColor: '#334155',
    borderRadius: 6,
    width: '100%',
    flexDirection: 'row',
    overflow: 'hidden',
    marginBottom: 8,
  },
  snsBar: {
    height: '100%',
    backgroundColor: '#EF4444',
  },
  pnsBar: {
    height: '100%',
    backgroundColor: '#3B82F6',
  },
  balanceStatus: {
    color: '#E2E8F0',
    fontSize: 13,
    fontWeight: '500',
  },
  sectionContainer: {
    width: '100%',
    marginTop: 20,
    backgroundColor: 'rgba(15, 23, 42, 0.4)',
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.03)',
  },
  sectionTitle: {
    fontSize: 14,
    color: '#F8FAFC',
    fontWeight: 'bold',
    marginBottom: 10,
    alignSelf: 'flex-start',
  },
  tableHeader: {
    flexDirection: 'row',
    backgroundColor: 'rgba(15, 23, 42, 0.7)',
    paddingVertical: 8,
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  tableRow: {
    flexDirection: 'row',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderColor: '#334155',
    backgroundColor: 'rgba(30, 41, 59, 0.4)',
    alignItems: 'center',
  },
  tableCell: {
    color: '#E2E8F0',
    fontSize: 12,
    textAlign: 'center',
  },
  cellHeader: {
    color: '#94A3B8',
    fontWeight: 'bold',
  },
  diagContainer: {
    width: '100%',
    marginTop: 20,
    backgroundColor: 'rgba(15, 23, 42, 0.4)',
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.03)',
  },
  diagTitle: {
    fontSize: 14,
    color: '#F8FAFC',
    fontWeight: 'bold',
    marginBottom: 10,
    alignSelf: 'flex-start',
  },
  diagCard: {
    width: '100%',
  },
  diagLabel: {
    color: '#94A3B8',
    fontSize: 13,
    marginBottom: 8,
  },
  diagStateText: {
    color: '#EF4444',
    fontWeight: 'bold',
    fontSize: 14,
  },
  diagText: {
    color: '#E2E8F0',
    fontSize: 12,
    lineHeight: 18,
    marginBottom: 6,
  },
  recommendBox: {
    marginTop: 10,
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(16, 185, 129, 0.3)',
    borderRadius: 8,
    padding: 10,
  },
  recommendTitle: {
    color: '#10B981',
    fontWeight: 'bold',
    fontSize: 13,
    marginBottom: 4,
  },
  recommendText: {
    color: '#A7F3D0',
    fontSize: 12,
    lineHeight: 18,
  },
  graphContainerLeadsOff: {
    borderColor: '#EF4444',
    backgroundColor: '#1E1B1B',
  },
  leadsOffBanner: {
    width: '90%',
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderColor: '#EF4444',
    borderWidth: 1.5,
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  leadsOffBannerText: {
    color: '#FCA5A5',
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
    lineHeight: 18,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#334155',
    paddingHorizontal: 16,
    paddingVertical: 8,
    width: '85%',
    marginBottom: 16,
    justifyContent: 'space-between',
  },
  inputLabel: {
    color: '#94A3B8',
    fontSize: 15,
    fontWeight: '600',
  },
  textInput: {
    color: '#F8FAFC',
    fontSize: 16,
    fontWeight: 'bold',
    backgroundColor: '#0F172A',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#475569',
    width: 80,
    paddingVertical: 6,
    paddingHorizontal: 10,
    textAlign: 'center',
  },
  buttonDisabled: {
    backgroundColor: '#475569',
    shadowColor: '#475569',
  },
  historyBtn: {
    marginTop: 15,
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 20,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  historyBtnText: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '600',
  },
  modalBg: {
    flex: 1,
    backgroundColor: 'rgba(15, 23, 42, 0.75)',
    justifyContent: 'flex-end',
  },
  modalContainer: {
    height: '80%',
    backgroundColor: '#1E293B',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    padding: 20,
    borderWidth: 1,
    borderColor: '#334155',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
    paddingBottom: 15,
    borderBottomWidth: 1,
    borderColor: '#334155',
  },
  modalTitle: {
    fontSize: 18,
    color: '#F8FAFC',
    fontWeight: 'bold',
  },
  modalCloseBtn: {
    fontSize: 16,
    color: '#3B82F6',
    fontWeight: 'bold',
  },
  emptyHistoryBox: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyHistoryText: {
    color: '#94A3B8',
    fontSize: 16,
    marginBottom: 8,
  },
  emptyHistorySub: {
    color: '#64748B',
    fontSize: 12,
  },
  historyCard: {
    backgroundColor: '#0F172A',
    borderRadius: 14,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#334155',
  },
  historyCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  historyTime: {
    color: '#94A3B8',
    fontSize: 13,
  },
  historyBadge: {
    fontSize: 11,
    fontWeight: 'bold',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    overflow: 'hidden',
  },
  badgeGood: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    color: '#10B981',
  },
  badgeAlert: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    color: '#EF4444',
  },
  historyMetrics: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  historyMetricText: {
    color: '#64748B',
    fontSize: 12,
  },
  historyTip: {
    color: '#94A3B8',
    fontSize: 11,
    fontStyle: 'italic',
  },
  clearAllBtn: {
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(239, 68, 68, 0.3)',
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 10,
    marginBottom: 10,
  },
  clearAllBtnText: {
    color: '#FCA5A5',
    fontSize: 14,
    fontWeight: 'bold',
  }
});
