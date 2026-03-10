import cv2
import time
import os

class FishCamera:
    def __init__(self):
        self.cap = None
        self.discover_camera()

    def discover_camera(self):
        # 1. 強制重置 V4L2 狀態（透過系統指令設定格式）
        # 設定 /dev/video1 使用 MJPG 且解析度為 1280x720
        print("--- [Camera] 執行系統層級 V4L2 初始化... ---")
        os.system("v4l2-ctl -d /dev/video1 --set-fmt-video=width=1280,height=720,pixelformat=MJPG")
        
        target_indices = [1] # 根據你的 Spec，video1 是唯一正確的影像源
        
        for index in target_indices:
            print(f"--- [Camera] 嘗試開啟 /dev/video{index} ---")
            
            # 使用更基礎的開啟方式，移除 CAP_V4L2 參數讓 OpenCV 自行適應
            self.cap = cv2.VideoCapture(index)
            
            if self.cap.isOpened():
                # 重新設定一次參數
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                # 給予鏡頭穩定時間
                time.sleep(1) 
                
                # 嘗試讀取（若 select() timeout 會卡在這裡）
                # 我們只試讀一幀，並設定較短的超時檢測
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    print(f"--- [Camera] 成功在 /dev/video{index} 獲取畫面！ ---")
                    return
                else:
                    print(f"--- [Camera] 讀取失敗，嘗試釋放並重啟 ---")
                    self.cap.release()
            
        print("--- [Camera] 無法啟動鏡頭，請嘗試重新插拔 USB ---")

    def get_frame(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret and frame is not None:
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                return buffer.tobytes()
        return None