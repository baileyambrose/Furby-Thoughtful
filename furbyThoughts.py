#!/usr/bin/python3
import cv2
from picamera2 import Picamera2, MappedArray
from fer.fer import FER
import time
import numpy as np

import os
from gpiozero import Motor, Button
from time import sleep
import sounddevice as sd
import soundfile as sf
import re

# Emotion detector (FER uses a CNN trained on FER2013)
emotion_detector = FER(mtcnn=False)
current_emotion = None
emotion_start_time = None
HOLD_TIME = 1.0   
triggered = False

trigger_emotion = None

sound_folder = "sounds/"

dialogue = {"neutral0":"You look so\nbored",
            "happy0":"You look happy!\nI'm happy you're\nhappy!"}

class AudioBank:
    def __init__(self, folder):
        self.sounds = {}
        self.stream = None
        self.remaining = None

        # Load supported audio formats
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

        # Prepare playback buffer
        self.remaining = np.copy(data)

        # Determine channel count
        channels = data.shape[1] if data.ndim > 1 else 1

        # Create a controllable OutputStream
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

sd.default.latency = ('low', 'low')   # request smallest buffers
sd.default.blocksize = 256            # tiny block size
sd.default.channels = 1               # mono

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
        tokens = re.split(r'(\s+)', dialogue[emotion])
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
            cv2.putText(frame, line, (450,90 + i*70),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)

def process_emotion(emotion):
    global current_emotion, emotion_start_time

    # If this is a new emotion, reset the timer
    if emotion != current_emotion:
        current_emotion = emotion
        emotion_start_time = time.time()
        return None

    if emotion_start_time is None:
        emotion_start_time = time.time()

    # If same emotion, check duration
    elapsed = time.time() - emotion_start_time
    if elapsed >= HOLD_TIME:
        return emotion   # sustained emotion detected

    return None

while True:
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

            sound_player.play(f"{dominant_emotion[0]}0")
            trigger_emotion = f"{dominant_emotion[0]}0"
            triggered = True
            sustained = None
        elif not sound_player.is_playing():
            triggered = False
            trigger_emotion = None

    finally:
        request.release()

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
        
        time.sleep(0.05)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()
picam2.stop()
