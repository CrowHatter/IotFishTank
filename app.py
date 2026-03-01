import json
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# SECRET_KEY 已根據你的要求更新為長隨機字串
app.config['SECRET_KEY'] = 'fish-tank-secret-key-99b3awiet456qr4ojy@@##%&*%KGrkyorlwerk84*/*+59+r5*8giJ*J($)#' 

CONFIG_FILE = 'config.json'
SECRET_FILE = 'config_secret.json'

# --- 1. 檔案讀寫邏輯 (File I/O) ---

def read_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 2. 登入管理設定 (Login Management) ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    # 從 Secret 檔案確認使用者是否存在
    secrets = read_json(SECRET_FILE)
    if user_id in secrets.get('users', {}):
        return User(user_id)
    return None

# --- 3. 初始化 Config 檔案 ---
if not os.path.exists(CONFIG_FILE):
    write_json(CONFIG_FILE, {"feed": [], "water": []})

# --- 4. 路由與驗證 (Routes & Auth) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 從 config_secret.json 讀取使用者資料
        secrets = read_json(SECRET_FILE)
        hashed_password = secrets.get('users', {}).get(username)
        
        # 驗證帳號是否存在且雜湊值是否正確
        if hashed_password and check_password_hash(hashed_password, password):
            user = User(username)
            login_user(user)
            return redirect(url_for('index'))
        
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

# --- 5. API 路由 (API Endpoints) ---

@app.route('/api/config', methods=['GET'])
@login_required
def get_config():
    return jsonify(read_json(CONFIG_FILE))

@app.route('/api/config', methods=['POST'])
@login_required
def update_config():
    new_config = request.json
    write_json(CONFIG_FILE, new_config)
    return jsonify({"status": "success"})

@app.route('/api/action', methods=['POST'])
@login_required
def trigger_action():
    action = request.json.get('action')
    # 這裡未來會加入 RPi.GPIO 控制硬體的代碼
    print(f"收到指令並執行: {action}")
    return jsonify({"status": "received", "action": action})

if __name__ == '__main__':
    # 保持使用 5080 Port
    app.run(host='0.0.0.0', port=5080, debug=True)