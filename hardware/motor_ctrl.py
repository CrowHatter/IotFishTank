import RPi.GPIO as GPIO
import time

class FishFeeder:
    def __init__(self):
        self.pins = [17, 18, 27, 22]
        self.sequence = [
            [1,0,0,1], [1,0,0,0], [1,1,0,0], [0,1,0,0],
            [0,1,1,0], [0,0,1,0], [0,0,1,1], [0,0,0,1]
        ]
        GPIO.setmode(GPIO.BCM)
        for pin in self.pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, False)

    def rotate(self, fraction, direction, delay=0.002):
        # 4096 步為一圈
        steps = int(abs(fraction) * 4096)
        seq = self.sequence if direction > 0 else list(reversed(self.sequence))
        
        for _ in range(steps):
            for step in seq:
                for i in range(4):
                    GPIO.output(self.pins[i], step[i])
                time.sleep(delay)
        self.stop()

    def feed_sequence(self):
        """執行：順時針 1/72 -> 逆時針 1/18"""
        print("開始餵食程序...")
        self.rotate(1/72, direction=1)  # 順時針
        time.sleep(0.5)                 # 稍微停頓
        self.rotate(1/18, direction=-1) # 逆時針
        print("餵食程序完成。")

    def stop(self):
        for pin in self.pins:
            GPIO.output(pin, False)