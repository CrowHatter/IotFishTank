import json
import os
import threading
import time
import base64
import cv2
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from werkzeug.security import check_password_hash
from flask_apscheduler import APScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
from hardware.motor_ctrl import FishFeeder
from hardware.camera_ctrl import FishCamera, CsiCamera, enumerate_cameras, _PICAMERA2_AVAILABLE
from hardware.light_ctrl import LightRelay
from hardware.water_level import WaterLevelDetector
from hardware.water_sensor import WaterLevelSensor
from hardware.pump_ctrl import PumpRelay, DrainRelay

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

# 佔位符，稍後在 _init_cameras() 時設定
fish_cam = None
fish_cam_b = None

light_relay = LightRelay()
atexit.register(light_relay.cleanup)

water_sensor = WaterLevelSensor()
atexit.register(water_sensor.cleanup)

pump_relay = PumpRelay()
atexit.register(pump_relay.cleanup)

drain_relay = DrainRelay()
atexit.register(drain_relay.cleanup)

_refill_lock = threading.Lock()
_stop_water_event = threading.Event()
MAX_REFILL_SECONDS = 360
DRAIN_SECONDS = 200

# 水位偵測器：參數於 config 載入後再套用（見下方 _init_water_detector）
water_detector = None
def _init_water_detector():
    global water_detector
    if fish_cam is None:
        return
    water_detector = WaterLevelDetector(fish_cam)
    cfg = read_json(CONFIG_FILE).get('water_level_config', {})
    water_detector.roi_x = tuple(cfg['roi_x']) if cfg.get('roi_x') else None
    water_detector.gap_threshold_px = cfg.get('gap_threshold_px', 25)
    water_detector.tape_bottom_ref = cfg.get('tape_bottom_ref')
    water_detector.roi_height_ratio = cfg.get('roi_height_ratio', 0.25)
    water_detector.tape_margin_px = cfg.get('tape_margin_px', 6)
    water_detector.frames = cfg.get('frames', 8)
    water_detector.gray_gamma = cfg.get('gray_gamma', 1.0)
    water_detector.waterline_min_grad = cfg.get('waterline_min_grad', 4.0)
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

# --- 輔助函式：水位偵測 ---
# 調校用：暫存最近擷取的 8 幀，讓使用者能對同一組畫面反覆調參數
_water_frames = []
_water_frames_lock = threading.Lock()

def _write_water_status(result):
    """把偵測結果寫回 device_status。sensor 與 OpenCV 結果獨立存放。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sensor_triggered = result.get('sensor_triggered', False)
    cv_state = result.get('cv_state', 'unknown')
    def _update(cfg):
        ds = dict(cfg["device_status"])
        ds['water_level_state'] = cv_state
        ds['water_level_percent'] = result.get('percent')
        ds['water_level_gap_px'] = result.get('gap_px')
        ds['last_water_level_check'] = now_str
        ds['water_sensor_triggered'] = sensor_triggered
        ds['water_level_alert'] = sensor_triggered or (cv_state == 'low')
        return {**cfg, "device_status": ds}
    safe_update_config(_update)
    if sensor_triggered or cv_state == 'low':
        sensor_str = "感測器：過低" if sensor_triggered else "感測器：正常"
        cv_str = f"視覺：{cv_state} {result.get('percent')}% gap={result.get('gap_px')}px"
        print(f"[{now_str}] ⚠️ 水位警示 {sensor_str}／{cv_str}")

def perform_water_level_check():
    """即時擷取多幀偵測（OpenCV）+ 讀取液位感測器，寫回 device_status，回傳結果 dict。
    兩者結果獨立：cv_state/percent/gap_px 來自 OpenCV，sensor_triggered 來自感測器。"""
    if water_detector is None:
        cv_result = {'cv_state': 'unknown', 'reason': '水位偵測器未初始化',
                     'percent': None, 'gap_px': None}
    else:
        raw = water_detector.detect()
        cv_result = {**raw, 'cv_state': raw.get('state', 'unknown')}

    sensor = water_sensor.state()
    cv_result['sensor_triggered'] = sensor['sensor_triggered']

    _write_water_status(cv_result)
    return cv_result

def _do_refill(source):
    """補水核心邏輯（不含 lock）。呼叫前需已持有 _refill_lock。"""
    if not water_sensor.is_low():
        sensor_state = water_sensor.state()
        def _update_sensor(cfg):
            ds = dict(cfg['device_status'])
            ds['water_sensor_triggered'] = sensor_state['sensor_triggered']
            ds['last_refill_source'] = source
            return {**cfg, 'device_status': ds}
        safe_update_config(_update_sensor)
        print(f"[Refill] 水位正常，無需補水 (source={source})")
        return {'status': 'skipped', 'reason': 'water_ok'}

    start_time = time.time()
    aborted = False
    stopped = False
    print(f"[Refill] 水位過低，開始補水 (source={source})")

    def _set_on(cfg):
        ds = dict(cfg['device_status'])
        ds['is_refilling'] = True
        ds['water_sensor_triggered'] = True
        ds['last_refill_source'] = source
        return {**cfg, 'device_status': ds}
    safe_update_config(_set_on)

    pump_relay.turn_on()

    try:
        while True:
            if _stop_water_event.is_set():
                stopped = True
                print(f"[Refill] ⛔ 收到緊急停止指令")
                break
            elapsed = time.time() - start_time
            if elapsed >= MAX_REFILL_SECONDS:
                aborted = True
                print(f"[Refill] ⚠️ 超時 {MAX_REFILL_SECONDS}s，強制關閉馬達（可能漏水或感測器故障）")
                break
            if not water_sensor.is_low():
                print(f"[Refill] 感測器回報正常，停止補水 (elapsed={elapsed:.1f}s)")
                break
            time.sleep(0.2)
    finally:
        pump_relay.turn_off()

    duration = time.time() - start_time
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    final_low = water_sensor.is_low()

    def _set_done(cfg):
        ds = dict(cfg['device_status'])
        ds['is_refilling'] = False
        ds['last_refill'] = now_str
        ds['last_refill_duration_s'] = round(duration, 1)
        ds['last_refill_source'] = source
        ds['last_refill_aborted'] = aborted or stopped
        ds['water_sensor_triggered'] = final_low
        ds['water_level_alert'] = final_low
        return {**cfg, 'device_status': ds}
    safe_update_config(_set_done)

    if stopped:
        status = 'stopped'
    elif aborted:
        status = 'aborted'
    else:
        status = 'done'
    print(f"[Refill] 完成 status={status}, duration={duration:.1f}s")
    return {'status': status, 'duration_s': round(duration, 1),
            'aborted': aborted or stopped, 'sensor_triggered': final_low}


def perform_refill(source='manual'):
    """補水流程：sensor 確認過低 → 開馬達 → 監測至正常或超時 → 關馬達 → 更新 config。
    防並發：同時只允許一個補水/換水 thread 執行。
    回傳 dict: {status: 'skipped'|'done'|'aborted'|'stopped'|'busy', ...}
    """
    if not _refill_lock.acquire(blocking=False):
        print(f"[Refill] 已在補水/換水中，忽略來自 {source} 的觸發")
        return {'status': 'busy'}
    _stop_water_event.clear()
    try:
        return _do_refill(source)
    except Exception as e:
        print(f"[Refill] 異常：{e}，強制關閉馬達")
        def _set_err(cfg):
            ds = dict(cfg['device_status'])
            ds['is_refilling'] = False
            ds['last_refill_aborted'] = True
            return {**cfg, 'device_status': ds}
        safe_update_config(_set_err)
        raise
    finally:
        _refill_lock.release()


def perform_water_change(source='manual'):
    """換水流程：抽水 DRAIN_SECONDS 秒（可中斷）→ 補水至感測器正常。
    與 perform_refill 共用 _refill_lock，互相鎖住。
    回傳 dict: {status: 'done'|'stopped'|'busy', drain_s, refill_result}
    """
    if not _refill_lock.acquire(blocking=False):
        print(f"[WaterChange] 已在補水/換水中，忽略來自 {source} 的觸發")
        return {'status': 'busy'}
    _stop_water_event.clear()
    try:
        print(f"[WaterChange] 開始換水，抽水 {DRAIN_SECONDS}s (source={source})")
        def _set_drain(cfg):
            ds = dict(cfg['device_status'])
            ds['is_draining'] = True
            return {**cfg, 'device_status': ds}
        safe_update_config(_set_drain)

        drain_relay.turn_on()
        drain_stopped = False
        try:
            # 每 0.2s 檢查一次停止信號，取代單一 sleep(DRAIN_SECONDS)
            deadline = time.time() + DRAIN_SECONDS
            while time.time() < deadline:
                if _stop_water_event.is_set():
                    drain_stopped = True
                    print(f"[WaterChange] ⛔ 收到緊急停止指令，中止抽水")
                    break
                time.sleep(0.2)
        finally:
            drain_relay.turn_off()

        def _clear_drain(cfg):
            ds = dict(cfg['device_status'])
            ds['is_draining'] = False
            return {**cfg, 'device_status': ds}
        safe_update_config(_clear_drain)

        if drain_stopped:
            print(f"[WaterChange] 緊急停止，不進行補水")
            return {'status': 'stopped', 'drain_s': 0, 'refill_result': None}

        # 等待虹吸停止：抽水結束後靜待 180 秒再補水
        print(f"[WaterChange] 抽水完成，等待 180s 讓虹吸停止")
        siphon_deadline = time.time() + 180
        while time.time() < siphon_deadline:
            if _stop_water_event.is_set():
                print(f"[WaterChange] ⛔ 虹吸等待中收到緊急停止指令")
                return {'status': 'stopped', 'drain_s': DRAIN_SECONDS, 'refill_result': None}
            time.sleep(0.2)

        print(f"[WaterChange] 開始補水")
        refill_result = _do_refill(source)
        print(f"[WaterChange] 換水完成 refill_result={refill_result}")
        final_status = 'stopped' if refill_result.get('status') == 'stopped' else 'done'
        return {'status': final_status, 'drain_s': DRAIN_SECONDS, 'refill_result': refill_result}

    except Exception as e:
        print(f"[WaterChange] 異常：{e}，強制關閉所有繼電器")
        drain_relay.turn_off()
        pump_relay.turn_off()
        def _set_err(cfg):
            ds = dict(cfg['device_status'])
            ds['is_draining'] = False
            ds['is_refilling'] = False
            return {**cfg, 'device_status': ds}
        safe_update_config(_set_err)
        raise
    finally:
        _refill_lock.release()

def _capture_water_frames(n):
    frames = []
    if fish_cam is None:
        return frames
    for _ in range(n):
        f = fish_cam.get_raw_frame()
        if f is not None:
            frames.append(f)
    return frames

def _sanitize_water_cfg(raw):
    """從前端送來的 dict 取出可調參數並做型別轉換，未知/無效值忽略。"""
    out = {}
    if 'roi_x' in raw:
        v = raw['roi_x']
        if v in (None, '', [], 'null'):
            out['roi_x'] = None
        elif isinstance(v, (list, tuple)) and len(v) == 2:
            x1, x2 = int(v[0]), int(v[1])
            out['roi_x'] = [min(x1, x2), max(x1, x2)]
    if 'gap_threshold_px' in raw:
        out['gap_threshold_px'] = max(1, int(raw['gap_threshold_px']))
    if 'roi_height_ratio' in raw:
        out['roi_height_ratio'] = float(min(0.9, max(0.05, float(raw['roi_height_ratio']))))
    if 'tape_margin_px' in raw:
        out['tape_margin_px'] = max(0, int(raw['tape_margin_px']))
    if 'frames' in raw:
        out['frames'] = min(30, max(1, int(raw['frames'])))
    if 'gray_gamma' in raw:
        out['gray_gamma'] = float(min(3.0, max(0.2, float(raw['gray_gamma']))))
    if 'waterline_min_grad' in raw:
        out['waterline_min_grad'] = float(min(50.0, max(0.5, float(raw['waterline_min_grad']))))
    return out

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
def check_schedule(source='cron'):
    with app.app_context():
        with file_lock:
            config = read_json(CONFIG_FILE)

        now = datetime.now()
        now_day = int(now.strftime("%w"))
        if source == 'cron':
            # 對齊到 10 分鐘排程槽：即使任務因 worker 忙碌被延後執行（甚至跨過整分鐘），
            # 仍能對上該時槽的排程，避免精確比對因延遲而整個錯過。
            slot = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
            now_time = slot.strftime("%H:%M")
        else:
            # 手動存檔觸發：維持精確比對，避免存檔當下誤觸發鄰近時槽的排程。
            now_time = now.strftime("%H:%M")
        print(f"[{now.strftime('%H:%M:%S')}] check_schedule 觸發 (source={source}, 比對時槽={now_time})")

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
                    action = item.get('action', 'refill')
                    if action == 'refill':
                        print(f"[{now_time}] 觸發自動補水排程")
                        threading.Thread(target=perform_refill, args=('cron',), daemon=True).start()
                    else:
                        print(f"[{now_time}] 觸發自動換水排程")
                        threading.Thread(target=perform_water_change, args=('cron',), daemon=True).start()
                    break

        light_schedules = config.get('auto_light', [])
        for item in light_schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    target = item.get('action', 'on')
                    current = config['device_status'].get('light', 'off')
                    light_relay.set_state(current, target)
                    safe_update_config(lambda cfg, t=target: {
                        **cfg,
                        "device_status": {**cfg["device_status"], "light": t}
                    })
                    print(f"[{now_time}] 自動燈光排程：{target}")
                    break

        water_level_schedules = config.get('auto_water_level', [])
        for item in water_level_schedules:
            if item.get('enabled') and item.get('time') == now_time:
                if now_day in item.get('days', []):
                    res = perform_water_level_check()
                    print(f"[{now_time}] 自動水位偵測：{res.get('state')} "
                          f"({res.get('percent')}%)")
                    break

scheduler.add_job(
    id='feeder_cron_job',
    func=check_schedule,
    trigger=CronTrigger(minute='0,10,20,30,40,50'),
    # worker 忙於串流時任務可能延後啟動；放寬容錯時間並合併積壓的觸發，
    # 確保 10 分鐘排程槽內一定會被執行一次（預設僅 1 秒，極易被跳過）。
    misfire_grace_time=290,
    coalesce=True,
    replace_existing=True,
)
scheduler.init_app(app)
scheduler.start()

# --- 影像串流產生器 ---
# 按需串流：每台攝影機獨立計數目前連線中的觀看者。沒有觀看者時 generator
# 不會被迭代（Flask MJPEG response 僅在瀏覽器連著 <img> 時消費），擷取迴圈
# 自然停止；計數僅用於記錄與驗證「無連線→不擷取」。
_viewers = {'A': 0, 'B': 0}
_viewers_lock = threading.Lock()

def gen_frames(camera=None, cam_id='A'):
    """回傳指定攝影機的 MJPEG 幀串流。camera 為 None 時用 fish_cam。"""
    if camera is None:
        camera = fish_cam
    with _viewers_lock:
        _viewers[cam_id] += 1
        print(f"[Stream {cam_id}] 觀看者連線，目前 {_viewers[cam_id]} 人")
    try:
        last = 0.0
        while True:
            fps = FPS_CYCLE[stream_fps_idx]
            interval = 1.0 / fps
            now = time.time()
            if now - last < interval:
                time.sleep(0.005)
                continue
            frame, content_type = camera.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            last = time.time()
            yield (b'--frame\r\nContent-Type: ' + content_type.encode() + b'\r\n\r\n' + frame + b'\r\n\r\n')
    finally:
        with _viewers_lock:
            _viewers[cam_id] -= 1
            print(f"[Stream {cam_id}] 觀看者離線，目前 {_viewers[cam_id]} 人"
                  f"{'（迴圈停止，不再擷取）' if _viewers[cam_id] == 0 else ''}")

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
        "auto_light": [],
        "auto_water_level": [],
        "water_level_config": {
            "roi_x": None, "gap_threshold_px": 25, "tape_bottom_ref": None,
            "roi_height_ratio": 0.25, "tape_margin_px": 6, "frames": 8,
            "gray_gamma": 1.0, "waterline_min_grad": 4.0
        },
        "device_status": {
            "light": "off", "last_fed_A": "Never", "last_fed_B": "Never",
            "water_level_state": "unknown", "water_level_percent": None,
            "water_sensor_triggered": False,
            "last_water_level_check": "Never"
        }
    }
    write_json(CONFIG_FILE, default_config)

# 攝影機分配邏輯：
#   Camera A → CSI (OV5647) via picamera2，若 picamera2 不可用則 fallback 到 V4L2
#   Camera B → USB V4L2，用 by-path 綁定固定 port
def _init_cameras():
    global fish_cam, fish_cam_b

    # --- Camera A: CSI ---
    if _PICAMERA2_AVAILABLE:
        try:
            fish_cam = CsiCamera()
            fish_cam.set_output((1280, 720), 80)
            print("[Camera Init] 攝影機 A (CSI/OV5647) 初始化成功")
        except Exception as e:
            print(f"[Camera Init] 攝影機 A (CSI) 初始化失敗，fallback 到 V4L2: {e}")
            fish_cam = None
    else:
        print("[Camera Init] picamera2 不可用，攝影機 A 將嘗試 V4L2 fallback")
        fish_cam = None

    # --- Camera B: USB V4L2，by-path 綁定 ---
    try:
        cameras = enumerate_cameras()
    except Exception as e:
        print(f"[Camera Init] enumerate_cameras 失敗: {e}")
        cameras = []

    with file_lock:
        config = read_json(CONFIG_FILE)

    camera_config = config.get('camera_config', {})
    b_index = None

    if not camera_config.get('B'):
        # 首次初始化：把第一台找到的 USB 攝影機分配給 B
        if cameras:
            b_index = cameras[0]['index']
            camera_config['B'] = cameras[0]['by_path'] or f"video{cameras[0]['index']}"
            try:
                safe_update_config(lambda cfg: {**cfg, "camera_config": camera_config})
                print(f"[Camera Init] 攝影機 B 首次分配: index={b_index}, by_path={camera_config['B']}")
            except Exception as e:
                print(f"[Camera Init] 保存 camera_config 失敗: {e}")
    else:
        by_path = camera_config['B']
        for cam in cameras:
            if cam['by_path'] == by_path or (cam['by_path'] is None and by_path == f"video{cam['index']}"):
                b_index = cam['index']
                break
        if b_index is None:
            print(f"[Camera Init] 無法找到攝影機 B (by_path={by_path})")

    if b_index is not None:
        try:
            fish_cam_b = FishCamera(device_index=b_index)
            fish_cam_b.set_output((1280, 720), 80)
            print(f"[Camera Init] 攝影機 B (USB) 初始化成功 (index={b_index})")
        except Exception as e:
            print(f"[Camera Init] 攝影機 B 初始化失敗: {e}")
            fish_cam_b = None

    # 讀取各鏡頭的校準亮度目標（如果有的話）
    cfg = read_json(CONFIG_FILE)
    if fish_cam:
        t = cfg.get('auto_brightness_target_A')
        if t is not None:
            fish_cam.set_auto_target(t)
            print(f"[Camera Init] 攝影機 A 亮度目標已載入: {t}")
    if fish_cam_b:
        t = cfg.get('auto_brightness_target_B')
        if t is not None:
            fish_cam_b.set_auto_target(t)
            print(f"[Camera Init] 攝影機 B 亮度目標已載入: {t}")

# 確保既有 config.json 也有水位設定欄位（舊檔可能缺少），缺則補上預設值
def _ensure_water_config():
    defaults = {
        "roi_x": None, "gap_threshold_px": 25, "tape_bottom_ref": None,
        "roi_height_ratio": 0.25, "tape_margin_px": 6, "frames": 8,
        "gray_gamma": 1.0, "waterline_min_grad": 4.0
    }
    def _update(cfg):
        wlc = {**defaults, **cfg.get('water_level_config', {})}
        ds = dict(cfg.get('device_status', {}))
        ds.setdefault('water_level_state', 'unknown')
        ds.setdefault('water_level_percent', None)
        ds.setdefault('water_sensor_triggered', False)
        ds.setdefault('last_water_level_check', 'Never')
        ds.setdefault('is_draining', False)
        ds.setdefault('is_refilling', False)
        ds.setdefault('last_refill', 'Never')
        ds.setdefault('last_refill_duration_s', None)
        ds.setdefault('last_refill_source', None)
        ds.setdefault('last_refill_aborted', False)
        return {**cfg, "water_level_config": wlc, "device_status": ds}
    safe_update_config(_update)

_ensure_water_config()
# 初始化攝影機
_init_cameras()
# 套用 config 中的水位偵測參數
_init_water_detector()

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
    if fish_cam is None:
        return "攝影機 A 未連接", 404
    return Response(gen_frames(fish_cam, 'A'),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/video_feed_b')
@login_required
def video_feed_b():
    if fish_cam_b is None:
        return "攝影機 B 未連接", 404
    return Response(gen_frames(fish_cam_b, 'B'),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

def _cam_by_target(target):
    """target = 'A'|'B' → 對應的 FishCamera 實例（或 None）。"""
    return fish_cam if target == 'A' else fish_cam_b if target == 'B' else None

def _cam_state(cam):
    if cam is None:
        return {"available": False, "auto": True, "step": None, "steps": 0}
    st = cam.exposure_state()
    return {"available": True, **st}

@app.route('/api/cameras', methods=['GET'])
@login_required
def get_cameras():
    return jsonify({
        "A": _cam_state(fish_cam),
        "B": _cam_state(fish_cam_b)
    })

@app.route('/api/camera/reset', methods=['POST'])
@login_required
def camera_reset():
    target = (request.json or {}).get('target', 'A')
    cam = _cam_by_target(target)
    if cam is None:
        return jsonify({"status": "error", "reason": f"攝影機 {target} 未連接"}), 404
    ok = cam.reset()
    return jsonify({"status": "success" if ok else "error", "target": target})

@app.route('/api/camera/exposure', methods=['POST'])
@login_required
def camera_exposure():
    body = request.json or {}
    target = body.get('target', 'A')
    cam = _cam_by_target(target)
    if cam is None:
        return jsonify({"status": "error", "reason": f"攝影機 {target} 未連接"}), 404
    # 三種操作：auto(回自動) / delta(±1 步階) / value(指定步階)
    if body.get('auto'):
        ok = cam.set_exposure(None)
    elif 'delta' in body:
        ok = cam.nudge_exposure(int(body['delta']))
    else:
        ok = cam.set_exposure(body.get('value'))
    return jsonify({"status": "success" if ok else "error",
                    "target": target, **cam.exposure_state()})

@app.route('/api/camera/exposure/calibrate', methods=['POST'])
@login_required
def camera_exposure_calibrate():
    body = request.json or {}
    target = body.get('target', 'A')
    cam = _cam_by_target(target)
    if cam is None:
        return jsonify({"status": "error", "reason": f"攝影機 {target} 未連接"}), 404
    brightness = cam.measure_brightness()
    if brightness is None:
        return jsonify({"status": "error", "reason": "無法取樣"}), 500
    cam.set_auto_target(brightness)
    key = f"auto_brightness_target_{target}"
    safe_update_config(lambda cfg: {**cfg, key: round(brightness, 1)})
    print(f"[Camera Calibrate] 攝影機 {target} 亮度目標設定為 {brightness:.1f}")
    return jsonify({"status": "success", "target": target,
                    "brightness": round(brightness, 1), **cam.exposure_state()})

@app.route('/api/stream_setting', methods=['POST'])
@login_required
def stream_setting():
    global stream_res_idx, stream_fps_idx
    if fish_cam is None:
        return jsonify({'error': '攝影機未連接'}), 503
    setting_type = request.json.get('type')
    with stream_lock:
        if setting_type == 'res':
            stream_res_idx = (stream_res_idx + 1) % len(RES_CYCLE)
        elif setting_type == 'fps':
            stream_fps_idx = (stream_fps_idx + 1) % len(FPS_CYCLE)
        else:
            return jsonify({'error': 'invalid type'}), 400
        # 解析度/幀數為 A、B 共用設定，兩台都套用
        fish_cam.set_output(RES_CYCLE[stream_res_idx], 80)
        if fish_cam_b is not None:
            fish_cam_b.set_output(RES_CYCLE[stream_res_idx], 80)
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
        check_schedule(source='manual')
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
        with file_lock:
            cfg = read_json(CONFIG_FILE)
            current_status = cfg["device_status"].get("light", "off")
            light_relay.set_state(current_status, new_status)
        safe_update_config(lambda cfg: {
            **cfg,
            "device_status": {**cfg["device_status"], "light": new_status}
        })
        return jsonify({"status": "success"})
    elif action == 'check_water_level':
        result = perform_water_level_check()
        return jsonify({"status": "success", "result": result})
    elif action == 'refill':
        result = perform_refill(source='manual')
        return jsonify({"status": "success", "result": result})
    elif action == 'water_change':
        if _refill_lock.locked():
            return jsonify({"status": "busy"})
        threading.Thread(target=perform_water_change, args=('manual',), daemon=True).start()
        return jsonify({"status": "accepted"})
    elif action == 'stop_water':
        _stop_water_event.set()
        drain_relay.turn_off()
        pump_relay.turn_off()
        print(f"[StopWater] 緊急停止指令送出")
        return jsonify({"status": "stopping"})
    return jsonify({"status": "received"})

@app.route('/api/water_level/tune', methods=['POST'])
@login_required
def water_level_tune():
    """互動式調校：
    - body.config 存在 → 寫入 water_level_config 並即時套用
    - body.recapture 為真，或目前無暫存幀 → 重新擷取 N 幀並暫存
    - 否則沿用暫存的同一組幀重新分析
    回傳：標註後影像(base64 JPEG)、偵測結果、目前 config。"""
    global _water_frames
    if water_detector is None or fish_cam is None:
        return jsonify({"status": "error", "reason": "水位偵測器未初始化"}), 503

    body = request.json or {}

    new_cfg = body.get('config')
    if new_cfg:
        clean = _sanitize_water_cfg(new_cfg)
        def _update(cfg):
            wlc = dict(cfg.get('water_level_config', {}))
            wlc.update(clean)
            return {**cfg, "water_level_config": wlc}
        safe_update_config(_update)
        _init_water_detector()

    with _water_frames_lock:
        if body.get('recapture') or not _water_frames:
            _water_frames = _capture_water_frames(water_detector.frames)
        frames = list(_water_frames)

    if not frames:
        return jsonify({"status": "error", "reason": "no_frame"}), 503

    result, color_img, gray_img = water_detector.analyze_and_render(frames)

    def _enc(img):
        if img is None:
            return None
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode('ascii') if ok else None

    tune_result = {**result, 'cv_state': result.get('state', 'unknown'),
                   'sensor_triggered': water_sensor.state()['sensor_triggered']}
    _write_water_status(tune_result)
    cfg = read_json(CONFIG_FILE).get('water_level_config', {})
    return jsonify({"status": "success", "result": tune_result, "config": cfg,
                    "image": _enc(color_img), "gray_image": _enc(gray_img)})

@app.route('/api/water_level/calibrate', methods=['POST'])
@login_required
def water_level_calibrate():
    if water_detector is None:
        return jsonify({"status": "error", "reason": "水位偵測器未初始化"}), 503
    cal = water_detector.calibrate()
    if not cal.get('ok'):
        return jsonify({"status": "error", "reason": cal.get('reason')}), 400
    # 寫入基準到 water_level_config，並即時套用
    def _update(cfg):
        wlc = dict(cfg.get('water_level_config', {}))
        wlc['tape_bottom_ref'] = cal['tape_bottom_ref']
        return {**cfg, "water_level_config": wlc}
    safe_update_config(_update)
    water_detector.tape_bottom_ref = cal['tape_bottom_ref']
    return jsonify({"status": "success", "calibration": cal})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5080, debug=False, threaded=True)