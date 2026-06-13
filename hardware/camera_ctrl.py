import cv2
import time
import os
import threading
import subprocess

def enumerate_cameras():
    """
    掃描 /dev/video0~9，找出所有可用的攝影機及其 by-path。
    回傳 list of {"index": N, "by_path": "..."} 依 index 升序排列。
    """
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
    """
    取得 /dev/videoN 對應的 /dev/v4l/by-path/ symlink（如果存在）。
    沒有的話回傳 None。
    """
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
    """用 v4l2-ctl 查詢 exposure_time_absolute 的真實 min/max/step/default。
    查不到時回傳保守預設。單位為 100µs（V4L2 慣例）。"""
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
    # 手動曝光的拉桿/按鈕用「離散步階」表示，步數固定為 STEPS 段。
    # 實際曝光值由查詢到的硬體 range 動態決定（見 _exp_range）。
    STEPS = 20
    # 維持可接受幀率的最低 fps：曝光時間(100µs) ≈ 10000/fps，
    # 故把可用曝光上限夾在 10000/MIN_FPS 以內，避免拉高曝光時幀數暴跌。
    MIN_FPS = 12

    def __init__(self, device_index=0):
        self.cap = None
        self.quality = 80
        self.output_size = (1280, 720)
        self._cam_lock = threading.Lock()
        self.device_index = device_index
        # 曝光狀態
        self.auto_exposure = True
        self.exposure_step = None     # 0..STEPS 的離散步階；None = 自動
        self._exp_range = {"min": 3, "max": 2047, "step": 1, "default": 156}
        self.discover_camera()

    def discover_camera(self):
        index = self.device_index
        print(f"--- [Camera] 執行系統層級 V4L2 重置 (/dev/video{index}) ---")

        # 先透過系統指令強迫設定格式與解析度
        os.system(f"v4l2-ctl -d /dev/video{index} --set-fmt-video=width=1920,height=1080,pixelformat=MJPG")

        # 查詢這台相機真實的曝光範圍（每次 (re)open 都重查，確保 reset 後正確）
        self._exp_range = _query_exposure_range(index)
        print(f"--- [Camera] 曝光範圍: {self._exp_range} ---")

        self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        
        if self.cap.isOpened():
            # 強制設定 MJPEG 
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            
            # 提升解析度至 1080p
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            
            # 設定緩衝區為 1，減少延遲
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            print("--- [Camera] 等待硬體穩定中... ---")
            time.sleep(2) # 給 2K 鏡頭更多初始化時間
            
            # 暖機讀取
            for _ in range(5):
                self.cap.read()

            ret, frame = self.cap.read()
            if ret and frame is not None:
                print(f"--- [Camera] 1080p 鏡頭初始化成功！ ---")
                return
        
        print("--- [Camera] 錯誤：無法開啟鏡頭節點 ---")

    def set_output(self, size, quality):
        """size = (w, h) or None (native 1080p); quality = 0-100"""
        with self._cam_lock:
            self.output_size = size
            self.quality = quality

    def _usable_exposure_max(self):
        """可用曝光上限：取硬體 max 與「維持 MIN_FPS 的曝光時間上限」中較小者，
        避免拉高曝光時幀率暴跌（曝光時間 100µs 單位 ≈ 10000/fps）。"""
        fps_cap = int(10000 / self.MIN_FPS)
        return max(self._exp_range["min"] + 1, min(self._exp_range["max"], fps_cap))

    def _step_to_exposure(self, step):
        """離散步階(0..STEPS) → 實際 exposure_time_absolute 值。"""
        lo = self._exp_range["min"]
        hi = self._usable_exposure_max()
        s = max(0, min(self.STEPS, step))
        return int(round(lo + (hi - lo) * s / self.STEPS))

    def _apply_exposure_locked(self):
        """套用目前的曝光狀態到硬體。需在持有 _cam_lock 時呼叫。回傳是否成功。"""
        if not (self.cap and self.cap.isOpened()):
            return False
        try:
            if self.auto_exposure or self.exposure_step is None:
                # 3 = V4L2 aperture-priority/auto exposure
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
            else:
                # 1 = V4L2 manual exposure，先切手動再設值
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                exp = self._step_to_exposure(self.exposure_step)
                self.cap.set(cv2.CAP_PROP_EXPOSURE, exp)
                print(f"--- [Camera {self.device_index}] 曝光 step={self.exposure_step}/"
                      f"{self.STEPS} → exposure_time_absolute={exp} ---")
            return True
        except Exception as e:
            print(f"--- [Camera] 套用曝光失敗: {e} ---")
            return False

    def set_exposure(self, value):
        """value = None → 恢復硬體自動曝光；0..STEPS → 手動曝光離散步階。
        自動對焦不受影響。回傳是否成功。"""
        with self._cam_lock:
            if value is None:
                self.auto_exposure = True
                self.exposure_step = None
            else:
                self.auto_exposure = False
                self.exposure_step = max(0, min(self.STEPS, int(value)))
            return self._apply_exposure_locked()

    def nudge_exposure(self, direction):
        """箭頭調整：direction = +1(變亮/曝光增) 或 -1(變暗/曝光減)。
        若目前是自動，先以中間步階進入手動再調。回傳是否成功。"""
        with self._cam_lock:
            if self.auto_exposure or self.exposure_step is None:
                base = self.STEPS // 2
            else:
                base = self.exposure_step
            self.auto_exposure = False
            self.exposure_step = max(0, min(self.STEPS, base + (1 if direction > 0 else -1)))
            return self._apply_exposure_locked()

    def exposure_state(self):
        """回傳目前曝光狀態給前端：{auto, step, steps}。"""
        return {"auto": self.auto_exposure, "step": self.exposure_step, "steps": self.STEPS}

    def reset(self):
        """釋放並重新初始化攝影機（USB 卡死時用），重新套用既有輸出與曝光設定。
        回傳是否成功。"""
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
            if ok:
                self._apply_exposure_locked()
            return ok

    def get_raw_frame(self):
        """回傳原生解析度 BGR numpy frame（供影像分析用），失敗回 None。
        不經過 resize/編碼，與串流用的 get_frame() 分開。"""
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
                    # 低解析度（480p/360p）用 WebP 省流量；高解析度用 JPEG 維持效能
                    use_webp = self.output_size is not None and self.output_size[1] <= 480
                    if use_webp:
                        _, buffer = cv2.imencode('.webp', frame, [cv2.IMWRITE_WEBP_QUALITY, self.quality])
                        return buffer.tobytes(), 'image/webp'
                    else:
                        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                        return buffer.tobytes(), 'image/jpeg'
        return None, None

    def __del__(self):
        if self.cap:
            self.cap.release()