import json
import os
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import check_password_hash
from flask_apscheduler import APScheduler
from apscheduler.triggers.cron import CronTrigger
from hardware.motor_ctrl import FishFeeder
from hardware.camera_ctrl import FishCamera

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fish-tank-secret-key-99b3awiet456qr4ojy@@##%&*%KGrkyorlwerk84*/*+59+r5*8giJ*J($)#' 

CONFIG_FILE = 'config.json'
SECRET_FILE = 'config_secret.json'
BAN_FILE = 'banned_ips.json'

# --- 1. 初始化雙餵食器與鏡頭 ---
# 餵食器 A (原本腳位)
feeder_a = FishFeeder(pins=[17, 18, 27, 22])
# 餵食器 B (新腳位，請根據實體接線修改)
feeder_b = FishFeeder(pins=[23, 24, 25, 8])

fish_cam = FishCamera() 
scheduler = APScheduler()
file_lock = threading.Lock()

# --- 2. 輔助函式：同步餵食邏輯 ---
def perform_dual_feed():
    """使用執行緒讓兩台餵食器同時啟動"""
    # 檢查是否任一馬達正在忙碌
    if feeder_a.is_busy or feeder_b.is_busy:
        return False
    
    # 定義內部執行函式
    def thread_feed(f): f.feed_sequence()
    
    # 建立並啟動執行緒
    t1 = threading.Thread(target=thread_feed, args=(feeder_a,))
    t2 = threading.Thread(target=thread_feed, args=(feeder_b,))
    t1.start()
    t2.start()
    
    # 更新最後餵食時間紀錄
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    safe_update_config(lambda cfg: {
        **cfg, 
        "device_status": {**cfg["device_status"], "last_fed": now_str}
    })
    return True

# --- 基礎檔案處理 ---
def read_json(filename):
    if not os.path.exists(filename): return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def safe_update_config(update_func):
    with file_lock:
        config = read_json(CONFIG_FILE)
        new_config = update_func(config)
        write_json(CONFIG_FILE, new_config)
    return new_config

# --- 登入安全性處理 (IP Ban) ---
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
    with app.app_context():
        with file_lock:
            config = read_json(CONFIG_FILE)
        
        now = datetime.now()
        now_time = now.strftime("%H:%M")
        now_day = int(now.strftime("%w"))
        
        schedules = config.get('auto_feed', [])
        for item in schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    # 修改：呼叫同步餵食函式
                    if perform_dual_feed():
                        print(f"[{now.strftime('%H:%M:%S')}] 自動雙投餵執行成功")
                    break

        water_schedules = config.get('auto_water_change', [])
        for item in water_schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    print(f"[{now_time}] 觸發自動換水排程 (待實作)")

scheduler.add_job(
    id='feeder_cron_job', 
    func=check_schedule, 
    trigger=CronTrigger(minute='0,10,20,30,40,50')
)
scheduler.init_app(app)
scheduler.start()

# --- 影像串流產生器 ---
def gen_frames():
    while True:
        frame = fish_cam.get_frame()
        if frame is None:
            time.sleep(0.1)
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

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

@app.route('/video_feed')
@login_required
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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
    # 修改：不忙碌時檢查排程，確保兩台都沒在忙
    if not feeder_a.is_busy and not feeder_b.is_busy:
        check_schedule()
    return jsonify({"status": "success"})

@app.route('/api/action', methods=['POST'])
@login_required
def trigger_action():
    action = request.json.get('action')
    if action == 'feed':
        # 修改：呼叫同步餵食函式
        success = perform_dual_feed()
        return jsonify({"status": "success" if success else "busy"})
    elif action in ['light_on', 'light_off']:
        new_status = "on" if action == 'light_on' else "off"
        safe_update_config(lambda cfg: {
            **cfg, 
            "device_status": {**cfg["device_status"], "light": new_status}
        })
        return jsonify({"status": "success"})
    return jsonify({"status": "received"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5080, debug=False, threaded=True)