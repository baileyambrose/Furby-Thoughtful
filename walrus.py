from gpiozero import Motor, Button
from time import sleep
import time
import sounddevice as sd
import soundfile as sf
import cv2

img = cv2.imread("magicalmysterytour.jpg")

# Check if the JPG actually loaded
if img is None:
    raise ValueError("Image failed to load. Check the path or filename.")

cv2.namedWindow("fullscreen", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("fullscreen", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

# Optionally scale image to screen size
screen_res = 1080, 1920  # change if needed
scale_width = screen_res[0] / img.shape[1]
scale_height = screen_res[1] / img.shape[0]
scale = min(scale_width, scale_height)
window_width = int(img.shape[1] * scale)
window_height = int(img.shape[0] * scale)
img_resized = cv2.resize(img, (window_width, window_height))

cv2.imshow("fullscreen", img_resized)


data, sr = sf.read("i_am_the_walrus.wav", dtype='float32')

# Slice the audio starting at 2 seconds
segment = data[185*sr:]

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
	(3.9, open_mouth),#I AM
	(4.1, close_mouth),
	(4.1, open_close_mouth_blink),#THE
	(4.6, close_mouth),#EGGMAN
	
	(6.6, open_mouth),#THEY ARE
	(6.8, close_mouth),
	(6.8, open_mouth),#THE
	(7.0, close_mouth),
	(7.0, open_mouth),#EGGMEN
	(7.3, close_mouth),
	
	(9.3, open_mouth),#I AM
	(9.5, close_mouth),
	(9.5, open_close_mouth_blink),#THE
	(9.9, close_mouth),#WAL
	(9.9, open_mouth),#RUS
	(10.1, close_mouth),
	
	(11.3, open_mouth),#DO
	(11.5, close_mouth),
	(11.7, open_mouth),#DO
	(11.9, close_mouth),
	(12.1, open_mouth),#DO
	(12.3, close_mouth),
	(12.5, open_close_mouth_blink),#DO CACHU
	(12.9, close_mouth),#DO
	
	(15.5, open_mouth),#CO
	(15.7, close_mouth),
	(15.9, open_mouth),#CO
	(16.1, close_mouth),
]

calibrate()
sleep(1)

#close()
print("Walrus start...")
sd.play(segment, sr, blocking=False)

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
#sd.wait()
sleep(2)

cv2.destroyAllWindows()
print("Done playing")
