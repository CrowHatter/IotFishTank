# Smart-Aquarium-Pi (智慧魚缸監控系統) 🐟

![Status](https://img.shields.io/badge/Status-In--Development-yellow)

這是一個基於 **Raspberry Pi** 的全方位魚缸管理解決方案。透過整合 **OpenCV 影像識別**、**IoT 感測器**與 **Cloudflare Tunnel**，實現遠端即時監控、自動餵食及魚隻安全報警功能。

---

## 🌟 核心功能 (Features)

* **即時串流 (Live Stream)：** 透過 Flask 與 OpenCV 實現低延遲的 USB 鏡頭影像傳輸 (MJPEG)。
* **影像識別 (Vision AI)：** 自動偵測魚隻是否跳躍隔板或發生異常行為。
* **自動化排程 (Automation)：**
    * **28BYJ-48 步進馬達** 控制的精準自動餵食系統。
    * 基於 `config.json` 的自動換水與燈光排程管理。
* **響應式儀表板 (RWD Dashboard)：** 仿 YouTube 介面設計，影片區塊捲動置頂 (Sticky View)，支援全螢幕縮放。
* **安全遠端訪問：** 透過 Cloudflare Tunnel 穿透內網，無需公開 IP 即可管理。

---

## 🛠️ 硬體清單 (Hardware Requirements)

| 類別 | 項目 | 備註 |
| :--- | :--- | :--- |
| **控制核心** | Raspberry Pi 4B / 5 | 建議 4GB RAM 以上以跑影像識別 |
| **影像擷取** | USB 網路攝影機 / Pi Camera | 用於即時監控與 AI 偵測 |
| **動力系統** | 28BYJ-48 步進馬達 + ULN2003 驅動板 | 用於自動餵食器 (Stepper Motor) |
| **環境感測** | DS18B20 防水溫度感測器 | 監控水溫 (Water Temperature Sensor) |
| **網路連接** | Cloudflare Tunnel | 實現外網遠端訪問 |

---

## 📂 專案架構 (Project Structure)

~~~bash
├── app.py              # Flask 後端主程式 (處理串流與 API)
├── config.json         # 自動化排程配置文件 (CRUD 目標)
├── hardware/
│   ├── motor_ctrl.py   # 步進馬達驅動邏輯 (GPIO 控制)
│   └── temp_sensor.py  # 溫度讀取邏輯
├── templates/
│   └── index.html      # 仿 YouTube 介面前端 (HTML/JS/Tailwind)
└── static/
    └── css/            # 自定義樣式與縮放邏輯
~~~

---

## 🚀 快速上手 (Quick Start)

### 1. 硬體接線 (Wiring)

* **步進馬達：** IN1-IN4 分別接至 Raspberry Pi GPIO 17, 18, 27, 22。
* **電源：** 驅動板電源建議外部供電，並與 Pi 共地 (Common Ground)。

### 2. 環境設定
~~~bash
# 安裝依賴套件
pip install flask opencv-python RPi.GPIO
~~~

### 3. 執行程式
~~~bash
python app.py
~~~
造訪 `http://<your-pi-ip>:5000` 即可開啟監控中心。

---

## 📺 介面操作說明

* **即時縮放 (Zoom)：** PC 端按住 `Ctrl + 滾輪`，手機端可直接雙指拉伸影片畫面。
* **狀態回饋 (Visual Feedback)：** 點擊餵食按鈕，圖示會進入「執行中」狀態，5 秒後恢復，模擬實體馬達運作。
* **管理視窗 (Modal)：** 點擊排程管理按鈕將彈出管理界面，支援對 `config.json` 中的數據進行 **CRUD (增刪改查)**。

---

## 💡 技術觀念 (Knowledge Base)

* **MJPEG (Motion JPEG)：** 本專案將影像幀編碼為 JPEG 格式透過 HTTP 傳輸，確保在樹莓派上的運算負擔最小且延遲極低。
* **Step Angle (步距角)：** 28BYJ-48 馬達透過減速齒輪提供極大扭力，適合精準控制飼料投放量。
* **Sticky Position：** 採用 CSS `sticky` 定位，確保在捲動長列表時，魚缸畫面始終維持在視野上方。

---

## 📝 待辦清單 (Todo List)

- [x] 完成 RWD 前端介面與影片循環 Demo
- [x] 整合 Flask 與 OpenCV 即時串流邏輯
- [ ] 實作 `config.json` 後端 CRUD API (Flask 路由)
- [ ] 開發 OpenCV 魚隻跳躍偵測 (Motion Detection)
- [ ] 配置 Cloudflare Tunnel 完成部署
