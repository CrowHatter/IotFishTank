# Smart-Aquarium-Pi (智慧魚缸監控系統) 🐟

![Status](https://img.shields.io/badge/Status-Beta-orange)
![Security](https://img.shields.io/badge/Security-HTTPS%20%2B%20PWA-blue)
![Network](https://img.shields.io/badge/Network-NAS%20Reverse%20Proxy-green)
![Deployment](https://img.shields.io/badge/Deployment-Gunicorn%20(gthread)%20%2B%20systemd-red)

這是一個基於 **Raspberry Pi Zero 2W** 的全方位魚缸管理解決方案。透過 **NAS 反向代理 (Reverse Proxy)** 與 **Let's Encrypt SSL** 實現安全的遠端 HTTPS 訪問，並提供完整的 **PWA (Progressive Web App)** 行動端體驗。

---

## 🌟 核心功能 (Features)

* **雙攝影機即時串流 (Dual-Camera Live Stream)：**
    * Camera A：CSI OV5647（picamera2/libcamera），VPU 硬體 MJPEG 編碼，零 CPU 開銷。
    * Camera B：USB V4L2（OpenCV），軟體 MJPEG 串流。
    * **全平台縮放系統：** 支援行動端 **雙指撥弄縮放 (Pinch Zoom)** 與 PC 端 **Ctrl + 滾輪縮放**。
    * **智慧邊界限制：** 實作邊界演算法防止影像放大後拖曳超出黑框。

* **攝影機曝光控制 (Exposure Control)：**
    * 20 步曝光梯（0–20），三段區間模型（暗端增益爬坡 / 中段對數曝光時間 / 亮端增益爬坡）。
    * 軟體自動亮度執行緒：每 3 秒調整一步趨近目標亮度（可手動鎖定）。
    * 每顆攝影機獨立曝光控制與亮度目標校正。

* **水位偵測系統 (Water Level Detection)：**
    * OpenCV 純視覺偵測：以黑色膠帶為基準線，梯度分析定位水面。
    * 可調參數：ROI、梯度閾值、Gamma、幀數中位數。
    * 調校 UI（`/api/water_level/tune`）與基準線校正（`/api/water_level/calibrate`）。
    * 支援自動排程定期檢測，低水位觸發警報旗標。

* **PWA 行動端優化 (Mobile Experience)：**
    * **應用程式化：** 支援「加入主畫面」，提供無網址列的沈浸式全螢幕體驗。
    * **智慧安裝導引：** 自動偵測環境，針對 Android 彈出安裝視窗，針對 iOS 提供分享導引。
    * **橫向鎖定 (Landscape Lock)：** 全螢幕模式下自動請求橫屏顯示，優化 16:9 監視視野。

* **多層級安全防護 (Security)：**
    * **HTTPS 加密：** 整合 Synology NAS 反向代理與 SSL 憑證，確保外部存取安全性。
    * **驗證系統：** 使用 `Flask-Login` 搭配 `werkzeug` pbkdf2 保護管理員帳密。
    * **動態封鎖：** 實作階梯式 IP 限制機制（持久化存儲於 `banned_ips.json`）：5 次失敗=1 分鐘封鎖，10 次=10 分鐘，15 次=永久。

* **自動化排程 (Automation)：**
    * APScheduler 每 10 分鐘整點觸發，支援以下四種排程類型：
        * `auto_feed`：自動餵食（可指定餵食器 A / B / 兩者）。
        * `auto_light`：自動燈光開關。
        * `auto_water_level`：自動水位檢測。
        * `auto_water_change`：自動換水（待實作）。

---

## 🛠️ 硬體與網路架構 (Hardware & Network)

| 類別 | 項目 | 備註 |
| :--- | :--- | :--- |
| **控制核心** | Raspberry Pi Zero 2W | ARMv7，512 MB RAM；使用 `.venv` 虛擬環境 |
| **服務引擎** | Gunicorn (gthread) | 線程模式相容硬體驅動（GPIO / V4L2） |
| **Camera A** | CSI OV5647 固定焦距模組 | picamera2/libcamera，VPU 硬體 MJPEG |
| **Camera B** | USB V4L2 攝影機 | OpenCV，自動掃描 `/dev/video*`，by-path 持久綁定 |
| **動力系統** | 28BYJ-48 × 2 + ULN2003 | 餵食器 A（GPIO 17,18,27,22）、B（GPIO 23,24,25,8） |
| **燈光控制** | 繼電器模組 | GPIO 12，主動低電位單脈衝觸發 |
| **外部訪問** | Synology Reverse Proxy | Port 5081 (HTTPS) → 5080 (HTTP) |
| **安全憑證** | Let's Encrypt SSL | PWA 運作之必要條件 |

---

## 📂 專案架構 (Project Structure)

```
├── app.py                  # Flask 後端主程式（路由、APScheduler、硬體協調）
├── config.json             # 排程、攝影機綁定、水位設定、裝置狀態
├── config_secret.json      # 帳號密碼雜湊（werkzeug pbkdf2）
├── banned_ips.json         # IP 封鎖名單
├── hashsecrect.py          # 產生密碼雜湊的工具腳本
├── test_cam.py             # 攝影機測試腳本
├── requirements.txt        # Python 依賴（picamera2 除外，需 apt 安裝）
├── hardware/
│   ├── camera_ctrl.py      # CsiCamera（CSI A）、FishCamera（USB B）、enumerate_cameras
│   ├── motor_ctrl.py       # FishFeeder（餵食器 A / B）
│   ├── light_ctrl.py       # LightRelay（繼電器燈光）
│   └── water_level.py      # WaterLevelDetector（OpenCV 水位偵測）
├── templates/
│   ├── index.html          # 主介面（雙攝影機、縮放拖曳、排程 Modal、PWA）
│   └── login.html          # 登入介面
└── static/
    ├── sw.js               # PWA Service Worker
    ├── manifest.json       # PWA 應用定義
    └── resource/
        └── icon.png        # 1024×1024 應用圖標
```

---

## 🚀 快速上手 (Quick Start)

### 1. 進入虛擬環境並安裝
```bash
cd ~/fishtank
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
# 安裝 OpenCV runtime 依賴
# 分批安裝 + 清快取，避免 Pi Zero 2W 512 MB OOM
sudo apt update && sync && sudo sysctl -w vm.drop_caches=3
sudo apt install -y --no-install-recommends libavcodec59 libavformat59 && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt install -y --no-install-recommends libswscale6 libavutil57 && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt install -y --no-install-recommends libopenblas0 libgfortran5 && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt install -y --no-install-recommends libwebp7 libwebpdemux2 libopenjp2-7 && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt install -y --no-install-recommends libgl1 libglib2.0-0 && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt install -y --no-install-recommends libgtk-3-0 libatlas3-base && sync && sudo sysctl -w vm.drop_caches=3
sleep 5
sudo apt clean && sync && sudo sysctl -w vm.drop_caches=3
```

```bash
# 安裝 picamera2（Camera A / CSI OV5647 所需）
# 必須使用系統套件，不可裝入 .venv（依賴 libcamera 系統層綁定）
sudo apt install -y --no-install-recommends python3-picamera2
```

### 2. 產生登入密碼雜湊
```bash
python hashsecrect.py
# 將輸出填入 config_secret.json：
# {"users": {"你的帳號": "pbkdf2:sha256:..."}}
```

### 3. 啟動服務（開發測試）
```bash
gunicorn --worker-class gthread --workers 1 --threads 15 --timeout 0 --bind 0.0.0.0:5080 app:app
```

---

## ⚙️ 自動化部署 (Automatic Deployment)

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
User=<你的使用者名稱>
Group=www-data
WorkingDirectory=/path/to/fishtank
Environment="PATH=/path/to/fishtank/.venv/bin"

ExecStart=/path/to/fishtank/.venv/bin/gunicorn \
    --worker-class gthread \
    --workers 1 \
    --threads 15 \
    --timeout 0 \
    --bind 0.0.0.0:5080 \
    app:app

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

# 查看即時 log
journalctl -u fishtank.service -f
```

---

## 🛡️ 系統穩定性維護 (Watchdog System)

針對 Pi Zero 2W 長時間運行下可能出現的 Wi-Fi 斷線與服務卡死，實作雙層防禦機制：網路監控 + 服務健康監控，兩者觸發修復動作時都會推播 Discord 通知。

### 1. 網路監控腳本 (Network Watchdog)

**步驟 1：建立腳本檔案**
```bash
sudo nano /usr/local/bin/net_watchdog.sh
```

貼入以下內容（`DISCORD_WEBHOOK` 換成自己申請的 Discord Webhook URL）：
```bash
#!/bin/bash

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

TARGET="8.8.8.8"
GATEWAY="192.168.1.1"
LOG_FILE="/var/log/network_watchdog.log"
DISCORD_WEBHOOK="<你的 Discord Webhook URL>"

notify() {
    /usr/bin/curl -s -H "Content-Type: application/json" \
        -d "{\"content\": \"$1\"}" \
        --max-time 10 \
        "$DISCORD_WEBHOOK" >> $LOG_FILE 2>&1
}

echo "$(date): 監控啟動檢查" >> $LOG_FILE

# 第一階段：確認外網連通性
/usr/bin/ping -c 3 -W 5 $TARGET > /dev/null 2>&1

if [ $? -eq 0 ]; then
    /usr/bin/dmesg -C
    exit 0
fi

# 第二階段：檢查硬體錯誤訊號
HW_ERROR=$(/usr/bin/dmesg | /usr/bin/tail -n 50 | /usr/bin/grep "\-110")

if [ ! -z "$HW_ERROR" ]; then
    echo "$(date): [偵測鎖死] 偵測到硬體錯誤，進行閘道檢查..." >> $LOG_FILE
    /usr/bin/ping -c 2 -W 3 $GATEWAY > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "$(date): [嚴重故障] 確認鎖死，執行強制重啟！" >> $LOG_FILE
        notify "🚨 [魚缸網路警報] 偵測到 Wi-Fi 硬體鎖死（-110 錯誤 + 閘道不通），$(date '+%Y-%m-%d %H:%M:%S') 執行強制重開機"
        /usr/bin/dmesg -C
        /sbin/reboot
        exit 0
    fi
fi

# 第三階段：軟修復（重新關聯 Wi-Fi）
echo "$(date): [階段 1] 網路不通，執行 nmcli 重啟 wlan0..." >> $LOG_FILE
notify "⚠️ [魚缸網路警報] 外網不通，$(date '+%Y-%m-%d %H:%M:%S') 執行 Wi-Fi 軟修復（重新連接 wlan0）"
/usr/bin/nmcli device disconnect wlan0 > /dev/null 2>&1
/usr/bin/sleep 5
/usr/bin/nmcli device connect wlan0 > /dev/null 2>&1
```

外網正常時不發通知（避免洗版），只有真正觸發修復動作才推播，並用不同 emoji 區分嚴重度：⚠️ 軟修復（重連 Wi-Fi）、🚨 強制重開機（硬體鎖死）。

**步驟 2：修正權限與建立 log 檔**
```bash
# 清除 Windows 換行符（SSH 複製貼上可能產生 \r）
sudo sed -i 's/\r$//' /usr/local/bin/net_watchdog.sh
sudo chmod +x /usr/local/bin/net_watchdog.sh
sudo touch /var/log/network_watchdog.log
```

**步驟 3：手動測試**
```bash
sudo /usr/local/bin/net_watchdog.sh && echo "OK"
cat /var/log/network_watchdog.log
```

### 2. 服務健康監控腳本 (Service Watchdog)

Gunicorn worker 有可能在開機階段（例如相機/GPIO 初始化）卡進死鎖：process 存活、port 持續 listening，但 systemd 會誤判為 `active (running)`，實際上任何 HTTP request 都不會有回應。`net_watchdog.sh` 檢查的是外網連通性，抓不到這種「本機服務卡死但網路正常」的狀況，因此另外補上一層針對 Flask 服務本身的健康檢查。

**步驟 1：建立腳本檔案**
```bash
sudo nano /usr/local/bin/service_watchdog.sh
```

貼入以下內容（`DISCORD_WEBHOOK` 可與 `net_watchdog.sh` 共用同一個，或另外申請一個區分頻道）：
```bash
#!/bin/bash

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

URL="http://127.0.0.1:5080/"
LOG_FILE="/var/log/service_watchdog.log"
TIMEOUT=10
DISCORD_WEBHOOK="<你的 Discord Webhook URL>"

HTTP_CODE=$(/usr/bin/curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "$URL")

if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "302" ]; then
    MSG="🐟 [魚缸警報] fishtank.service 卡死 (HTTP_CODE=$HTTP_CODE)，已於 $(date '+%Y-%m-%d %H:%M:%S') 自動重啟"
    echo "$(date): [異常] curl 逾時或回應碼異常 (HTTP_CODE=$HTTP_CODE)，重啟 fishtank.service" >> $LOG_FILE
    /usr/bin/curl -s -H "Content-Type: application/json" \
        -d "{\"content\": \"$MSG\"}" \
        --max-time 10 \
        "$DISCORD_WEBHOOK" >> $LOG_FILE 2>&1
    /usr/bin/systemctl restart fishtank.service
fi
```

用 `curl --max-time 10` 對本機 `http://127.0.0.1:5080/` 發請求；卡死時 curl 會逾時而非回傳錯誤碼，`--max-time` 是必要設定，否則 watchdog 自己也會卡住。回應非 200/302（含逾時）即視為異常，重啟服務並推播通知。

**步驟 2：修正權限與建立 log 檔**
```bash
sudo sed -i 's/\r$//' /usr/local/bin/service_watchdog.sh
sudo chmod +x /usr/local/bin/service_watchdog.sh
sudo touch /var/log/service_watchdog.log
```

**步驟 3：手動測試**
```bash
sudo /usr/local/bin/service_watchdog.sh && echo "OK"
cat /var/log/service_watchdog.log
```

### 3. 定時任務配置 (Crontab)
透過 `sudo crontab -e` 加入：
```cron
# 開機關閉 Wi-Fi 省電模式
@reboot iw dev wlan0 set power_save off
# 開機 40 秒後主動宣告 ARP
@reboot sleep 40 && /usr/bin/ping -c 5 192.168.1.1 > /dev/null 2>&1

# 每 3 分鐘執行網路監控
*/3 * * * * /bin/bash /usr/local/bin/net_watchdog.sh

# 每 5 分鐘檢查一次 fishtank 服務是否卡死
*/5 * * * * /bin/bash /usr/local/bin/service_watchdog.sh

# 每天凌晨 5 點重啟
0 5 * * * /sbin/reboot
```

### 4. 日誌追蹤
```bash
cat /var/log/network_watchdog.log
cat /var/log/service_watchdog.log
journalctl -u fishtank.service --since "1 hour ago"
```

### 5. 疑難排解：worker 卡在 boot 階段的死鎖

若 `service_watchdog.sh` 頻繁觸發重啟，代表服務啟動時發生死鎖（非資源不足、非網路問題）。診斷方式：

```bash
# 找出真正的 worker PID（非 master）
ps -ef --forest | grep gunicorn

# dump 所有 thread 的呼叫堆疊，確認卡在哪個函式
sudo <venv>/bin/py-spy dump --pid <worker_pid> --locals

# 確認是否為真正的無限期等待（而非忙碌迴圈）
sudo strace -p <worker_pid> -f -tt
```

`futex(..., FUTEX_WAIT..., NULL)`（無 timeout）代表真正的死鎖，需要在 watchdog 自動重啟前的視窗內（預設 5 分鐘）現場抓包才能定位問題程式碼；一旦重啟，卡死狀態即消失，無法回溯。相機（CSI/USB）與 GPIO 初始化是目前的頭號嫌疑，但尚未有 case 定位到具體行號。

---

## 📝 待辦清單 (Todo List)

- [x] PWA 封裝與 HTTPS 反向代理設定
- [x] 全平台影像縮放與防超界拖曳
- [x] Gunicorn + systemd 自動化部署
- [x] gthread 模型優化硬體併發存取
- [x] 多層級 Watchdog 系統
- [x] 雙攝影機系統（Camera A CSI OV5647 + Camera B USB）
- [x] 20 步曝光控制系統（手動 / 自動亮度）
- [x] 雙餵食器自動餵食（A / B 獨立排程）
- [x] OpenCV 視覺水位偵測（膠帶基準線 + 梯度分析）
- [x] 水位低時自動補水（補水馬達尚未接線）
- [ ] OpenCV 魚隻偵測
- [x] 環境光感應自動補光

---

## 💡 技術觀念 (Knowledge Base)

* **Gunicorn (gthread)：** 採用 OS 層級 pthreads 處理併發。相較於非同步協程，線程模式在調用 C 擴展庫（OpenCV、RPi.GPIO）時具備更佳的穩定性。必須使用 `--workers 1` 避免多個 worker 爭搶 GPIO/CSI 資源。

* **VPU 硬體 MJPEG 編碼：** Camera A 使用 picamera2 的 `MJPEGEncoder`，JPEG 壓縮由 Pi Zero 2W 的 VPU 硬體完成，主 CPU 幾乎零負擔。Camera B 使用 `cv2.imencode()` 軟體壓縮，CPU 開銷較高。

* **picamera2 系統套件限制：** picamera2 依賴 libcamera 系統層綁定，無法用 `pip install` 安裝至 `.venv`，必須透過 `sudo apt install python3-picamera2` 安裝，並在 gunicorn 啟動時讓 venv 的 Python 可存取系統 site-packages。

* **Reverse Proxy (反向代理)：** 由 NAS 處理 SSL 加密。PWA 嚴格要求 Secure Context（HTTPS），此架構讓 Pi 在內網執行 HTTP 同時對外提供 PWA 功能。

* **排程時間槽對齊：** APScheduler 每 10 分鐘整點觸發（0/10/20/30/40/50 分），排程時間設定請使用結尾為 0 的分鐘值（如 08:30、14:00）。`misfire_grace_time=290` 容許串流高負載下的觸發延遲。
