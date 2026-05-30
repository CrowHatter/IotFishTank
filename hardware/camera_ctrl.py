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
    def __init__(self, device_index=0):
        self.cap = None
        self.quality = 80
        self.output_size = (1280, 720)
        self._cam_lock = threading.Lock()
        self.device_index = device_index
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