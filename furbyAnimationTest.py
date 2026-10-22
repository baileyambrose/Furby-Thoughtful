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

last_animation = None

sound_folder = "/home/bailey/Furby-Thoughtful/sounds/"


class FurbyMotor:
    def __init__(self, motor_pin_dir1, motor_pin_dir2, enable_pin, button_pin):
        # Motor(IN1, IN2, enable=EN)
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
        #Runs update() in a background thread at a fixed interval.

        if self._update_thread is not None:
            return  # already running

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
            if elapsed > 0.3:
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
                # Manual brake: both inputs HIGH
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

            # If finished
            if self.sequence_index >= len(self.sequence):
                self.sequence_active = False
                print("Sequence finished")

furby = FurbyMotor(20,21,16,12)

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

CONFIG_PATH = Path("/home/bailey/Furby-Thoughtful/animations.yaml")

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
furby.calibrate()
print("Type an animation name to run it.")
print("Available animations:", ", ".join(sequences.keys()))
while True:
    name = input("\nAnimation> ").strip()

    if name.lower() in ("quit", "exit", "q"):
        break

    if name == "" and last_animation is not None:
        name = last_animation

    if name in dialogue:
        print(dialogue[name])

        sound_player.play(name)
        furby.load_sequence(name)
        furby.start_sequence()
        last_animation = name
        while sound_player.is_playing():
            sleep(0.05)
    else:
        print(f"animation {name} not found")

furby.stop_update_thread()
