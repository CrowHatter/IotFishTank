
# Smart-Aquarium-Pi (智慧魚缸監控系統) 🐟

![Status](https://img.shields.io/badge/Status-In--Development-yellow)
![Security](https://img.shields.io/badge/Security-Flask--Login%20%2B%20Rate%20Limit-green)

這是一個基於 **Raspberry Pi** 的全方位魚缸管理解決方案。透過 **DDNS** 實現遠端訪問，並整合 **階梯式 IP 封鎖機制** 與 **Scrypt 密碼雜湊**，確保你的魚缸管理既直觀又安全。

---

## 🌟 核心功能 (Features)

* **即時串流 (Live Stream)：** 透過 Flask 與 OpenCV 實現低延遲的 USB 鏡頭影像傳輸 (MJPEG)。
* **多層級安全防護 (Security)：**
    * **驗證系統：** 使用 `Flask-Login` 搭配 `Scrypt` 雜湊演算法保護管理員帳密。
    * **動態封鎖：** 實作階梯式 IP 限制（1 分鐘內錯 5 次鎖 1 分鐘、10 次鎖 10 分鐘、15 次永久封鎖）。
    * **資料分離：** 敏感憑證存於 `config_secret.json`，一般排程存於 `config.json`，封鎖紀錄存於 `banned_ips.json`。
* **自動化排程 (Automation)：**
    * **28BYJ-48 步進馬達** 控制的精準自動餵食系統。
    * 基於 `config.json` 的自動換水與燈光排程管理 (CRUD)。
* **響應式儀表板 (RWD Dashboard)：** 支援行動端 **全螢幕自動橫向旋轉 (Landscape Lock)** 與 **雙指撥弄縮放 (Pinch Zoom)**。

---

## 🛠️ 硬體與網路清單 (Hardware & Network)

| 類別 | 項目 | 備註 |
| :--- | :--- | :--- |
| **控制核心** | Raspberry Pi 4B / 5 | 建議 4GB RAM 以上以跑影像識別 |
| **影像擷取** | USB 網路攝影機 / Pi Camera | 用於即時監控與 AI 偵測 |
| **動力系統** | 28BYJ-48 步進馬達 + ULN2003 | 用於自動餵食器 (Stepper Motor) |
| **環境感測** | DS18B20 防水溫度感測器 | 監控水溫 (Water Temperature Sensor) |
| **網路連接** | DDNS (Dynamic DNS) | 搭配路由器 Port Forwarding (Port 5080) |

---

## 📂 專案架構 (Project Structure)

```bash
├── app.py              # Flask 後端主程式 (含 Auth 與 Rate Limit 邏輯)
├── config.json         # 一般自動化排程配置文件
├── config_secret.json  # 敏感帳號密碼雜湊檔 (不應上傳至 Git)
├── banned_ips.json     # 惡意 IP 封鎖名單 (持久化存儲)
├── templates/
│   ├── index.html      # 主監控介面 (支援手機全螢幕旋轉/縮放)
│   └── login.html      # 安全登入介面 (含錯誤閃爍提示)
└── static/
    └── resource/       # 靜態資源 (圖示、Demo 影片)
```

---

## 🚀 快速上手 (Quick Start)

### 1. 環境設定
```bash
# 安裝依賴套件
pip install flask flask-login opencv-python RPi.GPIO
```

### 2. 初始安全設定
請先手動產生密碼雜湊並填入 `config_secret.json`：
```python
from werkzeug.security import generate_password_hash
# 將產出的字串填入 config_secret.json 的 users 欄位中
print(generate_password_hash("你的管理員密碼"))
```

### 3. 執行程式
```bash
python app.py
```
造訪 `http://<your-ddns-domain>:5080` 即可進入登入頁面。

---

## 📺 操作亮點 (UX Highlights)

* **Mobile Optimized：** 手機全螢幕模式下自動請求 **Landscape (橫向)** 顯示，避免 16:9 畫面左右裁切。
* **Pinch-to-Zoom：** 實作觸控事件監聽，支援行動端雙指縮放影片細節，解決全螢幕下原本無法縮放的問題。
* **Safety Lock：** 修正了全螢幕切換與按鈕點擊之間的事件冒泡 (Event Bubbling) 問題。

---

## 📝 待辦清單 (Todo List)

- [x] 完成 RWD 前端介面與全螢幕旋轉/縮放
- [x] 實作 `Flask-Login` 驗證與 `Scrypt` 雜湊
- [x] 開發階梯式 IP 封鎖機制 (Persistent Ban List)
- [ ] 整合 OpenCV USB 鏡頭即時串流 (正式取代 Demo 影片)
- [ ] 完成 28BYJ-48 步進馬達 GPIO 餵食控制
- [ ] 實作 OpenCV 魚隻跳躍偵測 (Motion Detection)

---

### 💡 技術觀念 (Knowledge Base)

* **ISO 8601 Format：** 封鎖時間採用 ISO 格式存儲於 JSON，確保跨系統的時間解析準確性。
* **Memory-Hard Hashing：** 使用 `scrypt` 演算法大幅提高暴力破解的成本。
* **Least Privilege：** 建議以非 Root 使用者執行 Flask，並僅開放必要之單一埠口 (5080) 以降低風險。
