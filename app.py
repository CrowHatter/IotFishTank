import json
import os
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import check_password_hash
from flask_apscheduler import APScheduler
from hardware.motor_ctrl import FishFeeder

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fish-tank-secret-key-99b3awiet456qr4ojy@@##%&*%KGrkyorlwerk84*/*+59+r5*8giJ*J($)#' 

CONFIG_FILE = 'config.json'
SECRET_FILE = 'config_secret.json'
BAN_FILE = 'banned_ips.json'

# 初始化硬體與排程器
feeder = FishFeeder()
scheduler = APScheduler()
# 建立全域檔案鎖，確保多線程下檔案讀寫安全
file_lock = threading.Lock()

# --- 基礎檔案處理 ---
def read_json(filename):
    if not os.path.exists(filename): return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def safe_update_config(update_func):
    """
    安全更新設定檔的輔助函式 (原子操作)
    update_func: 傳入一個接收 dict 並回傳 dict 的 lambda 或函式
    """
    with file_lock:
        config = read_json(CONFIG_FILE)
        new_config = update_func(config)
        write_json(CONFIG_FILE, new_config)
    return new_config

def read_bans():
    if not os.path.exists(BAN_FILE): return {}
    with open(BAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for ip in data:
            unban_str = data[ip].get('unban_time')
            if unban_str == "max": data[ip]['unban_time'] = datetime.max
            elif unban_str: data[ip]['unban_time'] = datetime.fromisoformat(unban_str)
            else: data[ip]['unban_time'] = None
        return data

def write_bans(data):
    serializable = {}
    for ip, record in data.items():
        serializable[ip] = record.copy()
        unban_val = record.get('unban_time')
        if unban_val == datetime.max: serializable[ip]['unban_time'] = "max"
        elif isinstance(unban_val, datetime): serializable[ip]['unban_time'] = unban_val.isoformat()
    with open(BAN_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, indent=4)

def is_ip_banned(ip):
    failed_attempts = read_bans()
    if ip in failed_attempts:
        record = failed_attempts[ip]
        if record['unban_time'] and datetime.now() < record['unban_time']:
            return True, record['unban_time']
    return False, None

# --- 排程背景任務 ---
def check_schedule():
    """每 10 分鐘檢查 config.json 決定是否執行排程動作"""
    with app.app_context():
        # 讀取當前設定 (讀取也需加鎖確保資料完整)
        with file_lock:
            config = read_json(CONFIG_FILE)
        
        now = datetime.now()
        rounded_minute = (now.minute // 10) * 10
        now_time = now.replace(minute=rounded_minute, second=0, microsecond=0).strftime("%H:%M")
        now_day = int(now.strftime("%w"))
        
        # 1. 檢查自動餵食
        schedules = config.get('auto_feed', [])
        for item in schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    print(f"[{now.strftime('%H:%M:%S')}] 觸發排程餵食 (週{now_day})")
                    # feed_sequence 內部有 is_busy 鎖，若手動餵食中，此處會回傳 False
                    if feeder.feed_sequence():
                        # 使用 safe_update_config 確保 last_fed 寫入時不會覆蓋掉同時發生的燈光切換
                        safe_update_config(lambda cfg: {
                            **cfg, 
                            "device_status": {**cfg["device_status"], "last_fed": now.strftime("%Y-%m-%d %H:%M")}
                        })

        # 2. 檢查自動換水 (預留區)
        water_schedules = config.get('auto_water_change', [])
        for item in water_schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    print(f"[{now_time}] 觸發自動換水排程 (待實作)")

# 設定排程間隔為 600 秒 (10 分鐘)
scheduler.add_job(id='feeder_job', func=check_schedule, trigger='interval', seconds=600)
scheduler.init_app(app)
scheduler.start()

# --- 登入管理 ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id): self.id = id

@login_manager.user_loader
def load_user(user_id):
    secrets = read_json(SECRET_FILE)
    if user_id in secrets.get('users', {}): return User(user_id)
    return None

# 初始化設定檔結構
if not os.path.exists(CONFIG_FILE):
    default_config = {
        "auto_feed": [],
        "auto_water_change": [],
        "device_status": { "light": "off", "last_fed": "Never" }
    }
    write_json(CONFIG_FILE, default_config)

# --- 路由與 API ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    banned, unban_time = is_ip_banned(ip)
    if banned:
        if unban_time == datetime.max: return "您的 IP 已被永久封鎖。", 403
        wait_sec = int((unban_time - datetime.now()).total_seconds())
        flash(f"嘗試次數過多，請在 {wait_sec} 秒後再試。")
        return render_template('login.html')

    if request.method == 'POST':
        username, password = request.form.get('username'), request.form.get('password')
        secrets = read_json(SECRET_FILE)
        hashed_password = secrets.get('users', {}).get(username)
        if hashed_password and check_password_hash(hashed_password, password):
            all_bans = read_bans()
            if ip in all_bans:
                del all_bans[ip]
                write_bans(all_bans)
            login_user(User(username))
            return redirect(url_for('index'))
        
        all_bans = read_bans()
        now = datetime.now()
        if ip not in all_bans: all_bans[ip] = {'count': 1, 'unban_time': None}
        else: all_bans[ip]['count'] += 1
        count = all_bans[ip]['count']
        if count >= 15: all_bans[ip]['unban_time'] = datetime.max
        elif count >= 10: all_bans[ip]['unban_time'] = now + timedelta(minutes=10)
        elif count >= 5: all_bans[ip]['unban_time'] = now + timedelta(minutes=1)
        write_bans(all_bans)
        flash('帳號或密碼錯誤！')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    with file_lock:
        return jsonify(read_json(CONFIG_FILE))

@app.route('/api/config', methods=['POST'])
@login_required
def update_config():
    with file_lock:
        write_json(CONFIG_FILE, request.json)
    print("偵測到設定變更，立即觸發同步檢查...")
    check_schedule()
    return jsonify({"status": "success"})

@app.route('/api/action', methods=['POST'])
@login_required
def trigger_action():
    action = request.json.get('action')
    
    if action == 'feed':
        # 執行馬達動作 (不佔用 file_lock，以免阻塞其他 API 讀取)
        success = feeder.feed_sequence()
        if success:
            # 動作成功後，安全更新最後餵食時間
            safe_update_config(lambda cfg: {
                **cfg, 
                "device_status": {**cfg["device_status"], "last_fed": datetime.now().strftime("%Y-%m-%d %H:%M")}
            })
        return jsonify({"status": "success" if success else "busy"})
    
    elif action in ['light_on', 'light_off']:
        new_status = "on" if action == 'light_on' else "off"
        # 安全更新燈光狀態
        safe_update_config(lambda cfg: {
            **cfg, 
            "device_status": {**cfg["device_status"], "light": new_status}
        })
        return jsonify({"status": "success"})
        
    return jsonify({"status": "received"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5080, debug=False)