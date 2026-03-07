import cv2
import threading
import time

class FishCamera:
    def __init__(self, max_index=5):
        """
        初始化鏡頭並自動掃描可用裝置
        :param max_index: 掃描從 /dev/video0 到 /dev/videoX 的索引上限
        """
        self.cap = None
        self.lock = threading.Lock() # 確保多執行緒讀取影像時不會發生衝突
        self.active_index = -1
        
        print("--- [Camera] 開始掃描可用鏡頭裝置 ---")
        
        for i in range(max_index + 1):
            # 嘗試開啟索引為 i 的鏡頭
            temp_cap = cv2.VideoCapture(i)
            
            if temp_cap.isOpened():
                # 關鍵：必須嘗試讀取一幀以確認硬體真的有影像輸出 (非空殼裝置)
                ret, frame = temp_cap.read()
                if ret:
                    self.cap = temp_cap
                    self.active_index = i
                    print(f"--- [Camera] 成功找到鏡頭！使用裝置索引: {i} ---")
                    break
                else:
                    temp_cap.release()
            else:
                temp_cap.release()

        if self.cap is None:
            print("--- [Camera] 警告：未發現任何可用的鏡頭裝置。 ---")
        else:
            # 1. 設定解析度 (樹莓派建議 640x480 或 800x600 以維持順暢)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            # 2. 嘗試限制 FPS (硬體端減少負擔)
            self.cap.set(cv2.CAP_PROP_FPS, 20)
            
            # 3. 關閉緩衝區 (確保影像為「最即時」而非「最流暢」)
            # 這能有效防止 MJPEG 串流累積延遲
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def get_frame(self):
        """
        抓取當前畫面並轉換為 JPEG 位元組
        """
        if self.cap is None or not self.cap.isOpened():
            return None
            
        with self.lock:
            success, frame = self.cap.read()
            if not success:
                return None
            
            # 將 OpenCV 矩陣 BGR 轉換為 JPEG 位元組
            # [cv2.IMWRITE_JPEG_QUALITY, 75] 可在頻寬與品質間取得平衡
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            
            if not ret:
                return None
            
            return jpeg.tobytes()

    def __del__(self):
        """
        物件銷毀時釋放資源
        """
        if self.cap and self.cap.isOpened():
            self.cap.release()
            print("--- [Camera] 鏡頭資源已成功釋放 ---")