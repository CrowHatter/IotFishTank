import cv2
import os
import time

# 強制使用 xcb 避免 Qt 視窗插件崩潰
os.environ["QT_QPA_PLATFORM"] = "xcb"

def run_stable_test():
    index = 0
    print(f"--- 啟動 Index {index} 穩定性測試 ---")
    
    # 使用 V4L2 後端開啟
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    
    if not cap.isOpened():
        print(f"錯誤：無法開啟鏡頭 Index {index}")
        return

    # 設定解析度，避免頻寬過載導致的中斷
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("串流已啟動，請觀察視窗。按下 'q' 鍵退出並釋放鏡頭。")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("警告：無法讀取影像幀。正在嘗試重新讀取...")
                time.sleep(0.5)
                continue

            # 在畫面上顯示一個動態時間戳記，確認沒有「凍結」
            ts = time.strftime("%H:%M:%S")
            cv2.putText(frame, ts, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            cv2.imshow('FishTank_Debug', frame)

            # 關鍵：waitKey 必須存在且時間不能太短
            if cv2.waitKey(30) & 0xFF == ord('q'):
                print("使用者按下 'q'，準備正常關閉...")
                break
    except Exception as e:
        print(f"執行中發生錯誤: {e}")
    finally:
        # 徹底釋放
        cap.release()
        cv2.destroyAllWindows()
        # 強制刷新視窗系統
        for i in range(5):
            cv2.waitKey(1)
        print("--- 鏡頭資源已成功釋放 ---")

if __name__ == "__main__":
    run_stable_test()