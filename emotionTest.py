#!/usr/bin/python3
import cv2
from picamera2 import Picamera2, MappedArray
from fer.fer import FER
import time

# Emotion detector (FER uses a CNN trained on FER2013)
emotion_detector = FER(mtcnn=True)

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
    if index < 14:
        x_index = 720
    y_index = 33.9529 + 93.3757 * (index % 14)
    #print(int(y_index))
    cv2.line(frame, (x, y), (int(y_index), x_index), (255,255,255),2)#1150

while True:
    request = picam2.capture_request()
    
    index = 0
        #grayscale lores frame for detection
    try:
        # ORIGINAL frame (for display)
        frame = request.make_array('main')

        # ROTATED frame (for processing)
        proc = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        proc = cv2.flip(proc, 1)
        
        # Face detection on rotated frame
        faces = face_detector.detectMultiScale(proc, 1.1, 5)

        # For each face, convert rotated coords ? original coords
        H, W = proc.shape[:2]
        
        for (xp, yp, wp, hp) in faces:
            face_crop = proc[yp:yp+hp, xp:xp+wp]
            
            face_crop_bgr = cv2.cvtColor(face_crop, cv2.COLOR_BGRA2BGR)
            
            face_crop_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)
            print(face_crop_rgb.shape)
        
            try:
                emotion, score = emotion_detector.top_emotion(face_crop_rgb)
                label = f"{emotion} ({score:.2f})"
                
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
            
            """
            orig_x = yp
            orig_y = H - (xp + wp)
            orig_w = hp
            orig_h = wp

            box_color = (150,150,150)
            
            if label != "error":
                cv2.putText(proc, label, (orig_x, orig_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                        
                box_end = orig_y
                if index < 14:
                    box_end = orig_y+orig_h
                drawline(proc, index, orig_x + orig_w//2, box_end)
                
                box_color = (255,255,255)
            
            cv2.rectangle(proc,
                          (orig_x, orig_y),
                          (orig_x + orig_w, orig_y + orig_h),
                          box_color, 2)
            """
    finally:
        request.release()

        # --- Composite onto background ---

        # Scale upright camera frame
        cam_scaled = cv2.resize(proc, (CAM_W, CAM_H))

        # Copy background so original stays intact
        composed = backgrounds[index].copy()

        # Overlay scaled camera feed onto background
        composed[cam_y:cam_y+CAM_H, cam_x:cam_x+CAM_W] = cam_scaled
        
        
        # Display final composed frame
        cv2.imshow("Emotion Detection", composed)
        
        time.sleep(0.05)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()
picam2.stop()
