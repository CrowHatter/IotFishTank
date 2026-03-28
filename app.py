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

# --- 串流品質設定 ---
RES_CYCLE  = [None, (1280, 720), (854, 480), (640, 360)]  # None = 原生 1920x1080
FPS_CYCLE  = [30, 20, 10]
RES_LABELS = ['1080p', '720p', '480p', '360p']
FPS_LABELS = ['30fps', '20fps', '10fps']
stream_res_idx = 1   # 預設 720p
stream_fps_idx = 1   # 預設 20fps
stream_lock = threading.Lock()
fish_cam.set_output((1280, 720), 80)

# --- 2. 輔助函式：餵食邏輯 ---
def perform_feed(target='both'):
    """餵食指定目標並等待完成: target = 'A' | 'B' | 'both'"""
    feeders = []
    if target in ('A', 'both'):
        feeders.append(feeder_a)
    if target in ('B', 'both'):
        feeders.append(feeder_b)

    # 任一目標馬達忙碌則拒絕
    if any(f.is_busy for f in feeders):
        return False

    # 啟動執行緒並等待完成（join 確保 HTTP 回應與實際完成同步）
    threads = [threading.Thread(target=f.feed_sequence) for f in feeders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 更新最後餵食時間紀錄（A/B 獨立）
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    def _update(cfg):
        ds = dict(cfg["device_status"])
        if target in ('A', 'both'):
            ds['last_fed_A'] = now_str
        if target in ('B', 'both'):
            ds['last_fed_B'] = now_str
        return {**cfg, "device_status": ds}
    safe_update_config(_update)
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
                    if perform_feed('both'):
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
    last = 0.0
    while True:
        fps = FPS_CYCLE[stream_fps_idx]
        interval = 1.0 / fps
        now = time.time()
        if now - last < interval:
            time.sleep(0.005)
            continue
        frame = fish_cam.get_frame()
        if frame is None:
            time.sleep(0.1)
            continue
        last = time.time()
        yield (b'--frame\r\n'
               b'Content-Type: image/webp\r\n\r\n' + frame + b'\r\n\r\n')

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
        "device_status": { "light": "off", "last_fed_A": "Never", "last_fed_B": "Never" }
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

@app.route('/api/stream_setting', methods=['POST'])
@login_required
def stream_setting():
    global stream_res_idx, stream_fps_idx
    setting_type = request.json.get('type')
    with stream_lock:
        if setting_type == 'res':
            stream_res_idx = (stream_res_idx + 1) % len(RES_CYCLE)
        elif setting_type == 'fps':
            stream_fps_idx = (stream_fps_idx + 1) % len(FPS_CYCLE)
        else:
            return jsonify({'error': 'invalid type'}), 400
        fish_cam.set_output(RES_CYCLE[stream_res_idx], 80)
    return jsonify({'res': RES_LABELS[stream_res_idx], 'fps': FPS_LABELS[stream_fps_idx]})

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
        target = request.json.get('target', 'both')
        success = perform_feed(target)
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