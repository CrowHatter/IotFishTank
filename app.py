import json
import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fish-tank-secret-key-99b3awiet456qr4ojy@@##%&*%KGrkyorlwerk84*/*+59+r5*8giJ*J($)#' 

CONFIG_FILE = 'config.json'
SECRET_FILE = 'config_secret.json'
BAN_FILE = 'banned_ips.json'

# --- 1. 封鎖資料持久化邏輯 (Ban Persistence) ---

def read_bans():
    if not os.path.exists(BAN_FILE): return {}
    with open(BAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        # 將字串格式的時間轉回 datetime 物件
        for ip in data:
            unban_str = data[ip].get('unban_time')
            if unban_str == "max":
                data[ip]['unban_time'] = datetime.max
            elif unban_str:
                data[ip]['unban_time'] = datetime.fromisoformat(unban_str)
            else:
                data[ip]['unban_time'] = None
        return data

def write_bans(data):
    # 轉換 datetime 為字串以便存入 JSON
    serializable = {}
    for ip, record in data.items():
        serializable[ip] = record.copy()
        unban_val = record.get('unban_time')
        if unban_val == datetime.max:
            serializable[ip]['unban_time'] = "max"
        elif isinstance(unban_val, datetime):
            serializable[ip]['unban_time'] = unban_val.isoformat()
    
    with open(BAN_FILE, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, indent=4)

def is_ip_banned(ip):
    failed_attempts = read_bans()
    if ip in failed_attempts:
        record = failed_attempts[ip]
        if record['unban_time'] and datetime.now() < record['unban_time']:
            return True, record['unban_time']
    return False, None

# --- 2. 基礎檔案與登入設定 ---

def read_json(filename):
    if not os.path.exists(filename): return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    secrets = read_json(SECRET_FILE)
    if user_id in secrets.get('users', {}):
        return User(user_id)
    return None

if not os.path.exists(CONFIG_FILE):
    write_json(CONFIG_FILE, {"feed": [], "water": []})

# --- 3. 路由邏輯 ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr
    banned, unban_time = is_ip_banned(ip)
    
    if banned:
        if unban_time == datetime.max:
            return "您的 IP 已被永久封鎖。", 403
        wait_sec = int((unban_time - datetime.now()).total_seconds())
        flash(f"嘗試次數過多，請在 {wait_sec} 秒後再試。")
        return render_template('login.html')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        secrets = read_json(SECRET_FILE)
        hashed_password = secrets.get('users', {}).get(username)
        
        if hashed_password and check_password_hash(hashed_password, password):
            # 登入成功：清除該 IP 紀錄
            all_bans = read_bans()
            if ip in all_bans:
                del all_bans[ip]
                write_bans(all_bans)
            login_user(User(username))
            return redirect(url_for('index'))
        
        # 登入失敗：更新紀錄並存檔
        all_bans = read_bans()
        now = datetime.now()
        if ip not in all_bans:
            all_bans[ip] = {'count': 1, 'unban_time': None}
        else:
            all_bans[ip]['count'] += 1

        count = all_bans[ip]['count']
        if count >= 15:
            all_bans[ip]['unban_time'] = datetime.max
        elif count >= 10:
            all_bans[ip]['unban_time'] = now + timedelta(minutes=10)
        elif count >= 5:
            all_bans[ip]['unban_time'] = now + timedelta(minutes=1)
        
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

# --- API Endpoints ---
@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    return jsonify(read_json(CONFIG_FILE))

@app.route('/api/config', methods=['POST'])
@login_required
def update_config():
    write_json(CONFIG_FILE, request.json)
    return jsonify({"status": "success"})

@app.route('/api/action', methods=['POST'])
@login_required
def trigger_action():
    print(f"執行動作: {request.json.get('action')}")
    return jsonify({"status": "received"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5080, debug=True)