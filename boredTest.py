from gpiozero import Motor, Button
from time import sleep
import time
import sounddevice as sd
import soundfile as sf

data, sr = sf.read("bored.mp3", dtype='float32')

sd.default.latency = ('low', 'low')   # request smallest buffers
sd.default.blocksize = 256            # tiny block size
sd.default.channels = 1               # mono

# Motor(IN1, IN2, enable=EN)
motor = Motor(20, 21, enable=16)
button = Button(12, pull_up=True)

def calibrate():
	motor.forward(0.4)
	sleep(0.2)
	print(f"{button.is_pressed}")
	button.wait_for_press()
	print(f"done {button.is_pressed}")
	# Manual brake: both inputs HIGH
	motor.forward_device.on()
	motor.backward_device.on()
	print("Calibrated")
	
def open_mouth():
	motor.backward()
	sleep(0.19)
	motor.forward()
	sleep(0.05)
	# Manual brake: both inputs HIGH
	motor.forward_device.on()
	motor.backward_device.on()
	
def open_close_mouth_blink():
	motor.backward()
	sleep(0.39)
	motor.forward()
	sleep(0.05)
	# Manual brake: both inputs HIGH
	motor.forward_device.on()
	motor.backward_device.on()

def close_mouth():
	motor.forward()
	button.wait_for_press()
	#Manual brake
	motor.backward()
	sleep(0.05)
	motor.forward_device.on()
	motor.backward_device.on()

song = [
	(0.0, open_close_mouth_blink),#FURBY
	(0.6, close_mouth),
	(0.8, open_mouth),#THINKS
	(1.0, close_mouth),
	(1.2, open_mouth),#YOU
	(1.4, close_mouth),
	(1.6, open_close_mouth_blink),#LOOK
	(2.0, close_mouth),
]

calibrate()
sleep(3)

#close()
print("bored start...")
sd.play(data, sr, blocking=False)

#Execute events at the timestamps
start = time.time()

for t, fn in song:
    now = time.time()
    sleep_time = start + t - now
    if sleep_time > 0:
        time.sleep(sleep_time)
        
    fn()




motor.stop()

# Wait until playback finishes
sd.wait()

print("Done playing")
