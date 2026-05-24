/**
 * 簡易版心電圖 (ECG) 分析工具
 * 實作帶通濾波、R波偵測 (簡化版 Pan-Tompkins) 以及 HRV 運算，並整合與電腦版對齊的進階分析指標
 */

export class EcgAnalyzer {
  constructor(sampleRate = 250) {
    this.sampleRate = sampleRate;
  }

  // 計算平均值
  mean(data) {
    if (!data || data.length === 0) return 0;
    return data.reduce((a, b) => a + b, 0) / data.length;
  }

  // 移動平均 (低通濾波的一種簡單替代)
  movingAverage(data, windowSize) {
    const result = new Array(data.length).fill(0);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      sum += data[i];
      if (i >= windowSize) {
        sum -= data[i - windowSize];
      }
      result[i] = sum / Math.min(i + 1, windowSize);
    }
    return result;
  }

  // 去除基線偏移 (高通濾波的簡單替代：原訊號減去移動平均)
  removeBaselineWander(data, windowSize) {
    const ma = this.movingAverage(data, windowSize);
    return data.map((val, i) => val - ma[i]);
  }

  // 實作 Pan-Tompkins 雙閾值自適應與回溯搜尋的 R 波偵測演算法
  detectRPeaks(data) {
    if (!data || data.length < this.sampleRate * 2) return [];

    // 1. 去除基線漂移 (0.5s 的滑動窗口，去除呼吸與身體晃動引起的低頻起伏)
    const baselineWindow = Math.floor(this.sampleRate * 0.5);
    let filtered = this.removeBaselineWander(data, baselineWindow);

    // 2. 噪聲評估 (SQI) 與自適應低通降噪
    // 計算訊號的快速變異度 (微分平方和) 來評估高頻肌電噪聲
    let rawDiffSqSum = 0;
    const testLength = Math.min(data.length, this.sampleRate * 5);
    for (let i = 1; i < testLength; i++) {
      rawDiffSqSum += Math.pow(filtered[i] - filtered[i-1], 2);
    }
    const noiseIndicator = rawDiffSqSum / testLength;
    
    // 如果高頻噪聲指標大於閾值 (表示貼片接觸不良或晃動嚴重)，自適應進行一次低通濾波
    if (noiseIndicator > 1500) {
      // 用 5 點 (約 20ms) 移動平均進行平滑，濾除高頻毛刺
      filtered = this.movingAverage(filtered, 5);
    }

    // 3. 一階微分 (強化 R 波的陡峭上升斜率)
    let derivative = new Array(filtered.length).fill(0);
    for (let i = 1; i < filtered.length - 1; i++) {
      derivative[i] = (filtered[i + 1] - filtered[i - 1]) / 2;
    }

    // 4. 平方 (放大 QRS 斜率特徵，去除負向波，並降噪低幅波)
    let squared = derivative.map(val => val * val);

    // 5. 移動視窗積分 (150ms 窗口，對齊典型 QRS 寬度)
    const mwiWindow = Math.floor(this.sampleRate * 0.15);
    let mwi = this.movingAverage(squared, mwiWindow);

    // 6. 初始化 Pan-Tompkins 自適應雙閾值
    // 找出前 2 秒的極大值作為訊號初始估計，平均值作為噪聲初始估計
    const initRange = Math.min(mwi.length, this.sampleRate * 2);
    let maxInit = 100;
    let sumInit = 0;
    for (let i = 0; i < initRange; i++) {
      if (mwi[i] > maxInit) maxInit = mwi[i];
      sumInit += mwi[i];
    }
    const meanInit = sumInit / initRange;

    let spkf = maxInit * 0.5; // 訊號水平估計
    let npkf = meanInit * 0.5; // 噪聲水平估計
    let thr1 = npkf + 0.25 * (spkf - npkf); // 主閾值
    let thr2 = 0.5 * thr1; // 回溯搜尋閾值

    const peaks = [];
    const minRRDelay = Math.floor(this.sampleRate * 0.25); // 最小心跳間距 (約 240 BPM)
    let lastRPeakMwiIndex = -minRRDelay;

    // 用於回溯搜尋 (Back-search) 的追蹤：記錄所有局部最大值峰值
    const allCandidatePeaks = []; // 格式: { index, value }

    // 第一階段：掃描所有局部極大值候選點並動態更新閾值
    for (let i = 1; i < mwi.length - 1; i++) {
      if (mwi[i] > mwi[i - 1] && mwi[i] > mwi[i + 1]) {
        allCandidatePeaks.push({ index: i, value: mwi[i] });

        // 檢查是否大於主閾值 thr1，且距離上一個 R 波大於最小間期
        if (mwi[i] > thr1) {
          if (i - lastRPeakMwiIndex > minRRDelay) {
            // 判定為真 R 波
            // 在原始 filtered 訊號附近 +-100ms 範圍搜尋精準的 R 波最大值位置
            const searchStart = Math.max(0, i - Math.floor(this.sampleRate * 0.1));
            const searchEnd = Math.min(filtered.length, i + Math.floor(this.sampleRate * 0.1));
            let trueRIndex = searchStart;
            let maxFVal = filtered[searchStart];
            for (let j = searchStart; j < searchEnd; j++) {
              if (filtered[j] > maxFVal) {
                maxFVal = filtered[j];
                trueRIndex = j;
              }
            }
            peaks.push(trueRIndex);
            lastRPeakMwiIndex = i;

            // 更新訊號水平 spkf (滑動平均)
            spkf = 0.125 * mwi[i] + 0.875 * spkf;
          } else {
            // 距離太近，視為噪聲峰值
            npkf = 0.125 * mwi[i] + 0.875 * npkf;
          }
        } else if (mwi[i] > thr2) {
          // 介於主副閾值之間，暫時視為噪聲
          npkf = 0.125 * mwi[i] + 0.875 * npkf;
        }

        // 動態更新閾值
        thr1 = npkf + 0.25 * (spkf - npkf);
        thr2 = 0.5 * thr1;
      }

      // 第二階段：回溯搜尋 (Back-search) 機制
      // 如果距離上一個 R 波已經超過 1.66 秒 (對應心率 < 36 BPM)，很可能是漏判了
      const timeSinceLastBeat = i - lastRPeakMwiIndex;
      if (timeSinceLastBeat > Math.floor(this.sampleRate * 1.66)) {
        // 在「上一個 R 波」到「當前位置」之間尋找候選峰值
        const searchRangeStart = lastRPeakMwiIndex + minRRDelay;
        const searchRangeEnd = i - Math.floor(this.sampleRate * 0.15); // 留出基本寬度

        let bestCandidate = null;
        let maxCandVal = -1;

        for (const cand of allCandidatePeaks) {
          if (cand.index >= searchRangeStart && cand.index <= searchRangeEnd) {
            // 如果該候選點大於副閾值 thr2 且大於當前最大候選
            if (cand.value > thr2 && cand.value > maxCandVal) {
              maxCandVal = cand.value;
              bestCandidate = cand;
            }
          }
        }

        if (bestCandidate) {
          // 補登漏判的 R 波
          const iCand = bestCandidate.index;
          const searchStart = Math.max(0, iCand - Math.floor(this.sampleRate * 0.1));
          const searchEnd = Math.min(filtered.length, iCand + Math.floor(this.sampleRate * 0.1));
          let trueRIndex = searchStart;
          let maxFVal = filtered[searchStart];
          for (let j = searchStart; j < searchEnd; j++) {
            if (filtered[j] > maxFVal) {
              maxFVal = filtered[j];
              trueRIndex = j;
            }
          }

          // 插入到正確的時間排序位置
          peaks.push(trueRIndex);
          peaks.sort((a, b) => a - b);
          lastRPeakMwiIndex = iCand;

          // 重新校正訊號估計
          spkf = 0.25 * bestCandidate.value + 0.75 * spkf;
          thr1 = npkf + 0.25 * (spkf - npkf);
          thr2 = 0.5 * thr1;
        }
      }
    }

    return peaks.sort((a, b) => a - b);
  }

  // 估算呼吸率 (EDR - ECG-derived respiration) 基於呼吸竇性心律不整 (RSA)
  estimateRespirationRate(rrIntervals) {
    if (rrIntervals.length < 5) return 15.0; // 預設值
    // 對 RR 間期進行平滑處理 (去除異常心跳影響)
    const smoothed = this.movingAverage(rrIntervals, 3);
    
    // 計算波峰數量 (局部極大值)
    let peaks = 0;
    for (let i = 1; i < smoothed.length - 1; i++) {
      if (smoothed[i] > smoothed[i-1] && smoothed[i] > smoothed[i+1]) {
        peaks++;
      }
    }
    
    // 計算這段 RR 間隔的總時間 (秒)
    const totalDurationSeconds = rrIntervals.reduce((a, b) => a + b, 0) / 1000;
    if (totalDurationSeconds <= 0) return 15.0;
    
    const breathsPerMin = (peaks / totalDurationSeconds) * 60;
    
    // 正常成年人靜息呼吸頻率在 8 到 30 次/分 之間，否則使用預設值 15
    if (breathsPerMin >= 8 && breathsPerMin <= 30) {
      return Math.round(breathsPerMin * 10) / 10;
    }
    return 15.0;
  }

  // 簡化版特徵點定位演算法，用於估算 PR/QRS/QT 間期
  detectIntervals(data, peaks) {
    let prSum = 0, qrsSum = 0, qtSum = 0;
    let validPrCount = 0, validQrsCount = 0, validQtCount = 0;

    // 排除頭尾 2 個 peak，避免邊界搜尋溢出
    for (let idx = 2; idx < peaks.length - 2; idx++) {
      const R = peaks[idx];

      // 1. 尋找 Q 點：R 點前 40ms (10個點) 內的第一個局部極小值
      let Q = R;
      let minQVal = data[R];
      const qStart = Math.max(0, R - 10);
      for (let j = R; j >= qStart; j--) {
        if (data[j] < minQVal) {
          minQVal = data[j];
          Q = j;
        }
      }

      // 2. 尋找 S 點：R 點後 40ms (10個點) 內的第一個局部極小值
      let S = R;
      let minSVal = data[R];
      const sEnd = Math.min(data.length - 1, R + 10);
      for (let j = R; j <= sEnd; j++) {
        if (data[j] < minSVal) {
          minSVal = data[j];
          S = j;
        }
      }

      // 3. 尋找 P 點：Q 點前 100ms 到 240ms (25 到 60 個點) 之間的局部最大值
      let P = -1;
      let maxPVal = -Infinity;
      const pStart = Math.max(0, Q - 55);
      const pEnd = Math.max(0, Q - 15);
      if (pEnd > pStart) {
        for (let j = pStart; j <= pEnd; j++) {
          if (data[j] > maxPVal) {
            maxPVal = data[j];
            P = j;
          }
        }
      }

      // P_onset 設在 P 點前約 32ms (8個點)，或搜尋 P 前面的平坦段
      let P_onset = -1;
      if (P !== -1) {
        P_onset = Math.max(0, P - 8);
        let minSlope = Infinity;
        let bestOnset = P - 8;
        for (let j = Math.max(0, P - 12); j < P; j++) {
          if (j + 1 < data.length) {
            const slope = Math.abs(data[j+1] - data[j]);
            if (slope < minSlope) {
              minSlope = slope;
              bestOnset = j;
            }
          }
        }
        P_onset = bestOnset;
      }

      // 4. 尋找 T 點：S 點後 100ms 到 360ms (25 到 90 個點) 之間的局部最大值
      let T = -1;
      let maxTVal = -Infinity;
      const tStart = Math.min(data.length - 1, S + 25);
      const tEnd = Math.min(data.length - 1, S + 90);
      if (tEnd > tStart) {
        for (let j = tStart; j <= tEnd; j++) {
          if (data[j] > maxTVal) {
            maxTVal = data[j];
            T = j;
          }
        }
      }

      // T_offset 設在 T 點後約 60ms (15個點) 或是 T 之後平坦處
      let T_offset = -1;
      if (T !== -1) {
        T_offset = Math.min(data.length - 1, T + 15);
        let minSlope = Infinity;
        let bestOffset = T + 15;
        for (let j = T; j < Math.min(data.length, T + 25); j++) {
          if (j + 1 < data.length) {
            const slope = Math.abs(data[j+1] - data[j]);
            if (slope < minSlope) {
              minSlope = slope;
              bestOffset = j;
            }
          }
        }
        T_offset = bestOffset;
      }

      // 驗證與累加間期
      if (P_onset !== -1 && Q > P_onset) {
        prSum += (Q - P_onset) / this.sampleRate;
        validPrCount++;
      }
      if (S > Q) {
        qrsSum += (S - Q) / this.sampleRate;
        validQrsCount++;
      }
      if (T_offset !== -1 && T_offset > Q) {
        qtSum += (T_offset - Q) / this.sampleRate;
        validQtCount++;
      }
    }

    const pr = validPrCount > 0 ? prSum / validPrCount : null;
    const qrs = validQrsCount > 0 ? qrsSum / validQrsCount : null;
    const qt = validQtCount > 0 ? qtSum / validQtCount : null;

    return { pr, qrs, qt };
  }

  // 計算 HRV 與生理指標
  analyze(ecgData) {
    if (!ecgData || ecgData.length < this.sampleRate * 5) {
      return { status: "數據不足", hr: 0, sdnn: 0, rmssd: 0 };
    }

    const peaks = this.detectRPeaks(ecgData);
    if (peaks.length < 2) {
      return { status: "無法偵測足夠心跳", hr: 0, sdnn: 0, rmssd: 0 };
    }

    // 計算 RR 間隔 (單位: 毫秒)
    const rrIntervals = [];
    for (let i = 1; i < peaks.length; i++) {
      const diff = peaks[i] - peaks[i - 1];
      rrIntervals.push((diff / this.sampleRate) * 1000);
    }

    // 排除不合理的 RR 間隔 (例如大於 2000ms 或小於 300ms 的極端雜訊)
    const validRR = rrIntervals.filter(rr => rr >= 300 && rr <= 2000);
    if (validRR.length === 0) {
      return { status: "無有效 RR 間隔", hr: 0, sdnn: 0, rmssd: 0 };
    }

    // 1. 平均心率 (BPM)
    const meanRR = this.mean(validRR);
    const hr = Math.round(60000 / meanRR);

    // 2. SDNN (標準差)
    let sumSquaredDiffs = 0;
    for (let i = 0; i < validRR.length; i++) {
      sumSquaredDiffs += Math.pow(validRR[i] - meanRR, 2);
    }
    const sdnn = Math.sqrt(sumSquaredDiffs / validRR.length);

    // 3. RMSSD (相鄰 RR 間隔差值平方和的均方根)
    let sumSqDiffs = 0;
    for (let i = 1; i < validRR.length; i++) {
      sumSqDiffs += Math.pow(validRR[i] - validRR[i - 1], 2);
    }
    const rmssd = validRR.length > 1 ? Math.sqrt(sumSqDiffs / (validRR.length - 1)) : 0;

    // 4. 自律神經與活力活性計算 (與電腦端 receiver.py 對齊)
    const vitalityScore = Math.min(100, Math.max(10, Math.round(100 * (1.0 - Math.exp(-sdnn / 40.0)))));
    
    const sd1 = rmssd / Math.sqrt(2.0);
    const sd2 = Math.sqrt(Math.max(1.0, 2.0 * Math.pow(sdnn, 2) - 0.5 * Math.pow(rmssd, 2)));
    
    const pnsActive = Math.min(100, Math.max(10, Math.round(100 * (1.0 - Math.exp(-sd1 / 20.0)))));
    const snsActive = Math.min(100, Math.max(10, Math.round(100 * (1.0 - Math.exp(-sd2 / 50.0)))));
    
    const totalActive = snsActive + pnsActive;
    const snsPercent = Math.round((snsActive / totalActive) * 100);
    const pnsPercent = 100 - snsPercent;

    // 5. 估算呼吸率 (EDR)
    const avgRsp = this.estimateRespirationRate(validRR);

    // 6. 心電傳導間期分析
    const intervals = this.detectIntervals(ecgData, peaks);
    
    // PR 診斷
    let prVal = "N/A", prStatus = "未知";
    if (intervals.pr !== null) {
      prVal = intervals.pr.toFixed(3) + "s";
      if (intervals.pr > 0.20) prStatus = "一度阻滯";
      else if (intervals.pr < 0.12) prStatus = "偏短";
      else prStatus = "正常";
    }

    // QRS 診斷
    let qrsVal = "N/A", qrsStatus = "未知";
    if (intervals.qrs !== null) {
      qrsVal = intervals.qrs.toFixed(3) + "s";
      if (intervals.qrs > 0.12) qrsStatus = "寬波 (阻滯)";
      else if (intervals.qrs > 0.10) qrsStatus = "不完全阻滯";
      else if (intervals.qrs < 0.06) qrsStatus = "偏窄";
      else qrsStatus = "正常";
    }

    // QT 診斷
    let qtVal = "N/A", qtStatus = "未知";
    if (intervals.qt !== null) {
      qtVal = intervals.qt.toFixed(3) + "s";
      if (intervals.qt > 0.44) qtStatus = "延長 (警訊)";
      else if (intervals.qt < 0.36) qtStatus = "偏短";
      else qtStatus = "正常";
    }

    // 7. 綜合診斷與專家建議 (與電腦端對齊)
    let stressLevel = "正常";
    let recommendation = "保持規律作息，您的自律神經調節狀況非常良好！";

    if (sdnn < 35) {
      stressLevel = "高壓 / 疲勞狀態";
      recommendation = "建議多休息、進行深呼吸調節，或透過溫水浴放鬆身心。";
    } else if (rmssd > 50 && sdnn > 45) {
      stressLevel = "身心放鬆狀態";
      recommendation = "您的身體恢復狀況極佳，適合進行高強度學習或體力鍛鍊！";
    } else if (sdnn < 20) {
      stressLevel = "極度疲勞 / 慢性壓力";
      recommendation = "警訊！您的自律神經活性偏低，請務必獲得充足睡眠並適度釋放壓力。";
    }

    let balanceDesc = "";
    if (Math.abs(snsPercent - 50) <= 5) {
      balanceDesc = "雙向平衡：交感與副交感雙系統處於良好動態平衡狀態。";
    } else if (snsPercent > 55) {
      balanceDesc = `交感偏亢 (${snsPercent}% vs ${pnsPercent}%)：身體處於應激興奮狀態，可能伴隨焦慮、心跳偏快或壓力負荷過重。`;
    } else {
      balanceDesc = `副交感偏亢 (${pnsPercent}% vs ${snsPercent}%)：身體處於深沉放鬆或低能量疲勞狀態，油門動力不足。`;
    }

    let causeDesc = "";
    if (sdnn < 20) {
      causeDesc = `受試者整體自主神經活性極低 (SDNN = ${sdnn.toFixed(1)}ms)，處於極度疲勞或慢性壓力下，自律神經系統調節功能嚴重衰退。`;
    } else if (sdnn < 35) {
      causeDesc = `自律神經調節功能偏低 (SDNN = ${sdnn.toFixed(1)}ms)，處於高壓或疲勞狀態下，身體抗壓調節資源受限。`;
    } else {
      causeDesc = `自律神經調節功能良好 (SDNN = ${sdnn.toFixed(1)}ms)，身體神經系統總體活力充沛，具備優秀的適應力。`;
    }

    return {
      status: "分析成功",
      hr: hr,
      sdnn: Math.round(sdnn * 10) / 10,
      rmssd: Math.round(rmssd * 10) / 10,
      vitality: vitalityScore,
      sns: snsPercent,
      pns: pnsPercent,
      sns_active: snsActive,
      pns_active: pnsActive,
      rsp: avgRsp,
      pr_val: prVal,
      pr_status: prStatus,
      qrs_val: qrsVal,
      qrs_status: qrsStatus,
      qt_val: qtVal,
      qt_status: qtStatus,
      state: stressLevel,
      balance_desc: balanceDesc,
      cause: causeDesc,
      recommendation: recommendation
    };
  }
}
