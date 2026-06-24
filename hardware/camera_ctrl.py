import cv2
import math
import time
import os
import threading
import subprocess

def enumerate_cameras():
    cameras = []
    for i in range(10):
        try:
            cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    by_path = _get_device_by_path(i)
                    cameras.append({"index": i, "by_path": by_path})
                cap.release()
        except Exception as e:
            continue
    return cameras

def _get_device_by_path(index):
    try:
        for entry in os.listdir('/dev/v4l/by-path'):
            link_path = f'/dev/v4l/by-path/{entry}'
            if os.path.islink(link_path):
                target = os.path.realpath(link_path)
                if target == f'/dev/video{index}':
                    return link_path
    except Exception:
        pass
    return None

def _query_exposure_range(index):
    """用 v4l2-ctl 查詢 exposure_time_absolute 的真實 min/max/step/default。"""
    fallback = {"min": 3, "max": 2047, "step": 1, "default": 156}
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "-d", f"/dev/video{index}", "--list-ctrls"],
            stderr=subprocess.DEVNULL, text=True, timeout=5)
    except Exception as e:
        print(f"--- [Camera] 查詢曝光範圍失敗，用預設值: {e} ---")
        return fallback
    for line in out.splitlines():
        if "exposure_time_absolute" in line:
            vals = {}
            for tok in line.split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    try:
                        vals[k] = int(v)
                    except ValueError:
                        pass
            return {
                "min": vals.get("min", fallback["min"]),
                "max": vals.get("max", fallback["max"]),
                "step": vals.get("step", 1) or 1,
                "default": vals.get("default", fallback["default"]),
            }
    print("--- [Camera] 未找到 exposure_time_absolute，用預設值 ---")
    return fallback


class FishCamera:
    STEPS = 20
    MIN_FPS = 12

    # Step 三段對應常數
    GAIN_DEFAULT = 64
    GAIN_MIN     = 0
    GAIN_MAX     = 128
    DARK_END     = 3   # step 0..3：固定 exp_min，調 gain 0→48
    EXP_END      = 16  # step 4..16：固定 gain=64，對數曝光
                       # step 17..20：固定 exp_hi，調 gain 80→128

    # 自動亮度 thread 參數
    _AUTO_CHECK_INTERVAL    = 3.0   # 正常輪詢間隔（秒）
    _AUTO_FAST_INTERVAL     = 0.5   # 亮度突變後的快速跟進間隔
    _AUTO_SURGE_THRESHOLD   = 20    # 亮度變化超過此值視為突變
    _AUTO_TARGET_BRIGHTNESS = 110
    _AUTO_DEADBAND          = 12
    _AUTO_SAMPLE_W          = 80
    _AUTO_SAMPLE_H          = 45

    def __init__(self, device_index=0):
        self.cap = None
        self.quality = 80
        self.output_size = (1280, 720)
        self._cam_lock = threading.Lock()
        self.device_index = device_index
        # 曝光狀態
        self.auto_exposure = True
        self.exposure_step = self.STEPS // 2  # 初始從中間開始，不再是 None
        self._exp_range = {"min": 3, "max": 2047, "step": 1, "default": 156}
        # 自動亮度 thread
        self._auto_stop_event = threading.Event()
        self._auto_thread = None
        self._auto_target_brightness = float(self._AUTO_TARGET_BRIGHTNESS)

        self.discover_camera()
        if self.auto_exposure:
            self._start_auto_thread()

    def discover_camera(self):
        index = self.device_index
        print(f"--- [Camera] 執行系統層級 V4L2 重置 (/dev/video{index}) ---")
        os.system(f"v4l2-ctl -d /dev/video{index} --set-fmt-video=width=1920,height=1080,pixelformat=MJPG")
        self._exp_range = _query_exposure_range(index)
        print(f"--- [Camera] 曝光範圍: {self._exp_range} ---")

        self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            print("--- [Camera] 等待硬體穩定中... ---")
            time.sleep(2)
            for _ in range(5):
                self.cap.read()
            ret, frame = self.cap.read()
            if ret and frame is not None:
                print(f"--- [Camera] 1080p 鏡頭初始化成功！ ---")
                return
        print("--- [Camera] 錯誤：無法開啟鏡頭節點 ---")

    # --- Step ↔ (exposure, gain) 對應 ---

    def _usable_exposure_max(self):
        fps_cap = int(10000 / self.MIN_FPS)
        return max(self._exp_range["min"] + 1, min(self._exp_range["max"], fps_cap))

    def _step_to_exp_gain(self, step):
        """離散步階 (0..STEPS) → (exposure_time_absolute, gain)"""
        step = max(0, min(self.STEPS, step))
        exp_lo = self._exp_range["min"]
        exp_hi = self._usable_exposure_max()

        if step <= self.DARK_END:
            gain = int(self.GAIN_DEFAULT * step / (self.DARK_END + 1))
            return exp_lo, gain
        elif step <= self.EXP_END:
            t = (step - self.DARK_END) / (self.EXP_END - self.DARK_END)
            if t == 0:
                exp = exp_lo
            else:
                exp = int(round(math.exp(
                    math.log(exp_lo) + (math.log(exp_hi) - math.log(exp_lo)) * t
                )))
            return exp, self.GAIN_DEFAULT
        else:
            t = (step - self.EXP_END) / (self.STEPS - self.EXP_END)
            gain = int(round(self.GAIN_DEFAULT + (self.GAIN_MAX - self.GAIN_DEFAULT) * t))
            return exp_hi, gain

    # --- 硬體套用 ---

    def _apply_exposure_locked(self):
        """套用目前 exposure_step 到硬體。需在持有 _cam_lock 時呼叫。"""
        if not (self.cap and self.cap.isOpened()):
            return False
        try:
            step = self.exposure_step if self.exposure_step is not None else (self.STEPS // 2)
            exp, gain = self._step_to_exp_gain(step)
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 強制手動，不再用硬體自動曝光
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exp)
            self.cap.set(cv2.CAP_PROP_GAIN, gain)
            print(f"--- [Camera {self.device_index}] step={step}/{self.STEPS} "
                  f"exp={exp} gain={gain} ---")
            return True
        except Exception as e:
            print(f"--- [Camera] 套用曝光失敗: {e} ---")
            return False

    # --- 自動亮度 thread ---

    def _start_auto_thread(self):
        self._stop_auto_thread()
        self._auto_stop_event.clear()
        t = threading.Thread(target=self._auto_exposure_loop, daemon=True,
                             name=f"AutoExp-{self.device_index}")
        self._auto_thread = t
        t.start()

    def _stop_auto_thread(self):
        """通知 thread 停止並等待結束。不可在持有 _cam_lock 時呼叫。"""
        self._auto_stop_event.set()
        t = self._auto_thread
        if t and t.is_alive():
            t.join(timeout=self._AUTO_CHECK_INTERVAL + 1.0)
        self._auto_thread = None

    def _auto_exposure_loop(self):
        interval = self._AUTO_CHECK_INTERVAL
        prev_brightness = None
        while not self._auto_stop_event.wait(timeout=interval):
            # 短暫持鎖取一幀
            with self._cam_lock:
                if not self.auto_exposure:
                    break
                if not (self.cap and self.cap.isOpened()):
                    interval = self._AUTO_CHECK_INTERVAL
                    continue
                ret, frame = self.cap.read()
            if not ret or frame is None:
                interval = self._AUTO_CHECK_INTERVAL
                continue

            # 鎖外計算亮度（不阻塞串流）
            small = cv2.resize(frame, (self._AUTO_SAMPLE_W, self._AUTO_SAMPLE_H),
                               interpolation=cv2.INTER_AREA)
            brightness = float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())
            self._last_brightness = round(brightness, 1)

            # 亮度突變：下一次快速跟進
            if prev_brightness is not None and abs(brightness - prev_brightness) >= self._AUTO_SURGE_THRESHOLD:
                interval = self._AUTO_FAST_INTERVAL
            else:
                interval = self._AUTO_CHECK_INTERVAL
            prev_brightness = brightness

            error = brightness - self._auto_target_brightness
            if abs(error) <= self._AUTO_DEADBAND:
                continue
            direction = -1 if error > 0 else 1

            with self._cam_lock:
                if not self.auto_exposure:
                    break
                current = self.exposure_step if self.exposure_step is not None else (self.STEPS // 2)
                new_step = max(0, min(self.STEPS, current + direction))
                if new_step != current:
                    self.exposure_step = new_step
                    self._apply_exposure_locked()
                    print(f"[AutoExp {self.device_index}] brightness={brightness:.1f} "
                          f"target={self._auto_target_brightness:.1f} "
                          f"step {current}→{new_step}")

    # --- 公開曝光控制 ---

    def set_exposure(self, value):
        """value=None → 啟動自動亮度 thread；0..STEPS → 手動固定步階。"""
        if value is None:
            with self._cam_lock:
                self.auto_exposure = True
            self._start_auto_thread()
            return True
        else:
            self._auto_stop_event.set()  # 通知 thread 停止，不 join（避免持鎖 deadlock）
            with self._cam_lock:
                self.auto_exposure = False
                self.exposure_step = max(0, min(self.STEPS, int(value)))
                return self._apply_exposure_locked()

    def nudge_exposure(self, direction):
        """箭頭調整 ±1 步階。從自動當前位置出發，不再是 STEPS//2。"""
        self._auto_stop_event.set()  # 通知 thread 停止，不 join
        with self._cam_lock:
            base = self.exposure_step if self.exposure_step is not None else (self.STEPS // 2)
            self.auto_exposure = False
            self.exposure_step = max(0, min(self.STEPS, base + (1 if direction > 0 else -1)))
            return self._apply_exposure_locked()

    def exposure_state(self):
        """回傳曝光狀態給前端：{auto, step, steps}。auto 模式下 step 也有值。"""
        return {"auto": self.auto_exposure, "step": self.exposure_step, "steps": self.STEPS}

    # --- 校準 ---

    def measure_brightness(self):
        """取一幀，回傳下採樣灰階平均亮度 (0-255 float)，失敗回 None。"""
        with self._cam_lock:
            if not (self.cap and self.cap.isOpened()):
                return None
            ret, frame = self.cap.read()
        if not ret or frame is None:
            return None
        small = cv2.resize(frame, (self._AUTO_SAMPLE_W, self._AUTO_SAMPLE_H),
                           interpolation=cv2.INTER_AREA)
        return float(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).mean())

    def set_auto_target(self, brightness):
        """設定自動亮度目標值（0-255），供 auto thread 追蹤。"""
        self._auto_target_brightness = float(brightness)

    # --- 輸出設定 ---

    def set_output(self, size, quality):
        with self._cam_lock:
            self.output_size = size
            self.quality = quality

    # --- 重置 ---

    def reset(self):
        """釋放並重新初始化攝影機，重新套用既有設定。"""
        self._stop_auto_thread()  # join 安全：此時不持鎖
        with self._cam_lock:
            print(f"--- [Camera] 重置攝影機 (/dev/video{self.device_index}) ---")
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.discover_camera()
            ok = self.cap is not None and self.cap.isOpened()
            if ok and not self.auto_exposure:
                self._apply_exposure_locked()
        if ok and self.auto_exposure:
            self._start_auto_thread()
        return ok

    # --- 取幀 ---

    def get_raw_frame(self):
        with self._cam_lock:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    return frame
        return None

    def get_frame(self):
        with self._cam_lock:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    if self.output_size is not None:
                        frame = cv2.resize(frame, self.output_size, interpolation=cv2.INTER_AREA)
                    use_webp = self.output_size is not None and self.output_size[1] <= 480
                    if use_webp:
                        _, buffer = cv2.imencode('.webp', frame, [cv2.IMWRITE_WEBP_QUALITY, self.quality])
                        return buffer.tobytes(), 'image/webp'
                    else:
                        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                        return buffer.tobytes(), 'image/jpeg'
        return None, None

    def __del__(self):
        self._stop_auto_thread()
        if self.cap:
            self.cap.release()
