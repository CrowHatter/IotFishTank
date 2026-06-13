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

class FishCamera:
    # 曝光映射：UI 用 0–100 抽象刻度，後端線性映射到 V4L2 exposure_time_absolute
    # 常見區間。實際範圍需在 Pi 上以 `v4l2-ctl --list-ctrls` 確認後微調。
    EXPOSURE_MIN = 1
    EXPOSURE_MAX = 1000

    def __init__(self, device_index=0):
        self.cap = None
        self.quality = 80
        self.output_size = (1280, 720)
        self._cam_lock = threading.Lock()
        self.device_index = device_index
        # 曝光狀態：預設自動曝光（拉桿顯示 AUTO）
        self.auto_exposure = True
        self.exposure_value = None   # UI 0–100 刻度；None = 自動
        self.discover_camera()

    def discover_camera(self):
        index = self.device_index
        print(f"--- [Camera] 執行系統層級 V4L2 重置 (/dev/video{index}) ---")

        # 先透過系統指令強迫設定格式與解析度
        os.system(f"v4l2-ctl -d /dev/video{index} --set-fmt-video=width=1920,height=1080,pixelformat=MJPG")
        
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

    def _apply_exposure_locked(self):
        """套用目前的曝光狀態到硬體。需在持有 _cam_lock 時呼叫。回傳是否成功。"""
        if not (self.cap and self.cap.isOpened()):
            return False
        try:
            if self.auto_exposure or self.exposure_value is None:
                # 3 = V4L2 aperture-priority/auto exposure
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
            else:
                # 1 = V4L2 manual exposure，先切手動再設值
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
                ui = max(0, min(100, self.exposure_value))
                mapped = self.EXPOSURE_MIN + (self.EXPOSURE_MAX - self.EXPOSURE_MIN) * ui / 100.0
                self.cap.set(cv2.CAP_PROP_EXPOSURE, mapped)
            return True
        except Exception as e:
            print(f"--- [Camera] 套用曝光失敗: {e} ---")
            return False

    def set_exposure(self, value):
        """value = None → 恢復硬體自動曝光；0–100 → 手動曝光（線性映射）。
        自動對焦不受影響。回傳是否成功。"""
        with self._cam_lock:
            if value is None:
                self.auto_exposure = True
                self.exposure_value = None
            else:
                self.auto_exposure = False
                self.exposure_value = max(0, min(100, int(value)))
            return self._apply_exposure_locked()

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