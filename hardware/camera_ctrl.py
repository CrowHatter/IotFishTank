import cv2
import time
import os

class FishCamera:
    def __init__(self):
        self.cap = None
        self.discover_camera()

    def discover_camera(self):
        # 根據測試結果，鎖定 /dev/video0
        index = 0
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

    def get_frame(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                # 提高 JPEG 品質到 85，確保畫面細節
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buffer.tobytes()
        return None

    def __del__(self):
        if self.cap:
            self.cap.release()