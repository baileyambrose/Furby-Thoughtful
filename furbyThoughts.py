#!/usr/bin/python3
import cv2
from picamera2 import Picamera2, MappedArray
from fer.fer import FER
#import time
import numpy as np
import threading
import random
from datetime import datetime, time

import os
import signal
import sys
from gpiozero import Motor, Button
from time import sleep, monotonic
import sounddevice as sd
import soundfile as sf
import re

import yaml
from pathlib import Path

# Emotion detector (FER uses a CNN trained on FER2013)
emotion_detector = FER(mtcnn=False)
current_emotion = None
emotion_start_time = None
HOLD_TIME = 1.0   
triggered = False

trigger_emotion = None

sound_folder = "sounds/"

active = False
activation_schedule = {
    "Monday":    [("12:00", "19:00")],
    "Tuesday":   [("12:00", "22:00")],#("12:00", "19:00")
    "Wednesday": [("12:00", "19:00")],#("12:00", "19:00")
    "Thursday":  [("12:00", "19:50")],
    "Friday":    [("12:00", "19:00")],
    "Saturday":  [("09:00", "21:30")],
    "Sunday":    [("11:00", "17:10")],
}
sleeping = False
low_power_schedule = {
    "Monday":    [("12:00", "19:00")],
    "Tuesday":   [("12:00", "19:00")],
    "Wednesday": [("12:00", "19:00")],
    "Thursday":  [("12:00", "19:50")],
    "Friday":    [("12:00", "19:00")],
    "Saturday":  [],
    "Sunday":    [],
}
last_activation_time = 0.0
INACTIVITY_PERIOD = 60.0 * 20.0 #time to go low power after seeing no faces for this duration of seconds

force_shutdown = False

def handle_sigterm(signum, frame):
    global force_shutdown
    force_shutdown = True
    print("Received SIGTERM, shutting down...")

signal.signal(signal.SIGTERM, handle_sigterm)

class FurbyMotor:
    def __init__(self, motor_pin_dir1, motor_pin_dir2, enable_pin, button_pin):
        #Motor(IN1, IN2, enable=EN)
        self.motor = Motor(motor_pin_dir1, motor_pin_dir2, enable=enable_pin)
        self.button = Button(button_pin, pull_up=True, bounce_time=0.0005)

        self.button.when_pressed = self._on_button_pressed

        self.is_calibrating = False
        self.calibration_time = 0.0

        self.is_opening = False
        self.is_closing = False
        self.motor_start_time = 0.0
        self.motor_duration = 0.0

        self.is_stopping = False
        self.motor_stop_time = 0.0

        self.sequence = []
        self.sequence_start_time = 0.0
        self.sequence_index = 0
        self.sequence_active = False

        self._update_thread = None
        self._update_thread_stop = False

    def start_update_thread(self, interval=0.01):
        #Runs update() in a background thread at a fixed interval

        if self._update_thread is not None:
            return  #already running

        self._update_thread_stop = False

        def loop():
            while not self._update_thread_stop:
                self.update()
                sleep(interval)

        self._update_thread = threading.Thread(target=loop, daemon=True)
        self._update_thread.start()
        print("Update thread started")

    def stop_update_thread(self):
        self._update_thread_stop = True
        if self._update_thread is not None:
            self._update_thread.join(timeout=0.2)
        self._update_thread = None
        print("Update thread stopped")

    def load_sequences(self, sequence_dict):
        #list of name:(time_offset, function)
        self.sequence_dict = sequence_dict

    def load_sequence(self, name):
        if name not in self.sequence_dict:
            print(f"Sequence '{name}' not found")
            return
        seq = self.sequence_dict[name]

        self.sequence = sorted(seq, key=lambda x: x[0])
        self.sequence_index = 0
        self.sequence_active = False

        print(f"Sequence '{name}' loaded")

    def calibrate(self):
        self.is_calibrating = True
        self.motor.forward()
        self.calibration_start_time = monotonic()

    def _on_button_pressed(self):
        now = monotonic()
        if self.is_calibrating:
            elapsed = now - self.calibration_start_time
            if elapsed > 4.5:
                self.stop_motor()
                self.is_calibrating = False
                print("Calibration button hit — motor stopped")
        elif self.is_closing:
            elapsed = now - self.motor_start_time
            if elapsed > 0.05:
                print(f"{now} reverse motor (closing, switch pressed)")
                self.motor.backward()
                self.is_closing = False
                self.is_stopping = True
                self.motor_stop_time = now


    def _start_opening(self,duration):
        self.is_opening = True
        self.is_closing = False
        self.motor_duration = duration
        self.motor_start_time = monotonic()

        self.motor.backward()

    def _start_closing(self):
        self.is_opening = False
        self.is_closing = True
        self.motor_start_time = monotonic()

        self.motor.forward()

    def open_mouth(self):
        self._start_opening(0.19)

    def open_close_mouth_blink(self):
        self._start_opening(0.39)

    def close_mouth(self):
        self._start_closing()

    def close_eyes(self):
        self._start_opening(0.34)

    def stop_motor(self):
        self.motor.forward_device.on()
        self.motor.backward_device.on()

    def start_sequence(self):
        self.sequence_start_time = monotonic()
        self.sequence_index = 0
        self.sequence_active = True
        print("Sequence started")

    def update(self):
        #Must be called periodically from main loop
        now = monotonic()
        if self.is_opening:
            elapsed = now - self.motor_start_time
            if elapsed >= self.motor_duration:
                print(f"{now} reverse motor (opening)")
                self.motor.forward()
                self.is_opening = False
                self.is_stopping = True
                self.motor_stop_time = now
        elif self.is_closing:
            elapsed = now - self.motor_start_time
            if elapsed >= self.motor_duration+.1:
                print(f"{now} reverse motor (closing)")
                self.motor.backward()
                self.is_closing = False
                self.is_stopping = True
                self.motor_stop_time = now
        elif self.is_stopping:
            #self.stop_motor()
            elapsed = now - self.motor_stop_time
            if elapsed >= 0.05:
                #Manual brake: both inputs HIGH
                self.motor.forward_device.on()
                self.motor.backward_device.on()
                self.is_stopping = False
                print(f"{now}, {elapsed} stop motor")

        if self.sequence_active and self.sequence_index < len(self.sequence):
            event_time, event_fn = self.sequence[self.sequence_index]
            if now - self.sequence_start_time >= event_time:
                print(f"Sequence event at {event_time}s")
                event_fn()
                self.sequence_index += 1

            #if finished
            if self.sequence_index >= len(self.sequence):
                self.sequence_active = False
                print("Sequence finished")

furby = FurbyMotor(20,21,16,12)

class AudioBank:
    def __init__(self, folder):
        self.sounds = {}
        self.stream = None
        self.remaining = None

        #load supported audio formats
        exts = (".wav", ".mp3", ".flac", ".ogg")
        for fname in os.listdir(folder):
            if fname.lower().endswith(exts):
                path = os.path.join(folder, fname)
                data, sr = sf.read(path, dtype='float32')
                key = fname.lower().strip()
                self.sounds[key] = (data, sr)

    def play(self, name):
        name += ".mp3"
        key = name.lower().strip()
        if key not in self.sounds:
            print(f"Sound '{name}' not found in audio bank.")
            return False

        data, sr = self.sounds[key]

        self.total_samples = len(data)

        #prepare playback buffer
        self.remaining = np.copy(data)

        #determine channel count
        channels = data.shape[1] if data.ndim > 1 else 1

        #create a controllable OutputStream
        self.stream = sd.OutputStream(
            samplerate=sr,
            channels=channels,
            callback=self._callback
        )

        self.stream.start()
        return True

    def _callback(self, outdata, frames, time, status):
        if len(self.remaining) == 0:
            outdata[:] = np.zeros((frames, outdata.shape[1]))
            raise sd.CallbackStop

        chunk = self.remaining[:frames]

        #reshape mono audio to (frames, 1)
        if chunk.ndim == 1:
            chunk = chunk.reshape(-1, 1)

        outdata[:len(chunk)] = chunk

        if len(chunk) < frames:
            outdata[len(chunk):] = 0
            self.remaining = np.empty((0,))
        else:
            self.remaining = self.remaining[frames:]

    def is_playing(self):
        return self.stream is not None and self.stream.active

    def get_progress(self):
        if self.remaining is None or self.stream is None:
            return 0.0

        # total samples (mono or stereo)
        total = self.total_samples

        # remaining samples
        remaining = len(self.remaining)

        # fraction played
        played = 1.0 - (remaining / total)
        return max(0.0, min(1.0, played))
    
sound_player = AudioBank(sound_folder)

CONFIG_PATH = Path("animations.yaml")

def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    dialogue = raw["dialogue"]

    #map function names to actual furby methods
    fn_lookup = {
        "open_mouth": furby.open_mouth,
        "close_mouth": furby.close_mouth,
        "open_close_mouth_blink": furby.open_close_mouth_blink,
        "close_eyes": furby.close_eyes,
        #add more if needed
    }

    sequences = {}
    for key, seq in raw["sequences"].items():
        converted = []
        for timestamp, fn_name in seq:
            converted.append((timestamp, fn_lookup[fn_name]))
        sequences[key] = converted

    return dialogue, sequences

dialogue, sequences = load_config()

furby.load_sequences(sequences)

sd.default.latency = ('low', 'low')   # request smallest buffers
sd.default.blocksize = 256            # tiny block size
sd.default.channels = 1               # mono

#furby.calibrate()
#sound_player.play("awake")
furby.start_update_thread()

picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={"format": "XRGB8888", "size": (1280, 720)},
    lores={"format": "YUV420", "size": (640, 480)},
    display="main",
)

#for mode in picam2.sensor_modes:
    #print(mode)
    
picam2.configure(config)
picam2.start()

cv2.namedWindow("Emotion Detection", cv2.WND_PROP_FULLSCREEN)
cv2.setWindowProperty("Emotion Detection", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

cv2.startWindowThread()

cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_detector = cv2.CascadeClassifier(cascade_path)

# Load background
DISPLAY_W, DISPLAY_H = 1080, 1920
backgrounds = []
for i in range(28):
    img = cv2.imread(f"HUD/hud-{i}.png", cv2.IMREAD_UNCHANGED)
    #img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    img = cv2.resize(img, (DISPLAY_W, DISPLAY_H))
    backgrounds.append(img)

# Camera overlay size + position
CAM_W, CAM_H = 860, 1529
cam_x, cam_y = 110, 371

def drawline(frame, index, x,y):
    x_index = 0
    if index > 14:
        x_index = 720
    y_index = 33 + 93.3757 * (index % 14)
    #print(int(y_index))
    cv2.line(frame, (x, y), (int(x_index), int(y_index)), (255,255,255),2)#1150
def drawtext(frame, emotion):
    global dialogue
    if emotion is None:
        return
    if emotion in dialogue:
        tokens = re.split(r'( {2}|\s+)', dialogue[emotion])
        progress = sound_player.get_progress()
        progress = min(1.1*progress + 0.1, 1.0)
        num_tokens = int(len(tokens) * progress)
        text = "".join(tokens[:num_tokens])
        # Split into lines
        lines = text.split("\n")
        #print(tokens)
        #print(text)
        #print(lines)
        for i, line in enumerate(lines):
            cleaned_line = line.replace("  ", "")
            cv2.putText(frame, cleaned_line, (450,90 + i*70),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)

def process_emotion(emotion):
    global current_emotion, emotion_start_time
    now = monotonic()

    # If this is a new emotion, reset the timer
    if emotion != current_emotion:
        current_emotion = emotion
        emotion_start_time = now
        return None

    if emotion_start_time is None:
        emotion_start_time = now

    # If same emotion, check duration
    elapsed = now - emotion_start_time
    if elapsed >= HOLD_TIME:
        return emotion   # sustained emotion detected

    return None

def parse_time(tstr):
    h, m = map(int, tstr.split(":"))
    return time(hour=h, minute=m)

def time_in_window(now, start_str, end_str):
    start = parse_time(start_str)
    end   = parse_time(end_str)
    return start <= now <= end

def check_if_time_in_window():
    global active, last_activation_time

    now = datetime.now()
    today = now.strftime("%A")
    current_time = now.time()

    windows = activation_schedule.get(today, [])

    should_be_active = any(
        time_in_window(current_time, start, end)
        for start, end in windows
    )

    if should_be_active and not active:
        active = True
        last_activation_time = monotonic()
        on_activate()

    elif not should_be_active and active:
        active = False
        on_deactivate()

    if active:
        check_if_low_power(today, current_time)

def check_if_low_power(today, current_time):
    global last_activation_time, INACTIVITY_PERIOD, sleeping

    windows = low_power_schedule.get(today, [])
    
    in_sleep_window = any(
        time_in_window(current_time, start, end)
        for start, end in windows
    )

    now = monotonic()
    inactivity = False
    if now - last_activation_time > INACTIVITY_PERIOD:
        inactivity = True

    if in_sleep_window and inactivity and not sleeping:
        print(f"inactive for {INACTIVITY_PERIOD}s, sleeping...")
        sleeping = True
        furby.close_eyes()
    elif sleeping and not inactivity:
        print(f"activity detected, waking up")
        sleeping = False

    elif not in_sleep_window and sleeping:
        sleeping = False

def on_activate():
    while sound_player.is_playing():
        sleep(0.05)
    furby.calibrate()
    sound_player.play("awake")
    print("Activated")

def on_deactivate():
    while sound_player.is_playing():
        sleep(0.05)
    if sleeping:
        furby.close_mouth()
    sleep(1.0)
    sound_player.play("sleep")
    furby.load_sequence("sleep")
    furby.start_sequence()

    while sound_player.is_playing():
        sleep(0.05)
    print("Deactivated")

def plot_sleep_screen():
    frame = np.zeros((DISPLAY_H, DISPLAY_W, 3), dtype=np.uint8)
    cv2.putText(frame, "Zzzzzz", (150, 200),
        cv2.FONT_HERSHEY_SIMPLEX, 5, (255,255, 255), 6)
    cv2.imshow("Emotion Detection", frame)


while not force_shutdown:
    check_if_time_in_window()

    if not active:
        sleep(1.0)
        plot_sleep_screen()
    else:
    
        request = picam2.capture_request()
        
        index = 0
            #grayscale lores frame for detection
        try:
            sustained = None

            # ORIGINAL frame (for display)
            frame = request.make_array('main')

            # ROTATED frame (for processing)
            proc = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            proc = cv2.flip(proc, 1)
            
            # Face detection on rotated frame
            faces = face_detector.detectMultiScale(proc, 1.1, 5)

            # For each face, convert rotated coords ? original coords
            H, W = proc.shape[:2]

            dominant_emotion = [None,0.0]

            for (xp, yp, wp, hp) in faces:
                face_crop = proc[yp:yp+hp, xp:xp+wp]
                
                face_crop_bgr = cv2.cvtColor(face_crop, cv2.COLOR_BGRA2BGR)
                
                face_crop_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)
                #face_crop_rgb = np.ascontiguousarray(face_crop_rgb, dtype=np.uint8)
                #safe_img = face_crop_rgb.copy()
            
                try:
                    emotion, score = emotion_detector.top_emotion(face_crop_rgb)
                    label = f"{emotion} ({score:.2f})"

                    if hp > dominant_emotion[1]:
                        dominant_emotion[0] = emotion
                        dominant_emotion[1] = hp
                    
                    index = int(score *4)
                    if emotion == "neutral":
                        index = 0 + index
                    elif emotion == "sad":
                        index = 4 + index
                    elif emotion == "disgust":
                        index = 9 + index
                    elif emotion == "fear":
                        index = 14 + index
                    elif emotion == "angry":
                        index = 14 + index
                    elif emotion == "happy":
                        index = 18 + index
                    elif emotion == "surprise":
                        index = 23 + index
                        
                except:
                    label = "error"
                
                orig_x = xp
                orig_y = yp
                orig_w = wp
                orig_h = hp

                box_color = (150,150,150)
                box_linewidth = 1
                
                if label != "error":
                    last_activation_time = monotonic()
                    cv2.putText(proc, label, (orig_x, orig_y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                            
                    box_end = orig_x
                    if index > 14:
                        box_end = orig_x+orig_w
                    drawline(proc, index, box_end, orig_y + orig_h//2)
                    
                    box_color = (255,255,255)
                    box_linewidth = 2
                    if sustained:
                        box_color = (0,255,0)
                
                cv2.rectangle(proc,
                            (orig_x, orig_y),
                            (orig_x + orig_w, orig_y + orig_h),
                            box_color, box_linewidth)

            sustained = process_emotion(dominant_emotion[0])
            
            if sustained and not triggered:
                print("Triggered:", sustained)
                emotion = dominant_emotion[0]
                while emotion not in dialogue:
                    emotion = f"{dominant_emotion[0]}{random.randint(0,5)}"
                trigger_emotion = emotion
                sound_player.play(trigger_emotion)
                furby.load_sequence(trigger_emotion)
                furby.start_sequence()
                triggered = True
                sustained = None
            elif not sound_player.is_playing():
                triggered = False
                trigger_emotion = None

        finally:
            if active:
                request.release()

                if not sleeping:

                    # --- Composite onto background ---

                    # Scale upright camera frame
                    cam_scaled = cv2.resize(proc, (CAM_W, CAM_H))

                    # Copy background so original stays intact
                    composed = backgrounds[index].copy()

                    # Overlay scaled camera feed onto background
                    composed[cam_y:cam_y+CAM_H, cam_x:cam_x+CAM_W] = cam_scaled

                    drawtext(composed, trigger_emotion)
                    
                    # Display final composed frame
                    cv2.imshow("Emotion Detection", composed)
                else:
                    plot_sleep_screen()
                
                sleep(0.05)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()
picam2.stop()
furby.stop_update_thread()
print("Exited loop cleanly.")
sys.exit(0)
