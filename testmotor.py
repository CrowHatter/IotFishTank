import RPi.GPIO as GPIO
import time

# 設定使用 BCM 編碼 (對應 GPIO 號碼而非 Pin 號碼)
GPIO.setmode(GPIO.BCM)

# 定義 GPIO 腳位
motor_pins = [17, 18, 27, 22]

# 初始化所有腳位為輸出
for pin in motor_pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, False)

# 步進馬達的 8 步序列 (半步模式，扭力較穩)
sequence = [
    [1,0,0,1],
    [1,0,0,0],
    [1,1,0,0],
    [0,1,0,0],
    [0,1,1,0],
    [0,0,1,0],
    [0,0,1,1],
    [0,0,0,1]
]

def rotate(steps, direction=1, delay=0.003):
    """
    steps: 轉動步數 (512 步約一圈)
    direction: 1 為順時針, -1 為逆時針
    delay: 步進間隔 (越小越快，但太小馬達會跟不上只發出嗶聲)
    """
    for _ in range(steps):
        # 根據方向循環序列
        for step in (sequence if direction == 1 else reversed(sequence)):
            for i in range(4):
                GPIO.output(motor_pins[i], step[i])
            time.sleep(delay)

try:
    print("開始測試：順時針轉動...")
    rotate(1024, direction=1)
    
    time.sleep(1)
    
    print("開始測試：逆時針轉動...")
    rotate(1024, direction=-1)

except KeyboardInterrupt:
    print("使用者停止程式")
finally:
    GPIO.cleanup() # 務必清理 GPIO 狀態
    print("GPIO 已清理")