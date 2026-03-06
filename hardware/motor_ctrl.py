import RPi.GPIO as GPIO
import time

class FishFeeder:
    def __init__(self):
        self.pins = [17, 18, 27, 22]
        self.sequence = [
            [1,0,0,1], [1,0,0,0], [1,1,0,0], [0,1,0,0],
            [0,1,1,0], [0,0,1,0], [0,0,1,1], [0,0,0,1]
        ]
        # --- 關鍵：新增這行屬性 ---
        self.is_busy = False 
        
        GPIO.setwarnings(False) # 順便關閉你看到的 RuntimeWarning
        GPIO.setmode(GPIO.BCM)
        for pin in self.pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, False)

    def rotate(self, fraction, direction, delay=0.002):
        steps = int(abs(fraction) * 4096)
        seq = self.sequence if direction > 0 else list(reversed(self.sequence))
        for _ in range(steps):
            for step in seq:
                for i in range(4):
                    GPIO.output(self.pins[i], step[i])
                time.sleep(delay)

    def feed_sequence(self):
        """執行餵食動作流程"""
        # 如果正在忙碌，直接回傳 False 拒絕新任務
        if self.is_busy:
            return False
            
        try:
            self.is_busy = True # 標記為忙碌
            self.rotate(1/72, 1)  # 順時針
            time.sleep(0.5)
            self.rotate(1/36, -1) # 逆時針
            return True
        finally:
            self.stop()
            self.is_busy = False # 動作結束，恢復為不忙碌
            
    def stop(self):
        for pin in self.pins:
            GPIO.output(pin, False)