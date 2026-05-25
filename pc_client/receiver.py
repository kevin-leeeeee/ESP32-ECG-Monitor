import serial
import time
import numpy as np
import matplotlib
import struct
import asyncio
try:
    from bleak import BleakClient, BleakScanner
    HAS_BLEAK = True
except ImportError:
    HAS_BLEAK = False

# 設定全域中文字型，確保所有 UI 元件 (包括按鈕、坐標軸、標題) 能完美顯示中文
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'DejaVu Sans', 'Arial']
matplotlib.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import Button
from matplotlib.patches import Wedge, Polygon, Rectangle
from collections import deque
import threading
import os
import csv
from datetime import datetime

try:
    import neurokit2 as nk
except ImportError:
    print("缺少 neurokit2 或 scipy 套件，請執行: pip install neurokit2 scipy")
    exit()

# ==========================================
# 系統參數設定 
# ==========================================
SERIAL_PORT = 'AUTO' # 可設為 'AUTO' (自動偵測 USB), 'COM3' (手動指定), 'BLE' (藍牙), 'SIMULATE' (模擬)
BAUD_RATE = 115200
SAMPLE_RATE = 250 

# 設定量測總時間 (例如 120 秒 = 2 分鐘)
MEASUREMENT_DURATION = 120

# 畫面上只顯示最近 4 秒的波形
PLOT_WINDOW_POINTS = SAMPLE_RATE * 4

# 歷史紀錄檔案絕對路徑
HISTORY_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), 'history_records.csv'))

def migrate_csv_database_if_needed():
    """ 自動檢查並升級舊版 CSV 資料庫，補上 Avg_RSP (平均呼吸率) 欄位 """
    if not os.path.exists(HISTORY_FILE):
        return
        
    try:
        # 讀取現有內容
        rows = []
        headers = []
        with open(HISTORY_FILE, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers:
                rows = list(reader)
        
        # 如果欄位中沒有 Avg_RSP，就進行升級
        if headers and "Avg_RSP" not in headers:
            print("[資料庫升級] 偵測到舊版歷史紀錄資料庫，正在升級加入 [平均呼吸率 (Avg_RSP)] 欄位...")
            
            # 尋找插入位置，我們把 Avg_RSP 插在 Avg_HR 後面
            idx_hr = headers.index("Avg_HR")
            new_headers = headers[:idx_hr+1] + ["Avg_RSP"] + headers[idx_hr+1:]
            
            new_rows = []
            for row in rows:
                # 舊資料預設呼吸頻率補為 15.0 次/分 (常人標準值)
                new_row = row[:idx_hr+1] + ["15.0"] + row[idx_hr+1:]
                new_rows.append(new_row)
                
            # 寫入升級後的資料
            with open(HISTORY_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(new_headers)
                writer.writerows(new_rows)
            print("[資料庫升級] 歷史紀錄資料庫已成功升級！")
    except Exception as e:
        print(f"[資料庫升級警告] 自動升級 CSV 失敗: {e}")

def load_and_print_history():
    """ 讀取並在終端機印出過去的檢測歷史紀錄 """
    migrate_csv_database_if_needed() # 先確保資料庫欄位最新
    
    if not os.path.exists(HISTORY_FILE):
        print(f"\n[歷史紀錄] 歷史紀錄存檔路徑預計為: {HISTORY_FILE}")
        print("[歷史紀錄] 目前尚無歷史檢測紀錄。量測完成後會自動幫您存檔！")
        return []
    
    records = []
    try:
        with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            records = list(reader)
    except Exception as e:
        print(f"讀取歷史紀錄失敗: {e}")
        return []

    if not records:
        print(f"\n[歷史紀錄] 歷史紀錄檔案目前為空，路徑: {HISTORY_FILE}")
        return []

    print("\n" + "="*95)
    print(f" [歷史紀錄] 過去的自律神經檢測歷史紀錄 (存檔路徑: {HISTORY_FILE})")
    print("-"*95)
    print(f"{'量測時間':<20} | {'時間(秒)':<8} | {'平均心率':<8} | {'呼吸率(次/分)':<12} | {'SDNN(ms)':<10} | {'RMSSD(ms)':<10} | {'健康狀態':<15}")
    print("-"*95)
    
    # 顯示最新的 5 筆
    for r in records[-5:]:
        # 如果是舊資料可能沒有 Avg_RSP，預設給 15.0
        avg_rsp = float(r.get('Avg_RSP', 15.0))
        print(f"{r['Timestamp']:<20} | {r['Duration']:<8} | {r['Avg_HR']:<8} | {avg_rsp:<12.1f} | {float(r['SDNN']):<10.1f} | {float(r['RMSSD']):<10.1f} | {r['State']:<15}")
    print("="*95)
    print(" 提示：在心電圖視窗中按下鍵盤 【 H 】 鍵，或點擊下方 【歷史紀錄】 按鈕，可以即時查看 HRV 歷史趨勢變化圖！")
    print("="*95 + "\n")
    return records

def save_ecg_plot_image(plot_data, time_axis, is_sim, title, img_file, sample_rate=250):
    """
    將心電圖資料繪製成圖片存檔。
    如果總時間超過 60 秒，則會自動拆分成多個子圖（每列最多 60 秒），以防擠壓。
    自動根據資料範圍設定動態 Y 軸限度，防止波峰突出。
    """
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    
    max_time = time_axis[-1] if len(time_axis) > 0 else 0
    seconds_per_row = 60.0
    
    if max_time > seconds_per_row:
        num_rows = int(np.ceil(max_time / seconds_per_row))
    else:
        num_rows = 1
        
    fig_height = 3.0 * num_rows + 1.2
    fig_static = Figure(figsize=(15, fig_height))
    canvas = FigureCanvasAgg(fig_static)
    
    # 決定整體 Y 軸限度以防波峰突出 (使用整體資料範圍做為基準)
    if len(plot_data) > 0:
        y_min = np.min(plot_data)
        y_max = np.max(plot_data)
        padding = max(0.2 if is_sim else 150.0, (y_max - y_min) * 0.1)
        ylim_min = y_min - padding
        ylim_max = y_max + padding
    else:
        ylim_min, ylim_max = (0, 4095)
    
    for i in range(num_rows):
        ax = fig_static.add_subplot(num_rows, 1, i + 1)
        t_start = i * seconds_per_row
        t_end = (i + 1) * seconds_per_row
        
        # 篩選屬於該子圖時間區段的資料
        indices = np.where((time_axis >= t_start) & (time_axis < t_end))[0]
        if len(indices) > 0:
            ax.plot(time_axis[indices], plot_data[indices], color='#E74C3C', linewidth=0.8, alpha=0.9)
            
        ax.set_xlim(t_start, t_end)
        ax.set_ylim(ylim_min, ylim_max)
        ax.grid(True, linestyle='--', alpha=0.5)
        
        # 標示坐標軸文字
        if is_sim:
            ax.set_ylabel("模擬振幅", fontdict={'family': 'Microsoft JhengHei', 'size': 9})
        else:
            ax.set_ylabel("ADC 數值", fontdict={'family': 'Microsoft JhengHei', 'size': 9})
            
        # 只有最後一行顯示時間標籤
        if i == num_rows - 1:
            ax.set_xlabel("時間 (秒)", fontdict={'family': 'Microsoft JhengHei', 'size': 10})
            
    fig_static.suptitle(title, fontsize=13, fontweight='bold', family='Microsoft JhengHei')
    fig_static.tight_layout()
    fig_static.subplots_adjust(top=0.90 if num_rows == 1 else 0.94, hspace=0.35)
    canvas.print_figure(img_file, dpi=150)

def show_history_manager_window():
    """ 彈出 Tkinter 歷史紀錄管理器視窗，支援表格顯示、多行瀏覽、直接點擊刪除/檢視波形與開啟趨勢圖 """
    import tkinter as tk
    from tkinter import ttk, messagebox
    
    migrate_csv_database_if_needed() # 先確保資料庫欄位最新
    
    if not os.path.exists(HISTORY_FILE):
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("系統提示", "尚無歷史紀錄資料！")
        root.destroy()
        return
        
    records = []
    try:
        with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                records.append(r)
    except Exception as e:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("錯誤", f"讀取歷史紀錄失敗: {e}")
        root.destroy()
        return
        
    if not records:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("系統提示", "歷史紀錄檔中尚無資料！")
        root.destroy()
        return

    # 按時間倒序排列 (最新的在最上面)
    records_sorted = list(records)
    records_sorted.reverse()

    # 建立視窗
    manager = tk.Tk()
    manager.title("自律神經與心電歷史紀錄管理器")
    manager.geometry("1250x530")
    manager.resizable(True, True)
    
    # 視窗置中
    manager.update_idletasks()
    width = manager.winfo_width()
    height = manager.winfo_height()
    x = (manager.winfo_screenwidth() // 2) - (width // 2)
    y = (manager.winfo_screenheight() // 2) - (height // 2)
    manager.geometry(f'+{x}+{y}')

    # 設定精美現代外觀樣式
    style = ttk.Style(manager)
    style.configure("Treeview", font=("Microsoft JhengHei", 10), rowheight=26)
    style.configure("Treeview.Heading", font=("Microsoft JhengHei", 10, "bold"))

    # 1. 標題 Label (置頂)
    title_lbl = tk.Label(manager, text="📂 歷史量測紀錄清單 (雙擊某行或選取後點下方按鈕進行管理)", 
                         font=("Microsoft JhengHei", 11, "bold"), fg="#2C3E50", pady=10)
    title_lbl.pack(side="top", fill="x")

    # 2. 按鈕面板 (置底，優先 pack 確保置中且不被擠壓)
    btn_panel = tk.Frame(manager)
    btn_panel.pack(fill="x", side="bottom", pady=15)
    
    btn_frame = tk.Frame(btn_panel)
    btn_frame.pack(anchor="center")

    # 3. 左右並排佈局：左邊表格，右邊詳細分析 (在中間剩餘空間展開)
    left_frame = tk.Frame(manager)
    left_frame.pack(side="left", fill="both", expand=True, padx=(15, 5), pady=(0, 10))

    detail_frame = tk.LabelFrame(manager, text="🧠 自律神經與身心綜合診斷明細", 
                                 font=("Microsoft JhengHei", 10, "bold"), fg="#2C3E50", bg="#FDFEFE", 
                                 width=450, padx=2, pady=2, relief="solid", bd=1)
    detail_frame.pack(side="right", fill="both", padx=(5, 15), pady=(0, 10))
    detail_frame.pack_propagate(False) # 固定寬度防止被子元件擠開

    # 建立 Canvas 與垂直滾動條
    canvas = tk.Canvas(detail_frame, bg="#FDFEFE", highlightthickness=0)
    detail_vsb = ttk.Scrollbar(detail_frame, orient="vertical", command=canvas.yview)
    scroll_content = tk.Frame(canvas, bg="#FDFEFE")

    # 綁定 Canvas 大小與 scrollregion
    scroll_content.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas_window = canvas.create_window((0, 0), window=scroll_content, anchor="nw")
    canvas.bind(
        "<Configure>",
        lambda e: canvas.itemconfig(canvas_window, width=e.width)
    )
    canvas.configure(yscrollcommand=detail_vsb.set)

    # 滾輪事件
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def bind_mousewheel_recursive(widget):
        widget.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        widget.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))
        for child in widget.winfo_children():
            bind_mousewheel_recursive(child)

    canvas.pack(side="left", fill="both", expand=True)
    detail_vsb.pack(side="right", fill="y")

    # --- 左側表格設計 ---
    cols = ("Timestamp", "Duration", "Avg_HR", "Avg_RSP", "SDNN", "RMSSD", "State")
    tree = ttk.Treeview(left_frame, columns=cols, show="headings", selectmode="browse")
    
    # 定義欄位標題與寬度，開啟 stretch=True 確保填滿
    tree.heading("Timestamp", text="量測時間")
    tree.heading("Duration", text="長度 (秒)")
    tree.heading("Avg_HR", text="心率 (BPM)")
    tree.heading("Avg_RSP", text="呼吸率 (次/分)")
    tree.heading("SDNN", text="SDNN (ms)")
    tree.heading("RMSSD", text="RMSSD (ms)")
    tree.heading("State", text="身心狀態")
    
    tree.column("Timestamp", width=140, minwidth=130, anchor="center", stretch=True)
    tree.column("Duration", width=65, minwidth=50, anchor="center", stretch=True)
    tree.column("Avg_HR", width=75, minwidth=70, anchor="center", stretch=True)
    tree.column("Avg_RSP", width=95, minwidth=90, anchor="center", stretch=True)
    tree.column("SDNN", width=80, minwidth=70, anchor="center", stretch=True)
    tree.column("RMSSD", width=80, minwidth=70, anchor="center", stretch=True)
    tree.column("State", width=110, minwidth=100, anchor="center", stretch=True)
    
    # 滾動條
    vsb = ttk.Scrollbar(left_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    # --- 右側詳細面板設計 ---
    def create_section_header(parent, text):
        f = tk.Frame(parent, bg="#F2F4F4")
        f.pack(fill="x", pady=(10, 5))
        lbl = tk.Label(f, text=text, font=("Microsoft JhengHei", 10, "bold"), fg="#2C3E50", bg="#F2F4F4", anchor="w", padx=5)
        lbl.pack(fill="x")
        return f

    create_section_header(scroll_content, "基本量測資訊")
    
    time_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    time_frame.pack(fill="x", pady=2)
    tk.Label(time_frame, text="量測時間：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_time = tk.Label(time_frame, text="--", font=("Microsoft JhengHei", 10, "bold"), fg="#2C3E50", bg="#FDFEFE")
    lbl_time.pack(side="left")

    vitals_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    vitals_frame.pack(fill="x", pady=2)
    tk.Label(vitals_frame, text="生理指標：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_vitals = tk.Label(vitals_frame, text="--", font=("Microsoft JhengHei", 10), fg="#2C3E50", bg="#FDFEFE")
    lbl_vitals.pack(side="left")

    create_section_header(scroll_content, "自律神經平衡分析")
    
    vitality_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    vitality_frame.pack(fill="x", pady=2)
    tk.Label(vitality_frame, text="神經活力：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_vitality = tk.Label(vitality_frame, text="--", font=("Microsoft JhengHei", 10), fg="#2C3E50", bg="#FDFEFE")
    lbl_vitality.pack(side="left")

    sns_pns_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    sns_pns_frame.pack(fill="x", pady=2)
    tk.Label(sns_pns_frame, text="系統活性：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_sns_pns = tk.Label(sns_pns_frame, text="--", font=("Microsoft JhengHei", 10), fg="#2C3E50", bg="#FDFEFE")
    lbl_sns_pns.pack(side="left")

    balance_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    balance_frame.pack(fill="x", pady=2)
    tk.Label(balance_frame, text="平衡比例：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_balance = tk.Label(balance_frame, text="--", font=("Microsoft JhengHei", 10), fg="#2C3E50", bg="#FDFEFE")
    lbl_balance.pack(side="left")

    relation_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    relation_frame.pack(fill="x", pady=2)
    tk.Label(relation_frame, text="相對關係：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(anchor="nw", side="left")
    lbl_relation = tk.Label(relation_frame, text="--", font=("Microsoft JhengHei", 9), fg="#2E4053", bg="#FDFEFE", wraplength=340, justify="left")
    lbl_relation.pack(anchor="nw", side="left")

    create_section_header(scroll_content, "身心綜合診斷與專家建議")
    
    state_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    state_frame.pack(fill="x", pady=2)
    tk.Label(state_frame, text="健康狀態：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(side="left")
    lbl_state = tk.Label(state_frame, text="--", font=("Microsoft JhengHei", 11, "bold"), fg="#2C3E50", bg="#FDFEFE")
    lbl_state.pack(side="left")

    cause_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    cause_frame.pack(fill="x", pady=4)
    tk.Label(cause_frame, text="狀態成因：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(anchor="nw", side="left")
    lbl_cause = tk.Label(cause_frame, text="請選取紀錄", font=("Microsoft JhengHei", 9), fg="#2E4053", bg="#FDFEFE", wraplength=340, justify="left")
    lbl_cause.pack(anchor="nw", side="left")

    rec_frame = tk.Frame(scroll_content, bg="#FDFEFE")
    rec_frame.pack(fill="x", pady=4)
    tk.Label(rec_frame, text="專家建議：", font=("Microsoft JhengHei", 10, "bold"), fg="#7F8C8D", bg="#FDFEFE").pack(anchor="nw", side="left")
    lbl_rec = tk.Label(rec_frame, text="--", font=("Microsoft JhengHei", 9), fg="#566573", bg="#FDFEFE", wraplength=340, justify="left")
    lbl_rec.pack(anchor="nw", side="left")

    def update_detail_panel(values):
        if not values:
            lbl_time.config(text="--")
            lbl_vitals.config(text="--")
            lbl_vitality.config(text="--")
            lbl_sns_pns.config(text="--")
            lbl_balance.config(text="--")
            lbl_relation.config(text="未選取紀錄")
            lbl_state.config(text="未選取紀錄", fg="#7F8C8D")
            lbl_cause.config(text="請從左側點選任一量測紀錄查看詳細的身心狀態原因與專家建議。")
            lbl_rec.config(text="--")
            return

        ts, duration, avg_hr, avg_rsp_str, sdnn_str, rmssd_str, state = values
        try:
            sdnn = float(sdnn_str)
            rmssd = float(rmssd_str)
            hr = int(avg_hr)
            rsp = float(avg_rsp_str)
        except Exception:
            return

        # 重新計算指標
        vitality_score = min(100, max(10, int(100 * (1.0 - np.exp(-sdnn / 40.0)))))
        sd1 = rmssd / np.sqrt(2.0)
        sd2 = np.sqrt(max(1.0, 2.0 * (sdnn**2) - 0.5 * (rmssd**2)))
        pns_active = min(100, max(10, int(100 * (1.0 - np.exp(-sd1 / 20.0)))))
        sns_active = min(100, max(10, int(100 * (1.0 - np.exp(-sd2 / 50.0)))))
        total_active = sns_active + pns_active
        sns_percent = int((sns_active / total_active) * 100) if total_active > 0 else 50
        pns_percent = 100 - sns_percent

        # 相對關係
        if sns_percent > 55:
            sns_pns_relation_text = "交感偏亢 (油門過深)。身體處於緊繃或壓力應激狀態，建議調節放鬆。"
        elif pns_percent > 55:
            sns_pns_relation_text = "副交感偏亢 (煞車過深)。身體處於休整低能耗狀態，可能略顯疲憊。"
        else:
            sns_pns_relation_text = "雙系統平衡 (黃金比例)。交感與副交感維持理想動態平衡，調控正常。"

        # 原因
        if sdnn < 20:
            state_cause_text = "整體神經活性 (SDNN) 嚴重低下，代表長期壓力累積，調節能力已嚴重透支。"
        elif sdnn < 35:
            state_cause_text = "總體活性偏低，近期可能有睡眠不足、過度疲勞或壓力偏大。"
        elif rmssd > 50 and sdnn > 45:
            state_cause_text = "副交感活性充沛，身體處於高效修復與放鬆狀態，調控力極佳。"
        else:
            state_cause_text = "神經活性適中，交感與副交感維持動態平衡，抗壓適應力良好。"

        # 建議
        recommendation = "保持規律作息，您的自律神經調節狀況非常良好！"
        state_color = "#27AE60" # 綠色
        if sdnn < 20:
            state_color = "#C0392B" # 深紅
            recommendation = "警訊！您的自律神經活性偏低，請務必獲得充足睡眠並適度釋放壓力。"
        elif sdnn < 35:
            state_color = "#E74C3C" # 紅色
            recommendation = "建議多休息、進行深呼吸調節，或透過溫水浴放鬆身心。"
        elif rmssd > 50 and sdnn > 45:
            state_color = "#2980B9" # 藍色
            recommendation = "您的身體恢復狀況極佳，適合進行高強度學習或體力鍛鍊！"

        # 更新介面
        lbl_time.config(text=ts)
        lbl_vitals.config(text=f"{hr} BPM  |  平均呼吸率: {rsp:.1f} 次/分 ({duration}秒)")
        lbl_vitality.config(text=f"{vitality_score} / 100  (SDNN:{sdnn:.1f}ms, RMSSD:{rmssd:.1f}ms)")
        lbl_sns_pns.config(text=f"交感 (油門): {sns_active}  |  副交感 (煞車): {pns_active}")
        lbl_balance.config(text=f"交感 {sns_percent}%  vs  副交感 {pns_percent}%")
        lbl_relation.config(text=sns_pns_relation_text)
        lbl_state.config(text=state, fg=state_color)
        lbl_cause.config(text=state_cause_text)
        lbl_rec.config(text=recommendation)

    def on_tree_select(event):
        selected_item = tree.selection()
        if not selected_item:
            update_detail_panel(None)
            return
        values = tree.item(selected_item, "values")
        update_detail_panel(values)

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    # 填入數據
    def refresh_tree():
        # 清空
        for item in tree.get_children():
            tree.delete(item)
        # 讀取
        current_records = []
        try:
            with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    current_records.append(r)
        except:
            pass
        current_records.reverse()
        for idx, r in enumerate(current_records):
            avg_rsp = float(r.get('Avg_RSP', 15.0))
            tree.insert("", "end", iid=str(idx), values=(
                r["Timestamp"],
                r["Duration"],
                r["Avg_HR"],
                f"{avg_rsp:.1f}",
                r["SDNN"],
                r["RMSSD"],
                r["State"]
            ))
        
        # 預設選取第一筆紀錄 (最新量測結果)
        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.focus(children[0])

    refresh_tree()

    # 按鈕動作實作
    def get_selected_record():
        selected_item = tree.selection()
        if not selected_item:
            messagebox.showwarning("系統提示", "請先從清單中選取一筆紀錄！")
            return None
        values = tree.item(selected_item, "values")
        return values[0] # 返回 Timestamp 字串

    def view_selected():
        ts_str = get_selected_record()
        if not ts_str:
            return
            
        try:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            timestamp_file_str = dt.strftime("%Y%m%d_%H%M%S")
            raw_dir = os.path.join(os.path.dirname(HISTORY_FILE), 'raw_data')
            png_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_file_str}.png")
            csv_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_file_str}.csv")
            
            if os.path.exists(png_path):
                os.startfile(png_path)
            elif os.path.exists(csv_path):
                print("[歷史管理器] 發現 CSV，動態重建濾波後波形圖...")
                import pandas as pd
                df = pd.read_csv(csv_path)
                adc_vals = df['ADC_Value'].values
                
                title = f"心電圖 (ECG) 歷史波形紀錄 ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
                save_ecg_plot_image(plot_data, time_axis, is_sim, title, png_path)
                os.startfile(png_path)
            else:
                messagebox.showinfo("提示", "該筆紀錄為虛擬模擬資料，無歷史波形檔案！")
        except Exception as ex:
            messagebox.showerror("錯誤", f"開啟歷史波形失敗: {ex}")

    def delete_selected():
        ts_str = get_selected_record()
        if not ts_str:
            return
            
        confirm = messagebox.askyesno(
            "刪除紀錄確認",
            f"您確定要刪除此筆量測紀錄嗎？\n\n時間: {ts_str}\n\n警告：此操作將從歷史紀錄與硬碟中徹底刪除該數據與波形圖，且無法復原！"
        )
        if not confirm:
            return
            
        try:
            # 1. 從 CSV 刪除該行
            rows = []
            headers = []
            with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.reader(f)
                headers = next(reader)
                for r in reader:
                    if r[0] != ts_str:
                        rows.append(r)
                        
            with open(HISTORY_FILE, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
                
            # 2. 刪除相關實體檔案
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            timestamp_file_str = dt.strftime("%Y%m%d_%H%M%S")
            raw_dir = os.path.join(os.path.dirname(HISTORY_FILE), 'raw_data')
            png_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_file_str}.png")
            csv_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_file_str}.csv")
            
            deleted_count = 0
            if os.path.exists(png_path):
                os.remove(png_path)
                deleted_count += 1
            if os.path.exists(csv_path):
                os.remove(csv_path)
                deleted_count += 1
                
            messagebox.showinfo("成功", f"紀錄刪除成功！\n共刪除 {deleted_count} 個相關波形檔案。")
            refresh_tree()
        except Exception as ex:
            messagebox.showerror("錯誤", f"刪除失敗: {ex}")

    def show_trends():
        show_history_trend_chart()

    # 雙擊表格列直接開啟檢視
    tree.bind("<Double-1>", lambda event: view_selected())

    # 創建按鈕，使用傳統 Button 確保跨平台美觀，加寬邊距
    tk.Button(btn_frame, text="🔍 檢視心電圖", command=view_selected, font=("Microsoft JhengHei", 9, "bold"), width=13, bg="#3498DB", fg="white", activebackground="#2980B9", activeforeground="white").pack(side="left", padx=12)
    tk.Button(btn_frame, text="🗑️ 刪除此紀錄", command=delete_selected, font=("Microsoft JhengHei", 9, "bold"), width=13, bg="#E74C3C", fg="white", activebackground="#C0392B", activeforeground="white").pack(side="left", padx=12)
    tk.Button(btn_frame, text="📈 顯示趨勢圖", command=show_trends, font=("Microsoft JhengHei", 9, "bold"), width=13, bg="#2ECC71", fg="white", activebackground="#27AE60", activeforeground="white").pack(side="left", padx=12)
    tk.Button(btn_frame, text="關閉", command=manager.destroy, font=("Microsoft JhengHei", 9), width=10).pack(side="left", padx=12)

    # 遞迴綁定滑鼠滾輪，確保 hover 任何子元件時都能正常滾動
    bind_mousewheel_recursive(detail_frame)

    manager.mainloop()

def show_history_trend_chart():
    """ 畫出過去的 HRV 歷史變化趨勢圖 """
    migrate_csv_database_if_needed() # 先確保資料庫欄位最新
    
    if not os.path.exists(HISTORY_FILE):
        print("[警告] 尚無足夠的歷史資料可繪製趨勢圖！")
        return

    timestamps = []
    sdnn_list = []
    rmssd_list = []
    hr_list = []
    rsp_list = []
    raw_timestamps = [] # 儲存原始日期物件，方便找出對應的檔名

    try:
        with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                dt = datetime.strptime(r['Timestamp'], "%Y-%m-%d %H:%M:%S")
                raw_timestamps.append(dt)
                timestamps.append(dt.strftime("%m/%d %H:%M"))
                sdnn_list.append(float(r['SDNN']))
                rmssd_list.append(float(r['RMSSD']))
                hr_list.append(float(r['Avg_HR']))
                rsp_list.append(float(r.get('Avg_RSP', 15.0)))
    except Exception as e:
        print(f"繪製趨勢圖出錯: {e}")
        return

    if len(timestamps) < 2:
        print("[提示] 歷史紀錄少於 2 筆，請完成更多量測再來查看趨勢圖喔！")
        return

    # 建立趨勢圖視窗 (3 行 layout)
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8.5))
    fig.canvas.manager.set_window_title("HRV 歷史健康趨勢追蹤")

    # 1. SDNN & RMSSD 趨勢 (設定 picker=5，啟用點擊感應)
    ax1.plot(timestamps, sdnn_list, marker='o', color='#3498DB', label='SDNN (總體活性)', picker=5)
    ax1.plot(timestamps, rmssd_list, marker='s', color='#2ECC71', label='RMSSD (放鬆度)', picker=5)
    ax1.set_title("自律神經活性 (HRV) 歷史趨勢 (提示：點擊任何數據點可查看該次心電圖波形！)", 
                 fontdict={'family': 'Microsoft JhengHei', 'size': 11, 'color': '#2C3E50', 'weight': 'bold'})
    ax1.set_ylabel("ms")
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend()
    plt.setp(ax1.get_xticklabels(), rotation=10, ha="right")

    # 2. 平均心率趨勢
    ax2.plot(timestamps, hr_list, marker='^', color='#E74C3C', label='平均心率 (BPM)', picker=5)
    ax2.set_title("心率歷史趨勢", fontdict={'family': 'Microsoft JhengHei', 'size': 11})
    ax2.set_ylabel("BPM")
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend()
    plt.setp(ax2.get_xticklabels(), rotation=10, ha="right")

    # 3. 平均呼吸率趨勢
    ax3.plot(timestamps, rsp_list, marker='v', color='#9B59B6', label='呼吸率 (次/分)', picker=5)
    ax3.set_title("呼吸率歷史趨勢 (EDR 演算法自動提取)", fontdict={'family': 'Microsoft JhengHei', 'size': 11})
    ax3.set_ylabel("次/分 (Breaths/min)")
    ax3.grid(True, linestyle='--', alpha=0.5)
    ax3.legend()
    plt.setp(ax3.get_xticklabels(), rotation=10, ha="right")

    # 處理數據點被點擊的事件
    def on_pick(event):
        if not event.ind:
            return
        click_idx = event.ind[0]
        
        # 安全防護
        if click_idx >= len(raw_timestamps):
            return
            
        dt = raw_timestamps[click_idx]
        timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
        
        # 組合歷史檔案路徑
        raw_dir = os.path.join(os.path.dirname(HISTORY_FILE), 'raw_data')
        png_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_str}.png")
        csv_path = os.path.join(raw_dir, f"raw_ecg_{timestamp_str}.csv")
        
        # 彈出選單詢問使用者要檢視還是刪除
        action = [None]
        try:
            import tkinter as tk
            from tkinter import Toplevel, Button, Label, messagebox
            
            root = tk.Tk()
            root.withdraw() # 隱藏主視窗
            
            dialog = Toplevel(root)
            dialog.title("量測紀錄管理")
            dialog.geometry("340x150")
            dialog.resizable(False, False)
            
            # 視窗置中
            dialog.update_idletasks()
            width = dialog.winfo_width()
            height = dialog.winfo_height()
            x = (dialog.winfo_screenwidth() // 2) - (width // 2)
            y = (dialog.winfo_screenheight() // 2) - (height // 2)
            dialog.geometry(f'+{x}+{y}')
            
            dialog.transient(root)
            dialog.grab_set()
            
            Label(dialog, text=f"您點選了此筆紀錄：\n{dt.strftime('%Y-%m-%d %H:%M:%S')}", 
                  font=("Microsoft JhengHei", 10, "bold"), pady=15).pack()
            
            def view_action():
                action[0] = "view"
                dialog.destroy()
                
            def delete_action():
                action[0] = "delete"
                dialog.destroy()
                
            def cancel_action():
                dialog.destroy()
                
            btn_frame = tk.Frame(dialog)
            btn_frame.pack(fill="x", padx=15, pady=5)
            
            Button(btn_frame, text="🔍 檢視心電圖", command=view_action, font=("Microsoft JhengHei", 9), width=11, bg="#3498DB", fg="white").pack(side="left", padx=5)
            Button(btn_frame, text="🗑️ 刪除此紀錄", command=delete_action, font=("Microsoft JhengHei", 9), width=11, bg="#E74C3C", fg="white").pack(side="left", padx=5)
            Button(btn_frame, text="取消", command=cancel_action, font=("Microsoft JhengHei", 9), width=8).pack(side="left", padx=5)
            
            dialog.wait_window()
            root.destroy()
        except Exception as tk_err:
            print(f"[警告] 彈出管理視窗失敗，預設為檢視波形: {tk_err}")
            action[0] = "view"

        # 根據選擇執行動作
        if action[0] == "view":
            print(f"[檢視歷史] 正在開啟 {dt.strftime('%Y-%m-%d %H:%M:%S')} 的心電圖波形圖...")
            if os.path.exists(png_path):
                # 1. 圖片已存在，直接以系統預設程式打開
                try:
                    os.startfile(png_path)
                    print(f"[開啟波形] 已自動開啟波形圖：{png_path}")
                except Exception as ex:
                    print(f"[警告] 開啟波形圖失敗: {ex}")
            elif os.path.exists(csv_path):
                # 2. 只有 CSV，沒有 PNG (例如之前的測試紀錄)，動態重建圖表
                print("[開啟波形] 發現 CSV 原始數據，正在動態產生波形圖圖片...")
                try:
                    import pandas as pd
                    df = pd.read_csv(csv_path)
                    adc_vals = df['ADC_Value'].values
                    
                    title = f"心電圖 (ECG) 歷史波形紀錄 ({dt.strftime('%Y-%m-%d %H:%M:%S')})"
                    save_ecg_plot_image(plot_data, time_axis, is_sim, title, png_path)
                    
                    os.startfile(png_path)
                    print(f"[開啟波形] 動態生成並開啟成功：{png_path}")
                except Exception as ex:
                    print(f"[錯誤] 重建歷史波形圖失敗: {ex}")
            else:
                # 3. 模擬數據或舊測試資料，沒有原始檔
                print("[提示] 該筆紀錄為模擬資料或舊的測試資料，無原始心電圖波形可供檢視！")
                try:
                    import tkinter as tk
                    from tkinter import messagebox
                    root = tk.Tk()
                    root.withdraw()
                    messagebox.showinfo("系統提示", 
                                        f"量測時間: {dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                        "此筆紀錄為舊的系統資料或虛擬模擬資料，無歷史心電圖 (ECG) 原始波形檔案。")
                    root.destroy()
                except:
                    pass
                    
        elif action[0] == "delete":
            # 刪除邏輯
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                
                confirm = messagebox.askyesno(
                    "刪除紀錄確認", 
                    f"您確定要刪除此筆量測紀錄嗎？\n\n"
                    f"時間: {dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    "警告：此操作將會從歷史紀錄檔與硬碟中徹底刪除該數據點與心電圖檔案，且無法復原！"
                )
                
                if confirm:
                    # 1. 從 CSV 檔案刪除該行
                    rows = []
                    headers = []
                    with open(HISTORY_FILE, mode='r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        headers = next(reader)
                        for r in reader:
                            # 比較時間字串
                            if r[0] != dt.strftime('%Y-%m-%d %H:%M:%S'):
                                rows.append(r)
                                
                    with open(HISTORY_FILE, mode='w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(headers)
                        writer.writerows(rows)
                        
                    # 2. 刪除對應的 raw CSV & PNG 檔案
                    deleted_files_count = 0
                    if os.path.exists(png_path):
                        os.remove(png_path)
                        deleted_files_count += 1
                    if os.path.exists(csv_path):
                        os.remove(csv_path)
                        deleted_files_count += 1
                        
                    messagebox.showinfo("刪除成功", f"該筆紀錄已刪除！\n\n已清除 1 筆歷史指標資料與 {deleted_files_count} 個波形檔案。\n\n提示：請關閉此趨勢圖視窗並重新打開以更新顯示。")
                    print(f"[刪除成功] 已清除 {dt.strftime('%Y-%m-%d %H:%M:%S')} 的數據點與實體檔案。")
                root.destroy()
            except Exception as ex:
                print(f"[錯誤] 執行刪除失敗: {ex}")

    # 連結點擊事件
    fig.canvas.mpl_connect('pick_event', on_pick)

    plt.tight_layout()
    plt.show(block=False)

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def run_http_server(port=8080):
    import http.server
    import socketserver
    import os
    
    web_dir = os.path.join(os.path.dirname(__file__), 'web')
    class SafeHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=web_dir, **kwargs)
            
        def log_message(self, format, *args):
            pass # 靜音控制台輸出以保持整潔
            
    try:
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("", port), SafeHandler)
        server.serve_forever()
    except Exception as e:
        print(f"[HTTP 伺服器錯誤] {e}")

class ECGRealTimePlotter:
    def __init__(self, port, baud_rate, duration_seconds):
        self.port = port
        self.baud_rate = baud_rate
        self.duration = duration_seconds
        
        # 狀態機管理：'READY' (看波形準備中), 'MEASURING' (計時量測中), 'FINISHED' (量測結束)
        self.state = 'READY'
        self.start_time = None
        self.time_left = duration_seconds
        
        self.is_simulating = (port == 'SIMULATE')
        self.is_ble = (port == 'BLE')
        self.ble_connected = False
        self.ble_data_queue = deque()
        self.running = True
        
        # 收集到的完整資料緩衝區
        self.full_data = []
        
        # 用於即時繪圖的滾動緩衝區 (前後各增加 1 秒延遲緩衝以消除濾波器左右兩端的邊界效應)
        self.delay_points = SAMPLE_RATE
        total_len = PLOT_WINDOW_POINTS + 2 * self.delay_points
        self.plot_buffer = deque([0.0]*total_len, maxlen=total_len)
        
        # 初始化手機連線設定與服務
        self.local_ip = get_local_ip()
        self.ws_clients = set()
        self.ws_loop = None
        self.last_result = None
        
        # 指令同步旗標 (手機控制電腦端)
        self.pending_start_command = False
        self.pending_restart_command = False
        
        # GUI 更新同步旗標 (用於從背景執行緒安全傳遞 GUI 變更到主執行緒)
        self.pending_dashboard_update = None
        self.pending_final_dashboard = None
        self.pending_info_text = None
        self.leads_off_active = False
        self.consecutive_digits = 0
        
        # 啟動 HTTP 服務 (Port 8080)
        self.http_thread = threading.Thread(target=run_http_server, args=(8080,))
        self.http_thread.daemon = True
        self.http_thread.start()
        
        # 啟動 WebSocket 服務 (Port 8765)
        self.ws_thread = threading.Thread(target=self.start_websocket_server, args=(8765,))
        self.ws_thread.daemon = True
        self.ws_thread.start()
        
        print(f"\n==================================================")
        print(f"[手機連線網址] http://{self.local_ip}:8080")
        print(f"==================================================")
        
        # 初始化 Matplotlib 畫布 (分成上下兩區塊，加大寬高以容納 3欄式精緻儀表板)
        self.fig, (self.ax_ecg, self.ax_info) = plt.subplots(
            2, 1, figsize=(11.5, 7.8), gridspec_kw={'height_ratios': [3.0, 1.8]}
        )
        self.fig.canvas.manager.set_window_title("自律神經檢測系統 (定時量測)")
        
        # 調整子圖間距，留出最底部給 Button，最大化畫布可用性
        plt.subplots_adjust(top=0.93, bottom=0.13, left=0.07, right=0.96, hspace=0.32)
        
        # 註冊鍵盤事件
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        
        # --- ECG 波形圖 ---
        self.line, = self.ax_ecg.plot(range(PLOT_WINDOW_POINTS), [0]*PLOT_WINDOW_POINTS, color='red')
        self.ax_ecg.set_title("即時 ECG 心電圖波形", fontdict={'family': 'Microsoft JhengHei', 'size': 14})
        self.ax_ecg.set_ylim(-500, 4500)
        self.ax_ecg.set_xlim(0, PLOT_WINDOW_POINTS)
        self.ax_ecg.set_ylabel("ADC Value")
        self.ax_ecg.grid(True, linestyle='--', alpha=0.6)
        
        if self.is_simulating:
            self.ax_ecg.set_ylim(-1.5, 1.5)
        
        # --- 數據儀表板 ---
        self.ax_info.axis('off')
        self.info_text = None

        # --- 建立開始/重新量測按鈕 與 歷史紀錄按鈕 ---
        self.ax_btn = plt.axes([0.25, 0.03, 0.22, 0.05]) # 開始按鈕位置 [X, Y, Width, Height]
        self.btn_start = Button(self.ax_btn, '開始量測 (Start)', color='#2ECC71', hovercolor='#27AE60')
        self.btn_start.on_clicked(self.on_start_button_clicked)

        self.ax_btn_history = plt.axes([0.53, 0.03, 0.22, 0.05]) # 歷史紀錄按鈕位置 [X, Y, Width, Height]
        self.btn_history = Button(self.ax_btn_history, '歷史紀錄 (History)', color='#3498DB', hovercolor='#2980B9')
        self.btn_history.on_clicked(self.on_history_button_clicked)

        # 初始化連接
        if not self.is_simulating:
            if self.is_ble:
                if not HAS_BLEAK:
                    print("缺少 bleak 套件，無法使用藍牙連線！請執行: pip install bleak")
                    exit()
                print("[藍牙] 啟動藍牙 BLE 連線模式...")
                # 啟動 BLE 背景執行緒
                self.ble_thread = threading.Thread(target=self.run_ble_loop)
                self.ble_thread.daemon = True
                self.ble_thread.start()
            else:
                try:
                    self.ser = serial.Serial(port, baud_rate, timeout=1)
                    print(f"嘗試開啟串口 {port}...")
                    
                    # 進行數據確認檢測：嘗試讀取數據，確認有無有效資料流入
                    has_data = False
                    start_detect = time.time()
                    while time.time() - start_detect < 1.5:  # 檢測 1.5 秒
                        if self.ser.in_waiting > 0:
                            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                            if line:  # 讀到了非空字串 (可能是數字或 !LEADS_OFF!)
                                has_data = True
                                break
                        time.sleep(0.05)
                        
                    if not has_data:
                        print(f"[連線失敗] 雖然成功開啟了 {port}，但未檢測到來自 ESP32 的數據流入。")
                        print("   請確認：")
                        print("   1. ESP32 晶片已接妥並開機。")
                        print("   2. 該 COM Port 沒有被其他程式（如 Arduino IDE）佔用。")
                        self.ser.close()
                        exit()
                        
                    print(f"成功連接到 {port}，且已檢測到有效的數據流！")
                except Exception as e:
                    print(f"無法連接到 {port}，錯誤：{e}")
                    exit()
        else:
            print("[模擬] 啟動【模擬模式】：生成虛擬 ECG 訊號...")
            self.sim_ecg = nk.ecg_simulate(duration=300, sampling_rate=SAMPLE_RATE, heart_rate=72)
            self.sim_index = 0

    def run_ble_loop(self):
        """ 獨立執行緒中的 asyncio event loop，用來執行 BLE 連線 """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.ble_connect_task())
        except Exception as e:
            print(f"[藍牙執行緒錯誤] {e}")

    async def ble_connect_task(self):
        service_uuid = "19B10000-E8F2-537E-4F6C-D104768A1214"
        char_uuid = "19B10001-E8F2-537E-4F6C-D104768A1214"
        
        def notification_handler(sender, data):
            # 解析 10 個 uint16_t (Little-Endian)
            num_points = len(data) // 2
            if num_points > 0:
                vals = struct.unpack(f"<{num_points}H", data)
                self.ble_data_queue.extend(vals)

        while self.running:
            if not self.ble_connected:
                self.pending_info_text = "正在尋找藍牙裝置 ESP32_ECG_BLE..."
                print("[藍牙] 正在尋找藍牙裝置 ESP32_ECG_BLE...")
                try:
                    # 使用 find_device_by_filter 搜尋
                    device = await BleakScanner.find_device_by_filter(
                        lambda d, ad: d.name == "ESP32_ECG_BLE" or "ESP32_ECG_BLE" in (d.name or ""),
                        timeout=5.0
                    )
                    if device is None:
                        print("[藍牙] 未找到藍牙裝置 ESP32_ECG_BLE，5秒後重試...")
                        self.pending_info_text = "未找到藍牙裝置 ESP32_ECG_BLE，正在重試..."
                        await asyncio.sleep(5)
                        continue
                    
                    print(f"[藍牙] 找到裝置: {device.name} [{device.address}]，嘗試連線...")
                    self.pending_info_text = f"已找到藍牙裝置，正在連線 [{device.address}]..."
                    
                    async with BleakClient(device, timeout=10.0) as client:
                        self.ble_connected = client.is_connected
                        if self.ble_connected:
                            print(f"[藍牙] 成功連線到 {device.name}！")
                            self.pending_info_text = "藍牙連線成功！請保持放鬆並點擊開始量測。"
                            
                            # 訂閱特徵值
                            await client.start_notify(char_uuid, notification_handler)
                            
                            # 保持連線狀態直到斷線
                            while self.running and client.is_connected:
                                await asyncio.sleep(1)
                                
                            print("[藍牙] 藍牙連線中斷。")
                            self.ble_connected = False
                except Exception as e:
                    print(f"[藍牙] 連線或尋找裝置出錯: {e}")
                    self.ble_connected = False
                    self.pending_info_text = f"藍牙連線失敗: {str(e)}，重新嘗試中..."
            
            await asyncio.sleep(2)

        # 開啟倒數計時與狀態檢查執行緒
        self.timer_thread = threading.Thread(target=self.timer_loop)
        self.timer_thread.daemon = True
        self.timer_thread.start()
        
        # 繪製初始就緒畫面，利用完整區塊
        self.update_ready_dashboard()

    def start_websocket_server(self, port):
        import asyncio
        import json
        from websockets.server import serve
        
        self.ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.ws_loop)
        
        async def handler(websocket):
            self.ws_clients.add(websocket)
            try:
                # 連線成功時，立刻同步當前狀態
                await websocket.send(json.dumps({
                    "type": "state",
                    "state": self.state,
                    "time_left": self.time_left,
                    "total_duration": self.duration
                }))
                # 如果有之前的結果，也同步過去
                if self.last_result:
                    await websocket.send(json.dumps(self.last_result))
                    
                async for message in websocket:
                    data = json.loads(message)
                    if data.get('type') == 'command':
                        cmd = data.get('cmd')
                        if cmd == 'START':
                            self.pending_start_command = True
                        elif cmd == 'RESTART':
                            self.pending_restart_command = True
            except Exception as e:
                pass
            finally:
                self.ws_clients.remove(websocket)
                
        async def main():
            async with serve(handler, "0.0.0.0", port):
                await asyncio.Future()
                
        try:
            self.ws_loop.run_until_complete(main())
        except Exception as e:
            print(f"[WS 伺服器錯誤] {e}")

    def broadcast_to_ws(self, msg_dict):
        if not self.ws_clients:
            return
        import json
        import asyncio
        msg_str = json.dumps(msg_dict)
        if self.ws_loop and self.ws_loop.is_running():
            async def do_send():
                clients = list(self.ws_clients)
                if clients:
                    await asyncio.gather(*(client.send(msg_str) for client in clients), return_exceptions=True)
            asyncio.run_coroutine_threadsafe(do_send(), self.ws_loop)

    def on_history_button_clicked(self, event):
        """ 處理歷史紀錄按鈕被點擊 """
        print("[分析] 正在開啟歷史紀錄管理器...")
        show_history_manager_window()

    def on_start_button_clicked(self, event):
        """ 處理開始量測按鈕被點擊 """
        if self.state in ['READY', 'FINISHED']:
            print("[開始] 開始進行自律神經量測！")
            self.full_data = []
            
            # 清空 Serial 緩衝區，避免讀到舊資料導致計時器因數據累積而瞬間結束
            if not self.is_simulating:
                try:
                    self.ser.reset_input_buffer()
                except Exception as e:
                    print(f"[警告] 清空 Serial 緩衝區失敗: {e}")
                    
            self.start_time = time.time()
            self.time_left = self.duration
            self.state = 'MEASURING'
            self.last_result = None  # 清空上次結果
            
            # 廣播狀態給手機
            self.broadcast_to_ws({
                "type": "state",
                "state": "MEASURING",
                "time_left": self.time_left,
                "total_duration": self.duration
            })
            
            # 更改按鈕狀態為不可用 / 顯示量測中
            self.btn_start.label.set_text("量測進行中...")
            self.btn_start.color = '#BDC3C7' # 灰色
            self.btn_start.hovercolor = '#BDC3C7'
            self.ax_btn.figure.canvas.draw()

    def on_key_press(self, event):
        """ 監聽鍵盤事件 """
        if event.key in ['h', 'H', '竹']:
            print("[分析] 正在開啟歷史紀錄管理器...")
            show_history_manager_window()

    def update_plot(self, frame):
        """ 動畫更新函式 """
        # 當就緒狀態時，若導聯脫落狀態改變，即時重繪就緒儀表板
        if self.state == 'READY':
            current_leads_off = getattr(self, 'leads_off_active', False)
            if not hasattr(self, '_last_ready_leads_off') or self._last_ready_leads_off != current_leads_off:
                self._last_ready_leads_off = current_leads_off
                self.update_ready_dashboard()

        # 安全地在主執行緒執行來自背景執行緒 of GUI 更新
        if self.pending_dashboard_update is not None:
            time_str, hr_str, progress_bar = self.pending_dashboard_update
            self.pending_dashboard_update = None
            self.update_measuring_dashboard(time_str, hr_str, progress_bar)
            
        if self.pending_final_dashboard is not None:
            args = self.pending_final_dashboard
            self.pending_final_dashboard = None
            self.update_final_dashboard(*args)
            
        if self.pending_info_text is not None:
            text = self.pending_info_text
            self.pending_info_text = None
            self.update_info_text(text)

        # 處理來自手機的 WebSocket 指令
        if hasattr(self, 'pending_start_command') and self.pending_start_command:
            self.pending_start_command = False
            self.on_start_button_clicked(None)
        if hasattr(self, 'pending_restart_command') and self.pending_restart_command:
            self.pending_restart_command = False
            self.state = 'READY'
            self.update_ready_dashboard()
            self.broadcast_to_ws({
                "type": "state",
                "state": "READY",
                "time_left": self.duration,
                "total_duration": self.duration
            })

        new_samples = []

        if self.is_simulating:
            samples_to_generate = int(SAMPLE_RATE * 0.02)
            for _ in range(samples_to_generate):
                if self.sim_index < len(self.sim_ecg):
                    val = self.sim_ecg[self.sim_index]
                    new_samples.append(val)
                    self.sim_index = (self.sim_index + 1) % len(self.sim_ecg)
        else:
            if self.is_ble:
                while len(self.ble_data_queue) > 0:
                    val = self.ble_data_queue.popleft()
                    new_samples.append(val)
                    if val == 0:
                        if not self.leads_off_active:
                            self.leads_off_active = True
                            print(f"[Debug] [藍牙] 導聯脫落狀態改變為: {self.leads_off_active}")
                        self.consecutive_digits = 0
                    else:
                        self.consecutive_digits += 1
                        if self.consecutive_digits >= 50:  # 連續 50 個正常點才解除警報
                            if self.leads_off_active:
                                self.leads_off_active = False
                                print(f"[Debug] [藍牙] 導聯脫落狀態改變為: {self.leads_off_active}")
            else:
                try:
                    while self.ser.in_waiting > 0:
                        try:
                            line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                            if line == "!LEADS_OFF!":
                                new_samples.append(0) 
                                if not self.leads_off_active:
                                    self.leads_off_active = True
                                    print(f"[Debug] 導聯脫落狀態改變為: {self.leads_off_active}")
                                self.consecutive_digits = 0
                            elif line.isdigit():
                                new_samples.append(int(line))
                                self.consecutive_digits += 1
                                if self.consecutive_digits >= 50:  # 連續 50 個正常點 (約 0.2 秒) 才解除警報
                                    if self.leads_off_active:
                                        self.leads_off_active = False
                                        print(f"[Debug] 導聯脫落狀態改變為: {self.leads_off_active}")
                            elif line:
                                print(f"[Debug] 接收到非預期串口數據: {line}")
                        except Exception as e:
                            print(f"[Debug] 讀取單行數據異常: {e}")
                            pass
                except Exception as e:
                    print(f"[串口異常] USB 連線已斷開或丟失：{e}")
                    pass

        # 餵入繪圖緩衝區
        for sample in new_samples:
            self.plot_buffer.append(sample)
            # 只有在 MEASURING 狀態下才把數據寫入 full_data (存檔與計算用)
            if self.state == 'MEASURING':
                self.full_data.append(sample)

        # 廣播即時數據給手機 (我們每次打包當前幀收到的新樣本廣播，以減少封包量)
        if new_samples and self.state == 'MEASURING':
            if self.is_simulating:
                # 模擬數據的值大約在 -1.5 到 1.5，將其映射到 0 到 4095
                mapped_samples = [int((s + 1.5) / 3.0 * 4095) for s in new_samples]
                self.broadcast_to_ws({"type": "ecg", "data": mapped_samples})
            else:
                self.broadcast_to_ws({"type": "ecg", "data": new_samples})

        start_idx = self.delay_points
        end_idx = self.delay_points + PLOT_WINDOW_POINTS
        if not self.is_simulating:
            raw_arr = np.array(self.plot_buffer)
            if np.any(raw_arr != 0):
                try:
                    from scipy.signal import butter, filtfilt
                    nyq = SAMPLE_RATE / 2.0
                    b, a = butter(2, [0.5 / nyq, 40.0 / nyq], btype='band')
                    filtered = filtfilt(b, a, raw_arr) + 2000
                    # 擷取中間的顯示部分，前後各保留 1 秒作為濾波緩衝，完美消除左右兩側邊界效應
                    self.line.set_ydata(filtered[start_idx:end_idx])
                except Exception:
                    self.line.set_ydata(list(self.plot_buffer)[start_idx:end_idx])
            else:
                self.line.set_ydata(list(self.plot_buffer)[start_idx:end_idx])
        else:
            # 模擬數據亦同，僅擷取中間顯示點
            self.line.set_ydata(list(self.plot_buffer)[start_idx:end_idx])
            
        return self.line,

    def timer_loop(self):
        """ 處理倒數計時 """
        self.last_heartbeat_time = 0
        while self.running:
            # 每秒向 ESP32 發送一次 PC_CONNECT 心跳訊號，通知其關閉藍牙
            if not self.is_simulating and not self.is_ble and hasattr(self, 'ser') and self.ser.is_open:
                now = time.time()
                if now - self.last_heartbeat_time >= 1.0:
                    try:
                        self.ser.write(b"PC_CONNECT\n")
                        self.last_heartbeat_time = now
                    except Exception:
                        pass
            
            if self.state == 'MEASURING':
                # 改用實際收集到的數據樣本數來計算流逝時間！
                # 這樣可以 100% 保證「計時器顯示的秒數」與「收集到的訊號長度」絕對同步！
                # 解決因為 GUI 繪圖執行緒延遲導致二者不同步、卡在 00:01 且報告失敗的問題。
                elapsed = len(self.full_data) / SAMPLE_RATE
                self.time_left = max(0, self.duration - int(elapsed))
                
                mins, secs = divmod(self.time_left, 60)
                time_str = f"{mins:02d}:{secs:02d}"

                if self.time_left > 0:
                    # 即時估算心跳
                    current_len = len(self.full_data)
                    if current_len > SAMPLE_RATE * 5:
                        recent_data = self.full_data[-(SAMPLE_RATE * 5):]
                        try:
                            cleaned = nk.ecg_clean(recent_data, sampling_rate=SAMPLE_RATE)
                            _, info = nk.ecg_peaks(cleaned, sampling_rate=SAMPLE_RATE)
                            peaks = info["ECG_R_Peaks"]
                            if len(peaks) >= 2:
                                rr = np.diff(peaks) / SAMPLE_RATE * 1000
                                hr = int(60000 / np.mean(rr))
                                hr_str = f"{hr} BPM"
                            else:
                                hr_str = "計算中"
                        except:
                            hr_str = "計算中"
                    else:
                        hr_str = "收集資料中"

                    filled = int((self.duration - self.time_left) / self.duration * 10)
                    progress_bar = "■" * filled + "□" * (10 - filled)
                    self.pending_dashboard_update = (time_str, hr_str, progress_bar)
                    
                    # 廣播量測進度與即時心率到手機
                    self.broadcast_to_ws({
                        "type": "state",
                        "state": "MEASURING",
                        "time_left": self.time_left,
                        "total_duration": self.duration,
                        "hr": hr_str
                    })
                else:
                    # 倒數結束
                    self.state = 'FINISHED'
                    self.pending_info_text = "[數據分析中] 倒數結束！正在進行最終自律神經 HRV 計算分析..."
                    self.calc_final_hrv()
            
            time.sleep(0.1) # 縮短 sleep 時間，讓 UI 倒數更即時、順暢

    def calc_final_hrv(self):
        """ 計算整段量測的最終指標 """
        data = np.array(self.full_data)
        
        # 根據量測長度動態調整去除前導訊號的時間與長度限制，以支援短時間 (如 12 秒) 的快速測試
        slice_seconds = 3 if self.duration >= 30 else 1
        min_required_seconds = 10 if self.duration >= 30 else 5
        min_r_peaks = 10 if self.duration >= 30 else 3
        
        data = data[SAMPLE_RATE * slice_seconds:]
        
        if len(data) < SAMPLE_RATE * min_required_seconds:
            self.pending_info_text = "[量測失敗] 時間過短，無法計算完整的自律神經指標！"
            self.reset_button_to_restart()
            return
 
        try:
            cleaned = nk.ecg_clean(data, sampling_rate=SAMPLE_RATE)
            peaks, info = nk.ecg_peaks(cleaned, sampling_rate=SAMPLE_RATE)
            r_peaks = info["ECG_R_Peaks"]
 
            if len(r_peaks) < min_r_peaks:
                self.pending_info_text = "[量測失敗] 訊號雜訊過高或電極脫落，無法偵測到足夠的心跳波動！"
                self.reset_button_to_restart()
                return
 
            rr_intervals = np.diff(r_peaks) / SAMPLE_RATE * 1000
 
            avg_hr = int(60000 / np.mean(rr_intervals))
            sdnn = np.std(rr_intervals)
            rmssd = np.sqrt(np.mean(np.square(np.diff(rr_intervals))))
            
            # 計算標準化指標 (0 - 100 分，更加直觀好懂)
            # 1. 活力指數 (Vitality Score, 基於 SDNN) - 反映自律神經系統的總體調節能力
            vitality_score = min(100, max(10, int(100 * (1.0 - np.exp(-sdnn / 40.0)))))
            
            # 2. 基於非線性 Poincaré 幾何特徵 (SD1 / SD2) 計算交感與副交感神經各自活性指標
            sd1 = rmssd / np.sqrt(2.0)
            sd2 = np.sqrt(max(1.0, 2.0 * (sdnn**2) - 0.5 * (rmssd**2)))
            
            # 轉換為 0 - 100 活性分數
            pns_active = min(100, max(10, int(100 * (1.0 - np.exp(-sd1 / 20.0)))))  # 副交感活性 (煞車系統：負責放鬆修復)
            sns_active = min(100, max(10, int(100 * (1.0 - np.exp(-sd2 / 50.0)))))  # 交感活性 (油門系統：負責應激興奮)
            
            # 計算兩者的佔比 (平衡度)
            total_active = sns_active + pns_active
            sns_percent = int((sns_active / total_active) * 100)
            pns_percent = 100 - sns_percent
 
            # 使用 EDR 演算法從 ECG 訊號中提取呼吸波形並計算平均呼吸率
            avg_rsp = 15.0 # 預設常人靜息標準值
            try:
                rsp_signal = nk.ecg_rsp(cleaned, sampling_rate=SAMPLE_RATE)
                rsp_peaks, _ = nk.rsp_peaks(rsp_signal, sampling_rate=SAMPLE_RATE)
                peak_indices = np.where(rsp_peaks['RSP_Peaks'] == 1)[0]
                if len(peak_indices) >= 2:
                    intervals = np.diff(peak_indices) / SAMPLE_RATE
                    rates = 60.0 / intervals
                    avg_rsp = np.mean(rates)
                    # 進行常規生理範圍過濾 (8 - 30 次/分)，避免極短測試產生噪聲偏離
                    if avg_rsp < 8 or avg_rsp > 30:
                        avg_rsp = 15.0
            except Exception as ex:
                print(f"[呼吸波形提取提示] EDR 計算微幅受限，使用預設值。原因：{ex}")
 
            # 基於 ACLS 臨床指引計算心電圖傳導間期 (使用 DWT 離散小波變換定位特徵點)
            pr_val, qrs_val, qt_val = "N/A", "N/A", "N/A"
            pr_status, qrs_status, qt_status = "未知", "未知", "未知"
            
            try:
                _, waves = nk.ecg_delineate(cleaned, r_peaks, sampling_rate=SAMPLE_RATE, method='dwt')
                
                # 1. PR 間期 (P波起點至QRS起點) -> 評估第一度房室傳導阻滯
                p_onsets = np.array(waves.get('ECG_P_Onsets', []))
                r_onsets = np.array(waves.get('ECG_R_Onsets', []))
                if len(p_onsets) > 0 and len(r_onsets) > 0:
                    pr_diffs = (r_onsets - p_onsets) / SAMPLE_RATE
                    pr_mean = np.nanmean(pr_diffs)
                    if not np.isnan(pr_mean):
                        pr_val = f"{pr_mean:.3f}s"
                        if pr_mean > 0.20:
                            pr_status = "一度阻滯"
                        elif pr_mean < 0.12:
                            pr_status = "偏短"
                        else:
                            pr_status = "正常"
                
                # 2. QRS 波寬 (QRS起點至QRS終點) -> 評估束支傳導阻滯
                r_offsets = np.array(waves.get('ECG_R_Offsets', []))
                if len(r_onsets) > 0 and len(r_offsets) > 0:
                    qrs_diffs = (r_offsets - r_onsets) / SAMPLE_RATE
                    qrs_mean = np.nanmean(qrs_diffs)
                    if not np.isnan(qrs_mean):
                        qrs_val = f"{qrs_mean:.3f}s"
                        if qrs_mean > 0.12:
                            qrs_status = "寬波 (阻滯)"
                        elif qrs_mean > 0.10:
                            qrs_status = "不完全阻滯"
                        elif qrs_mean < 0.06:
                            qrs_status = "偏窄"
                        else:
                            qrs_status = "正常"
                            
                # 3. QT 間期 (QRS起點至T波終點) -> 評估QT延長與心律不整風險
                t_offsets = np.array(waves.get('ECG_T_Offsets', []))
                if len(r_onsets) > 0 and len(t_offsets) > 0:
                    qt_diffs = (t_offsets - r_onsets) / SAMPLE_RATE
                    qt_mean = np.nanmean(qt_diffs)
                    if not np.isnan(qt_mean):
                        qt_val = f"{qt_mean:.3f}s"
                        if qt_mean > 0.44:
                            qt_status = "延長 (警訊)"
                        elif qt_mean < 0.36:
                            qt_status = "偏短"
                        else:
                            qt_status = "正常"
            except Exception as delineate_err:
                print(f"[ECG 間期分析警告] 小波特徵定位受限: {delineate_err}")

            stress_level = "正常"
            recommendation = "保持規律作息，您的自律神經調節狀況非常良好！"
 
            if sdnn < 20:
                stress_level = "極度疲勞 / 慢性壓力"
                recommendation = "警訊！您的自律神經活性偏低，請務必獲得充足睡眠並適度釋放壓力。"
            elif sdnn < 35:
                stress_level = "高壓 / 疲勞狀態"
                recommendation = "建議多休息、進行深呼吸調節，或透過溫水浴放鬆身心。"
            elif rmssd > 50 and sdnn > 45:
                stress_level = "身心放鬆狀態"
                recommendation = "您的身體恢復狀況極佳，適合進行高強度學習或體力鍛鍊！"
 
            # 儲存到歷史紀錄 CSV 檔案 (新增 avg_rsp 欄位)
            self.save_to_history(avg_hr, avg_rsp, sdnn, rmssd, stress_level)
            # 儲存每一個原始取樣點數據與波形圖 PNG
            self.save_raw_data()
 
            report = f"================= 自律神經與心電生理分析報告 ({self.duration}秒) =================\n"
            report += f"平均心率: {avg_hr} BPM  |  平均呼吸率 (EDR): {avg_rsp:.1f} 次/分  |  活力總分: {vitality_score}/100\n"
            report += f"交感活性 (油門系統)：【 {sns_active} / 100 】  |  副交感活性 (煞車系統)：【 {pns_active} / 100 】\n"
            report += f"自律神經平衡度：【 交感 {sns_percent}%  vs  副交感 {pns_percent}% 】 (健康標準: 45%-55%)\n"
            report += f"ACLS 傳導：PR間期: {pr_val}({pr_status}) | QRS波寬: {qrs_val}({qrs_status}) | QT間期: {qt_val}({qt_status})\n"
            report += f"健康綜合狀態：【 {stress_level} 】  |  專家建議：{recommendation}\n"
            report += f"提示：現在可按下鍵盤 【 H 】 鍵來查看與管理歷史紀錄！"
            
            # 列印一份文字版到終端機供背景除錯或存檔
            print("\n" + report)
            
            # 計算平衡描述與成因描述 (與歷史紀錄管理器邏輯一致)
            balance_desc = ""
            if abs(sns_percent - 50) <= 5:
                balance_desc = "雙向平衡：交感與副交感雙系統處於良好動態平衡狀態。"
            elif sns_percent > 55:
                balance_desc = f"交感偏亢 ({sns_percent}% vs {pns_percent}%)：身體處於應激興奮狀態，可能伴隨焦慮、心跳偏快或壓力負荷過重。"
            else:
                balance_desc = f"副交感偏亢 ({pns_percent}% vs {sns_percent}%)：身體處於深沉放鬆或低能量疲勞狀態，油門動力不足。"

            cause_desc = ""
            if sdnn < 20:
                cause_desc = f"受試者整體自主神經活性極低 (SDNN = {sdnn:.1f}ms)，處於極度疲勞或慢性壓力下，自律神經系統調節功能嚴重衰退。"
            elif sdnn < 35:
                cause_desc = f"自律神經調節功能偏低 (SDNN = {sdnn:.1f}ms)，處於高壓或疲勞狀態下，身體抗壓調節資源受限。"
            else:
                cause_desc = f"自律神經調節功能良好 (SDNN = {sdnn:.1f}ms)，身體神經系統總體活力充沛，具備優秀的適應力。"

            self.last_result = {
                "type": "result",
                "hr": avg_hr,
                "rsp": round(avg_rsp, 1),
                "vitality": vitality_score,
                "sns": sns_percent,
                "pns": pns_percent,
                "balance_desc": balance_desc,
                "state": stress_level,
                "cause": cause_desc,
                "recommendation": recommendation,
                "sdnn": round(sdnn, 1),
                "rmssd": round(rmssd, 1),
                "sns_active": sns_active,
                "pns_active": pns_active,
                "pr_val": pr_val,
                "pr_status": pr_status,
                "qrs_val": qrs_val,
                "qrs_status": qrs_status,
                "qt_val": qt_val,
                "qt_status": qt_status
            }
            self.broadcast_to_ws(self.last_result)

            # 使用全新的 3欄式精緻儀表板更新 GUI
            self.pending_final_dashboard = (
                avg_hr, avg_rsp, vitality_score,
                sns_active, pns_active, sns_percent, pns_percent,
                pr_val, pr_status, qrs_val, qrs_status, qt_val, qt_status,
                stress_level, recommendation, sdnn, rmssd
            )
            self.reset_button_to_restart()
 
        except Exception as e:
            self.pending_info_text = f"[分析失敗] 過程出錯，可能是訊號不完整。錯誤訊息：{e}"
            self.reset_button_to_restart()
 
    def reset_button_to_restart(self):
        """ 恢復按鈕狀態為可點擊，並改成「重新量測」 """
        self.btn_start.label.set_text("重新量測 (Restart)")
        self.btn_start.color = '#2ECC71' # 亮綠色
        self.btn_start.hovercolor = '#27AE60'
        self.ax_btn.figure.canvas.draw()
 
    def save_to_history(self, hr, rsp, sdnn, rmssd, state):
        """ 將本次檢測結果寫入 CSV 存檔 """
        file_exists = os.path.exists(HISTORY_FILE)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            with open(HISTORY_FILE, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Duration", "Avg_HR", "Avg_RSP", "SDNN", "RMSSD", "State"])
                writer.writerow([timestamp, self.duration, hr, round(rsp, 1), round(sdnn, 2), round(rmssd, 2), state])
            print(f"[存檔] 本次量測結果已成功存檔至: {HISTORY_FILE}")
        except Exception as e:
            print(f"[警告] 存檔失敗: {e}")

    def save_raw_data(self):
        """ 儲存本次量測的每一個原始取樣點 (Raw ECG) 與波形圖圖片 """
        if not self.full_data:
            print("[警告] 無原始數據可儲存！")
            return
        
        # 建立 raw_data 資料夾 (若不存在)
        raw_dir = os.path.join(os.path.dirname(__file__), 'raw_data')
        if not os.path.exists(raw_dir):
            try:
                os.makedirs(raw_dir)
            except Exception as e:
                print(f"[警告] 建立 raw_data 目錄失敗: {e}")
                raw_dir = os.path.dirname(__file__) # 失敗則改為當前目錄
                
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_file = os.path.join(raw_dir, f"raw_ecg_{timestamp}.csv")
        img_file = os.path.join(raw_dir, f"raw_ecg_{timestamp}.png")
        
        # 1. 儲存 CSV 數據
        try:
            with open(raw_file, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Sample_Index", "ADC_Value"])
                for idx, val in enumerate(self.full_data):
                    writer.writerow([idx, val])
            print(f"[原始數據存檔] 每個取樣點數據已成功存檔至: {raw_file}")
        except Exception as e:
            print(f"[警告] 原始數據存檔失敗: {e}")

        # 2. 儲存 PNG 完整波形圖片 (使用獨立的 Agg Canvas，避免干擾主 GUI 執行緒)
        try:
            # 剔除前導訊號
            slice_seconds = 3 if self.duration >= 30 else 1
            plot_data = self.full_data[SAMPLE_RATE * slice_seconds:]
            time_axis = np.arange(len(plot_data)) / SAMPLE_RATE
            
            if not self.is_simulating:
                try:
                    from scipy.signal import butter, filtfilt
                    nyq = SAMPLE_RATE / 2.0
                    b, a = butter(2, [0.5 / nyq, 40.0 / nyq], btype='band')
                    plot_data = filtfilt(b, a, plot_data) + 2000
                except Exception as filt_err:
                    print(f"[波形存檔] 儲存波形濾波失敗，使用原始數據: {filt_err}")

            title = f"心電圖 (ECG) 歷史波形紀錄 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
            save_ecg_plot_image(plot_data, time_axis, self.is_simulating, title, img_file)
            print(f"[波形存檔] 完整心電圖波形已成功儲存為圖片: {img_file}")
        except Exception as e:
            print(f"[警告] 儲存心電圖波形圖片失敗: {e}")

    def update_info_text(self, text, is_final=False):
        """ 繪製一般狀態或錯誤訊息的簡單提示 """
        self.ax_info.clear()
        self.ax_info.axis('off')
        
        # 決定顏色
        bg_color, border_color, text_color = '#F4F6F9', '#BDC3C7', '#2E4053'
        if "失敗" in text or "錯誤" in text:
            bg_color, border_color, text_color = '#FDEDEC', '#F1948A', '#922B21'
            
        self.ax_info.text(0.5, 0.5, text, 
                          fontsize=11.5, color=text_color, ha='center', va='center', family='Microsoft JhengHei',
                          bbox=dict(facecolor=bg_color, edgecolor=border_color, boxstyle='round,pad=0.7'))
        self.fig.canvas.draw_idle()

    def update_ready_dashboard(self):
        """ 繪製就緒狀態的儀表板 """
        self.ax_info.clear()
        self.ax_info.axis('off')
        self.ax_info.patch.set_facecolor('#F8F9FA')
        
        # 根據是否脫線決定背景色與提示文字
        if getattr(self, 'leads_off_active', False):
            bg_color = '#FDEDEC'      # 淺紅色背景
            border_color = '#F1948A'  # 紅色邊框
            title_color = '#C0392B'
            title_text = "⚠️ 偵測到導聯脫落！請檢查貼片與導線連接"
            instructions = (
                "【 貼片連接指引 】\n"
                "請將 AD8232 電極貼片貼於人體：紅(RA-右臂/右胸)、黃(LA-left-左臂/左胸)、綠(LL-左腿/腹部邊緣)\n"
                "提示：目前導聯脫落中，請檢查杜邦線 (LO+, LO-)、音訊插頭與貼片是否貼緊人體！\n\n"
                f"[手機連線網址] http://{self.local_ip}:8080"
            )
            text_color = '#C0392B'
        else:
            if self.is_ble:
                if not self.ble_connected:
                    bg_color = '#EBF5FB'      # 淺藍色背景
                    border_color = '#AED6F1'  # 藍色邊框
                    title_color = '#2980B9'
                    title_text = "🔍 正在搜尋藍牙裝置 ESP32_ECG_BLE..."
                    instructions = (
                        "【 藍牙連線中 】\n"
                        "請確保 ESP32 已經通電啟動，並且電腦的藍牙已開啟。\n"
                        "系統將自動搜尋並連接，請稍候...\n\n"
                        f"[手機連線網址] http://{self.local_ip}:8080"
                    )
                else:
                    bg_color = '#E8F8F5'      # 淺綠色背景
                    border_color = '#7DCEA0'  # 綠色邊框
                    title_color = '#196F3D'
                    title_text = "✅ 藍牙連線成功！裝置: ESP32_ECG_BLE"
                    instructions = (
                        "【 貼片連接指引 】\n"
                        "請將 AD8232 電極貼片貼於人體：紅(RA-右臂/右胸)、黃(LA-left-左臂/左胸)、綠(LL-左腿/腹部邊緣)\n"
                        "提示：請保持身體放鬆、靜坐，然後點擊下方 [開始量測] 按鈕。\n\n"
                        f"[手機連線網址] http://{self.local_ip}:8080"
                    )
            else:
                bg_color = '#EAECEE'      # 預設灰色背景
                border_color = '#BDC3C7'  # 預設灰色邊框
                title_color = '#2C3E50'
                title_text = "自律神經與心電生理量測系統 (定時量測模式)"
                instructions = (
                    "【 貼片連接指引 】\n"
                    "請將 AD8232 電極貼片貼於人體：紅(RA-右臂/右胸)、黃(LA-left-左臂/左胸)、綠(LL-左腿/腹部邊緣)\n"
                    "提示：請保持身體放鬆、靜坐，避免移動與說話，然後點擊下方 [開始量測] 按鈕。\n\n"
                    f"[手機連線網址] http://{self.local_ip}:8080"
                )
            text_color = '#566573'

        # 繪製主標題
        self.ax_info.text(0.5, 0.76, title_text, 
                          fontsize=13, fontweight='bold', color=title_color, ha='center', va='center', family='Microsoft JhengHei')
        
        # 繪製指引與狀態
        self.ax_info.text(0.5, 0.35, instructions, 
                          fontsize=10.0, color=text_color, ha='center', va='center', family='Microsoft JhengHei',
                          bbox=dict(facecolor=bg_color, edgecolor=border_color, boxstyle='round,pad=0.5'))
        
        # 廣播 READY 狀態給手機
        self.broadcast_to_ws({
            "type": "state",
            "state": "READY",
            "time_left": self.duration,
            "total_duration": self.duration
        })
        
        self.fig.canvas.draw_idle()

    def update_measuring_dashboard(self, time_str, hr_str, progress_bar):
        """ 繪製量測進行中的儀表板 """
        self.ax_info.clear()
        self.ax_info.axis('off')
        
        # 根據是否脫線決定背景色與提示文字
        if getattr(self, 'leads_off_active', False):
            bg_color = '#FDEDEC'      # 淺紅色背景
            border_color = '#F1948A'  # 紅色邊框
            tip_text = "⚠️ 偵測到導聯脫落，請檢查貼片！"
            tip_color = '#C0392B'     # 深紅色文字
            tip_weight = 'bold'
        else:
            bg_color = '#EBF5FB'      # 預設淺藍色背景
            border_color = '#AED6F1'  # 預設藍色邊框
            tip_text = "請保持平穩深呼吸，不要說話與移動"
            tip_color = '#7F8C8D'     # 預設灰色文字
            tip_weight = 'normal'
            
        # 繪製背景容器
        self.ax_info.text(0.5, 0.5, "", bbox=dict(facecolor=bg_color, edgecolor=border_color, boxstyle='round,pad=15.0', alpha=0.9))
        
        # 3欄式排版
        # 1. 剩餘時間
        self.ax_info.text(0.18, 0.65, "剩餘時間", fontsize=10, color='#5D6D7E', ha='center', va='center', family='Microsoft JhengHei')
        self.ax_info.text(0.18, 0.35, time_str, fontsize=24, fontweight='bold', color='#2980B9', ha='center', va='center', family='Microsoft JhengHei')
        
        # 分割線 1
        self.ax_info.plot([0.36, 0.36], [0.15, 0.85], color=border_color, linestyle='--', linewidth=1.2)
        
        # 2. 即時心率
        self.ax_info.text(0.5, 0.65, "即時心率", fontsize=10, color='#5D6D7E', ha='center', va='center', family='Microsoft JhengHei')
        self.ax_info.text(0.5, 0.35, hr_str, fontsize=24, fontweight='bold', color='#C0392B', ha='center', va='center', family='Microsoft JhengHei')
        
        # 分割線 2
        self.ax_info.plot([0.64, 0.64], [0.15, 0.85], color=border_color, linestyle='--', linewidth=1.2)
        
        # 3. 量測進度與溫馨提示
        self.ax_info.text(0.82, 0.68, "量測進度與提示", fontsize=10, color='#5D6D7E', ha='center', va='center', family='Microsoft JhengHei')
        self.ax_info.text(0.82, 0.45, progress_bar, fontsize=12, fontweight='bold', color='#2C3E50', ha='center', va='center', family='Courier New')
        self.ax_info.text(0.82, 0.22, tip_text, fontsize=9, color=tip_color, fontweight=tip_weight, ha='center', va='center', family='Microsoft JhengHei')
        
        # 強制固定座標軸範圍，避免 plot 直線時觸發自動縮放 (Autoscale) 導致所有文字被裁剪隱藏
        self.ax_info.set_xlim(0, 1)
        self.ax_info.set_ylim(0, 1)
        self.fig.canvas.draw_idle()

    def update_final_dashboard(self, avg_hr, avg_rsp, vitality_score, sns_active, pns_active, sns_percent, pns_percent, pr_val, pr_status, qrs_val, qrs_status, qt_val, qt_status, stress_level, recommendation, sdnn, rmssd):
        """ 繪製最終報告的 3欄式精緻儀表板，整合原因與交感/副交感相對關係 """
        self.ax_info.clear()
        self.ax_info.axis('off')
        
        # 根據身心狀態決定背景底色與框線顏色
        bg_color, border_color, text_color = '#F9EBEA', '#F1948A', '#922B21'
        if "放鬆" in stress_level:
            bg_color, border_color, text_color = '#EAF2F8', '#85C1E9', '#1A5276'
        elif "正常" in stress_level or "平衡" in stress_level:
            bg_color, border_color, text_color = '#E8F8F5', '#7DCEA0', '#196F3D'
            
        # 繪製填滿整個 ax_info 的背景
        self.ax_info.add_patch(Rectangle((0.02, 0.02), 0.96, 0.96, facecolor=bg_color, edgecolor=border_color, linewidth=2, alpha=0.8, zorder=0))
        
        # 1. 頂部：基礎生理
        self.ax_info.text(0.06, 0.88, f"平均心率: {avg_hr} BPM  |  平均呼吸率: {avg_rsp:.1f} 次/分", fontsize=11, color='#2C3E50', ha='left', va='center', family='Microsoft JhengHei', fontweight='bold', zorder=2)
        acls_text = f"ACLS 傳導: PR {pr_val}({pr_status}) | QRS {qrs_val}({qrs_status}) | QT {qt_val}({qt_status})"
        self.ax_info.text(0.94, 0.88, acls_text, fontsize=9.5, color='#566573', ha='right', va='center', family='Microsoft JhengHei', zorder=2)
        self.ax_info.plot([0.05, 0.95], [0.81, 0.81], color=border_color, linestyle='-', linewidth=1.2, alpha=0.6, zorder=1)

        # 2. 中間偏上：神經活力 (單向進度條)
        self.ax_info.text(0.06, 0.70, "神經活力總分 (Vitality)", fontsize=11.5, fontweight='bold', color='#2C3E50', ha='left', va='center', family='Microsoft JhengHei', zorder=2)
        vit_color = '#27AE60' if vitality_score >= 60 else ('#F39C12' if vitality_score >= 30 else '#E74C3C')
        self.ax_info.text(0.94, 0.70, f"{vitality_score} / 100", fontsize=15, fontweight='bold', color=vit_color, ha='right', va='center', family='Courier New', zorder=2)
        
        # 神經活力進度條
        bar_y = 0.58
        self.ax_info.add_patch(Rectangle((0.06, bar_y), 0.88, 0.05, facecolor='#EAECEE', edgecolor='none', zorder=1))
        fill_width = 0.88 * (vitality_score / 100.0)
        self.ax_info.add_patch(Rectangle((0.06, bar_y), fill_width, 0.05, facecolor=vit_color, edgecolor='none', zorder=2))
        
        # 進度條刻度文字
        self.ax_info.text(0.06, 0.54, "0 (疲勞)", fontsize=8, color='#7F8C8D', ha='left', va='top', family='Microsoft JhengHei')
        self.ax_info.text(0.94, 0.54, "100 (充沛)", fontsize=8, color='#7F8C8D', ha='right', va='top', family='Microsoft JhengHei')

        # 3. 中間偏下：自律神經平衡 (雙向進度條)
        self.ax_info.text(0.06, 0.42, "自律神經平衡 (SNS vs PNS)", fontsize=11.5, fontweight='bold', color='#2C3E50', ha='left', va='center', family='Microsoft JhengHei', zorder=2)
        
        # 交感/副交感文字
        self.ax_info.text(0.06, 0.35, f"交感(油門) {sns_percent}%", fontsize=10, color='#E74C3C', ha='left', va='center', family='Microsoft JhengHei', fontweight='bold', zorder=2)
        self.ax_info.text(0.94, 0.35, f"副交感(煞車) {pns_percent}%", fontsize=10, color='#2980B9', ha='right', va='center', family='Microsoft JhengHei', fontweight='bold', zorder=2)
        
        # 雙向平衡條
        bal_y = 0.28
        sns_width = 0.88 * (sns_percent / 100.0)
        pns_width = 0.88 * (pns_percent / 100.0)
        self.ax_info.add_patch(Rectangle((0.06, bal_y), sns_width, 0.04, facecolor='#E74C3C', edgecolor='none', alpha=0.85, zorder=2))
        self.ax_info.add_patch(Rectangle((0.06 + sns_width, bal_y), pns_width, 0.04, facecolor='#3498DB', edgecolor='none', alpha=0.85, zorder=2))
        
        # 中心基準線
        self.ax_info.plot([0.5, 0.5], [bal_y - 0.02, bal_y + 0.06], color='#2C3E50', linewidth=2.0, zorder=3)
        self.ax_info.text(0.5, bal_y - 0.03, "平衡點", fontsize=8, color='#7F8C8D', ha='center', va='top', family='Microsoft JhengHei', zorder=3)

        # 4. 底部：綜合診斷與建議
        self.ax_info.plot([0.05, 0.95], [0.18, 0.18], color=border_color, linestyle='-', linewidth=1.2, alpha=0.6, zorder=1)
        self.ax_info.text(0.06, 0.12, f"綜合狀態: {stress_level}", fontsize=11.5, fontweight='bold', color=text_color, ha='left', va='center', family='Microsoft JhengHei', zorder=2)
        
        # 專家建議文字
        wrapped_rec = self.wrap_chinese_text(f"建議: {recommendation}", limit=32)
        self.ax_info.text(0.32, 0.14, wrapped_rec, fontsize=9.5, color='#34495E', ha='left', va='top', family='Microsoft JhengHei', zorder=2)
        
        # 強制固定座標軸範圍，避免 plot 直線時觸發自動縮放 (Autoscale) 導致所有文字被裁剪隱藏
        self.ax_info.set_xlim(0, 1)
        self.ax_info.set_ylim(0, 1)
        self.fig.canvas.draw_idle()
        
    def wrap_chinese_text(self, text, limit=18):
        """ 將中文文字每 limit 個字元插入換行符號 """
        lines = []
        current_line = []
        count = 0
        for char in text:
            current_line.append(char)
            if ord(char) > 127:
                count += 1
            else:
                count += 0.5
            if count >= limit:
                lines.append("".join(current_line))
                current_line = []
                count = 0
        if current_line:
            lines.append("".join(current_line))
        return "\n".join(lines)

    def start(self):
        self.ani = animation.FuncAnimation(self.fig, self.update_plot, interval=20, blit=False, cache_frame_data=False)
        plt.show()
        
    def close(self):
        self.running = False
        if not self.is_simulating:
            try:
                self.ser.close()
            except:
                pass

def auto_detect_serial_port():
    """ 自動掃描可用串口，優先尋找 CP210x, CH340, USB-SERIAL 等常用晶片 """
    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    
    # 1. 優先匹配常見 USB 轉串口晶片
    for p in ports:
        desc = p.description.upper()
        if any(keyword in desc for keyword in ["CH340", "CP210", "USB-SERIAL", "USB SERIAL", "FTDI"]):
            return p.device
            
    # 2. 如果沒有明顯的 USB 晶片描述，排除 Intel SOL 與 COM1 後，選擇第一個可用的 COM 埠
    for p in ports:
        desc = p.description.upper()
        if "SOL" not in desc and p.device != "COM1":
            return p.device
            
    # 3. 兜底回傳第一個可用串口
    if ports:
        return ports[0].device
        
    return None

if __name__ == '__main__':
    # 啟動時先載入並列印歷史清單
    load_and_print_history()
    
    port = SERIAL_PORT
    if port == 'AUTO':
        detected = auto_detect_serial_port()
        if detected:
            print(f"[自動偵測] 偵測到可能為 ESP32 的串口：{detected}")
            port = detected
        else:
            print("[自動偵測] 未偵測到任何可用的 USB 串口，預設嘗試 COM3...")
            port = 'COM3'
            
    plotter = ECGRealTimePlotter(port, BAUD_RATE, MEASUREMENT_DURATION)
    try:
        plotter.start()
    except KeyboardInterrupt:
        print("結束程式")
    finally:
        plotter.close()
