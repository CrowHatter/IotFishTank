import json
import os
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CONFIG_FILE = 'config.json'

# 初始化 config.json (如果不存在)
if not os.path.exists(CONFIG_FILE):
    default_config = {"feed": [], "water": []}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(default_config, f)

def read_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def write_config(data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@app.route('/')
def index():
    # 渲染首頁
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(read_config())

@app.route('/api/config', methods=['POST'])
def update_config():
    new_config = request.json
    write_config(new_config)
    return jsonify({"status": "success"})

@app.route('/api/action', methods=['POST'])
def trigger_action():
    action = request.json.get('action')
    # 這裡未來會加入 RPi.GPIO 控制馬達或燈光的程式碼
    print(f"執行動作: {action}")
    return jsonify({"status": "received", "action": action})

if __name__ == '__main__':
    # 讓同區域網路的設備都能連線 (host='0.0.0.0')
    app.run(host='0.0.0.0', port=5000, debug=True)