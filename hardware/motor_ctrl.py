import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

class FishFeeder:
    # 修改 __init__，讓它接收 pins 列表，預設值為你原本的腳位
    def __init__(self, pins=[17, 18, 27, 22]):
        self.pins = pins
        self.sequence = [
            [1,0,0,1], [1,0,0,0], [1,1,0,0], [0,1,0,0],
            [0,1,1,0], [0,0,1,0], [0,0,1,1], [0,0,0,1]
        ]
        self.is_busy = False

        if GPIO_AVAILABLE:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            # 初始化該實例指定的腳位
            for pin in self.pins:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, False)
        else:
            print(f"[Mock] FishFeeder 初始化 pins={self.pins}（無 GPIO，降級為 mock）")

    def rotate(self, fraction, direction, delay=0.002):
        steps = int(abs(fraction) * 4096 / 8) # 修正：28BYJ-48 完整循環通常包含 8 個子步
        if not GPIO_AVAILABLE:
            print(f"[Mock] rotate fraction={fraction} direction={direction} ({steps} steps)")
            return
        seq = self.sequence if direction > 0 else list(reversed(self.sequence))

        for _ in range(steps):
            for step in seq:
                for i in range(4):
                    GPIO.output(self.pins[i], step[i])
                time.sleep(delay)

    def feed_sequence(self):
        """執行餵食動作流程"""
        if self.is_busy:
            return False

        try:
            self.is_busy = True
            self.rotate(1/72, -1)   # 順時針撥動
            time.sleep(0.5)
            self.rotate(1/2, 1)   # 逆時針回彈（註：原本寫 1 圈可能太久，建議根據容器大小調整）
            return True
        finally:
            self.stop()
            self.is_busy = False

    def stop(self):
        """將所有腳位設為低電位，防止馬達過熱"""
        if not GPIO_AVAILABLE:
            return
        for pin in self.pins:
            GPIO.output(pin, False)
