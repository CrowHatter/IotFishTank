import cv2
import time

class FishCamera:
    def __init__(self):
        self.cap = None
        self.discover_camera()

    def discover_camera(self):
        # 根據 v4l2-ctl 結果，優先嘗試索引 1
        target_indices = [1, 2, 0] 
        
        for index in target_indices:
            print(f"--- [Camera] 嘗試開啟裝置 /dev/video{index} ---")
            # 強制使用 V4L2 後端
            self.cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
            
            if self.cap.isOpened():
                # 1. 強制設定為 MJPG 格式 (這是這顆鏡頭流暢的關鍵)
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                
                # 2. 設定解析度為 720p (兼顧頻寬與網頁比例)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                
                # 3. 緩衝區設定 (減少延遲)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                # 4. 驗證是否真的有畫面
                ret, frame = self.cap.read()
                if ret:
                    print(f"--- [Camera] 成功在 /dev/video{index} 獲取畫面！ ---")
                    return
                else:
                    print(f"--- [Camera] 裝置 /dev/video{index} 已開啟但讀取幀失敗 ---")
                    self.cap.release()
            
        print("--- [Camera] 錯誤：所有鏡頭裝置皆無法獲取影像 ---")

    def get_frame(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                # 2K 鏡頭原始畫面較大，編碼時維持 80% 品質以平衡傳輸速度
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                return buffer.tobytes()
        return None

    def __del__(self):
        if self.cap:
            self.cap.release()