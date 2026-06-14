# Smart-Aquarium-Pi (智慧魚缸監控系統) 🐟

![Status](https://img.shields.io/badge/Status-Beta-orange)
![Security](https://img.shields.io/badge/Security-HTTPS%20%2B%20PWA-blue)
![Network](https://img.shields.io/badge/Network-NAS%20Reverse%20Proxy-green)
![Deployment](https://img.shields.io/badge/Deployment-Gunicorn%20(gthread)%20%2B%20systemd-red)

這是一個基於 **Raspberry Pi 4** 的全方位魚缸管理解決方案。透過 **NAS 反向代理 (Reverse Proxy)** 與 **Let's Encrypt SSL** 實現安全的遠端 HTTPS 訪問，並提供完整的 **PWA (Progressive Web App)** 行動端體驗。

---

## 🌟 核心功能 (Features)

* **即時串流與操作 (Live Stream & UI)：**
    * 透過 Flask 與 OpenCV 實現低延遲的 MJPEG 影像串流 (Image Streaming)。
    * **全平台縮放系統：** 支援行動端 **雙指撥弄縮放 (Pinch Zoom)** 與 PC 端 **Ctrl + 滾輪縮放**。
    * **智慧邊界限制：** 實作邊界演算法防止影像放大後拖曳超出黑框。
* **PWA 行動端優化 (Mobile Experience)：**
    * **應用程式化：** 支援「加入主畫面」，提供無網址列的沈浸式全螢幕體驗。
    * **智慧安裝導引：** 自動偵測環境，針對 Android 彈出安裝視窗，針對 iOS 提供分享導引。
    * **橫向鎖定 (Landscape Lock)：** 全螢幕模式下自動請求橫屏顯示，優化 16:9 監視視野。
* **多層級安全防護 (Security)：**
    * **HTTPS 加密：** 整合 Synology NAS 反向代理與 SSL 憑證，確保外部存取安全性。
    * **驗證系統：** 使用 `Flask-Login` 搭配 `Scrypt` 保護管理員帳密。
    * **動態封鎖：** 實作階梯式 IP 限制機制（持久化存儲於 `banned_ips.json`）。
* **自動化排程 (Automation)：**
    * 支援 **28BYJ-48 步進馬達** 控制的精準自動餵食。
    * 視覺化排程管理介面 (CRUD)，支援燈光與換水自動化。

---

## 🛠️ 硬體與網路架構 (Hardware & Network)

| 類別 | 項目 | 備註 |
| :--- | :--- | :--- |
| **控制核心** | Raspberry Pi 5 | 使用專屬虛擬環境 `.venv` 執行 |
| **服務引擎** | Gunicorn (gthread) | 採用線程模式 (Threads) 以相容硬體控制 |
| **影像擷取** | USB 網路攝影機 | 自動掃描 `/dev/video*` 裝置 |
| **動力系統** | 28BYJ-48 + ULN2003 | 用於自動餵食器 (Stepper Motor) |
| **外部訪問** | Synology Reverse Proxy | 透過 Port 5081 (HTTPS) 轉發至 5080 (HTTP) |
| **安全憑證** | Let's Encrypt SSL | PWA 運作之必要條件 |

---

## 📂 專案架構 (Project Structure)

```bash
├── app.py              # Flask 後端主程式 (鏡頭串流、API、安全邏輯)
├── config.json         # 自動化排程配置文件
├── config_secret.json  # 敏感帳號密碼雜湊檔
├── banned_ips.json     # 惡意 IP 封鎖名單 (Persistent Ban List)
├── requirements.txt    # 虛擬環境所需依賴
├── .venv/              # Python 虛擬環境 (Virtual Environment)
├── templates/
│   ├── index.html      # 主介面 (含 PWA 導引、縮放拖曳、Banner)
│   └── login.html      # 安全登入介面
└── static/
    ├── sw.js           # PWA Service Worker (離線支援基礎)
    ├── manifest.json   # PWA 應用定義檔 (圖示、顏色、啟動模式)
    └── resource/
        └── icon.png    # 1024x1024 高解析度應用圖標
```

---

## 🚀 快速上手 (Quick Start)

### 1. 進入虛擬環境並安裝
```bash
cd ~/Desktop/IotFishTank
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 測試服務啟動
使用 Gunicorn 配合 **gthread** 於 5080 Port 啟動：
```bash
gunicorn --worker-class gthread --threads 15 --bind 0.0.0.0:5080 app:app
```

---

## ⚙️ 自動化部署 (Automatic Deployment)

為確保樹莓派重啟後（未登入前）自動運行服務，本專案採用 **systemd** 管理。

### 1. 建立 Service 檔案
```bash
sudo nano /etc/systemd/system/fishtank.service
```

### 2. 貼入以下配置
```ini
[Unit]
Description=Gunicorn gthread service for IoT Fish Tank
After=network.target

[Service]
User=ericweng
Group=www-data
WorkingDirectory=/home/ericweng/Desktop/IotFishTank
Environment="PATH=/home/ericweng/Desktop/IotFishTank/.venv/bin"

# 使用 gthread 模式，確保對底層硬體驅動 (GPIO/USB) 的相容性
ExecStart=/home/ericweng/Desktop/IotFishTank/.venv/bin/gunicorn \
    --worker-class gthread \
    --workers 1 \
    --threads 15 \
    --timeout 0 \
    --keep-alive 5 \
    --preload \
    --bind 0.0.0.0:5080 \
    app:app

# 核心需求：即使沒登入也會自動開啟，崩潰自動重啟
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. 啟用服務
```bash
sudo systemctl daemon-reload
sudo systemctl enable fishtank.service
sudo systemctl start fishtank.service
```

---

## 🛡️ 系統穩定性維護 (Watchdog System)

針對 Raspberry Pi 5 網卡偶發的韌體鎖死 (Firmware Hang, Error -110) 與網路斷連問題，本專案實作了三層防禦機制。

### 1. 網路監控腳本 (Network Watchdog)
建立於 `/usr/local/bin/net_watchdog.sh`，具備硬體偵測與階段式恢復邏輯：
```bash
#!/bin/bash

# 強制定義絕對路徑，確保 Cron 執行時能找到所有指令
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TARGET="8.8.8.8"
GATEWAY="192.168.1.1"
LOG_FILE="/var/log/network_watchdog.log"

# [偵錯] 每次啟動寫入日誌
echo "$(date): 監控啟動檢查" >> $LOG_FILE

# 1. 第一階段：確認網路是否可連通外網
/usr/bin/ping -c 3 -W 5 $TARGET > /dev/null 2>&1

if [ $? -eq 0 ]; then
    # 網路正常，清除舊的 dmesg 錯誤紀錄，避免重複重啟
    /usr/bin/dmesg -C
    exit 0
fi

# 2. 第二階段：檢查是否為硬體鎖死 (Error -110)
HW_ERROR=$(/usr/bin/dmesg | /usr/bin/tail -n 50 | /usr/bin/grep "\-110")

if [ ! -z "$HW_ERROR" ]; then
    echo "$(date): [偵測鎖死] 偵測到硬體鎖死訊號，進行最終閘道檢查..." >> $LOG_FILE
    # 雙重確認：如果連區域網路路由器都 ping 不到，執行強制重啟
    /usr/bin/ping -c 2 -W 3 $GATEWAY > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "$(date): [嚴重故障] 硬體確認鎖死且無法連向路由器，執行強制重啟！" >> $LOG_FILE
        /usr/bin/dmesg -C
        /sbin/reboot
        exit 0
    fi
fi

# 3. 第三階段：嘗試軟修復 (重新關聯 Wi-Fi)
echo "$(date): [階段 1] 網路不通，執行 nmcli 重啟 wlan0..." >> $LOG_FILE
/usr/bin/nmcli device disconnect wlan0 > /dev/null 2>&1
/usr/bin/sleep 5
/usr/bin/nmcli device connect wlan0 > /dev/null 2>&1
```
如果是使用 windows 遠端 ssh 複製貼上記得 ```sudo sed -i 's/\r$//' /usr/local/bin/net_watchdog.sh```避免 ```\r```的問題

### 2. 定時任務配置 (Crontab)
透過 `sudo crontab -e` 進行系統級別的監控與基礎維護：
```cron
# 開機自動關閉 Wi-Fi 省電模式，防止鎖死
@reboot iw dev wlan0 set power_save off
# 開機 40 秒後主動宣告
@reboot sleep 40 && /usr/bin/ping -c 5 192.168.1.1 > /dev/null 2>&1

# 每 3 分鐘執行一次監控腳本
*/3 * * * * /bin/bash /usr/local/bin/net_watchdog.sh

# 每天凌晨 5 點重啟系統
0 5 * * * /sbin/reboot
```

### 3. 日誌追蹤 (Logging)
所有watchdog的動作均記錄於系統標準日誌目錄，可透過以下指令分析運行狀態：
```bash
# 查看網路修復與重啟歷史紀錄
cat /var/log/network_watchdog.log
```

---

## 📝 待辦清單 (Todo List)

- [x] 完成 PWA 封裝與 HTTPS 反向代理設定
- [x] 實作全平台 (觸控/滑鼠) 影像縮放與防超界拖曳
- [x] 整合正式鏡頭串流 (MJPEG Stream)
- [x] 實作 Gunicorn + systemd 自動化部署 (開機自啟動)
- [x] 採用 gthread 模型優化硬體併發存取
- [x] 實作多層級 Watchdog 系統 (自動修復 -110 鎖死)
- [ ] 實作 OpenCV 魚隻偵測 (Object Detection)
- [ ] 增加環境光感應自動補光功能

---

### 💡 技術觀念 (Knowledge Base)

* **Gunicorn (gthread)：** 採用作業系統級別的線程 (**pthreads**) 處理併發。相較於非同步協程 (Coroutines)，線程模式在調用 C 擴展庫（如 OpenCV）或操作 GPIO 驅動時具備更佳的穩定性與預測性。
* **Reverse Proxy (反向代理)：** 由 NAS 處理 SSL 加密。由於 PWA 嚴格要求 **Secure Context** (HTTPS)，此架構是讓樹莓派在內網運行 HTTP 但外網享有 PWA 功能的最佳解。
* **Deterministic System (確定性系統)：** 透過凌晨定時重啟與高頻率watchdog.sh，將系統轉化為可預測的穩定狀態，大幅提升長期運作的無人值守能力。
