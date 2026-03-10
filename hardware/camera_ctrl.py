import cv2
import time

class FishCamera:
    def __init__(self):
        self.cap = None
        self.discover_camera()

    def discover_camera(self):
        # 根據 v4l2-ctl，優先鎖定索引 1
        target_indices = [1, 2, 0] 
        
        for index in target_indices:
            print(f"--- [Camera] 嘗試開啟 /dev/video{index} ---")
            self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            
            if self.cap.isOpened():
                # 關鍵設定：MJPG 格式
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                # 設為 720p 確保流暢
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                # --- 修正點：給予鏡頭暖機時間 ---
                print("--- [Camera] 等待硬體穩定中... ---")
                time.sleep(1.5) 
                
                # 暖機：讀取 5 幀丟掉，確保緩衝區充滿正確的 MJPEG 封包
                for _ in range(5):
                    self.cap.read()

                # 最後驗證
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    print(f"--- [Camera] 成功在 /dev/video{index} 獲取有效畫面！ ---")
                    return
                else:
                    print(f"--- [Camera] /dev/video{index} 讀取失敗或畫面為空 ---")
                    self.cap.release()
            
        print("--- [Camera] 嚴重錯誤：無法獲取任何有效影像 ---")

    def get_frame(self):
        if self.cap and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    # 降低品質至 70% 減少外網傳輸壓力
                    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    return buffer.tobytes()
            except Exception as e:
                print(f"--- [Camera] 讀取幀異常: {e} ---")
        return None

    def __del__(self):
        if self.cap:
            self.cap.release()