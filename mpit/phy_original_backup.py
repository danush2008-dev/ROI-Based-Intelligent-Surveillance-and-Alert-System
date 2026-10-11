import os
import cv2
import torch
import numpy as np
import pygame
import warnings
import smtplib
import ssl
from email.message import EmailMessage

from datetime import datetime
warnings.filterwarnings("ignore")

SENDER_EMAIL    = "rahangdalefarishta@gmail.com"       
SENDER_PASSWORD = "ikyxbzoiwminkvbw"     
RECEIVER_EMAIL  = "farishta.rahangdale2024@vitstudent.ac.in"  

EMAIL_COOLDOWN_SECONDS = 30

last_email_time = None

path_alarm = "Alarm/alarm.wav"

pygame.init()

audio_available = False

try:
    pygame.mixer.init()
    pygame.mixer.music.load(path_alarm)
    audio_available = True
    print("Audio mixer initialized successfully.")
except pygame.error as e:
    print("Audio unavailable:", e)
# Loading the model
model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
cap = cv2.VideoCapture("input vedio for testing.mp4")
#if u want to test in real time, replace file name with 0 for WebCam
target_classes = ['car', 'bus', 'truck', 'person']
count = 0
number_of_photos = 3
# Polygon points
pts = []
# Function to draw polygon (roi)
def draw_polygon(event, x, y, flags, param):
    global pts
    if event == cv2.EVENT_LBUTTONDOWN:
        print(x, y)
        pts.append([x, y])
    elif event == cv2.EVENT_RBUTTONDOWN:
        pts = []
# Function to check if a point is inside a polygon
def inside_polygon(point, polygon):
    result = cv2.pointPolygonTest(polygon, (point[0], point[1]), False)
    if result == 1:
        return True
    else:
        return False
def send_email_alert(image_path):
    """
    Sends an email alert with the intruder detection image attached.
    Args:
        image_path (str): Absolute path to the saved detection image.
    Uses Gmail SMTP over SSL (port 465).
    The global `last_email_time` flag is updated after a successful send
    so that the cooldown logic in the main loop works correctly.
    """
    global last_email_time
    detection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = EmailMessage()
    msg["Subject"] = "Intruder Alert"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER_EMAIL
    msg.set_content(
        f"WARNING: A person was detected inside the restricted zone.\n\n"
        f"Detection timestamp : {detection_time}\n"
        f"Saved image path    : {image_path}\n\n"
        f"Please review the attached image immediately."
    )
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            img_data = img_file.read()

        msg.add_attachment(
            img_data,
            maintype="image",
            subtype="jpeg",
            filename=os.path.basename(image_path)
        )
    else:
        print(f"[EMAIL] Warning: image not found at {image_path}, sending without attachment.")
    try:
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl_context) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        last_email_time = datetime.now()
        print(f"[EMAIL] Alert sent successfully at {detection_time}")
    except smtplib.SMTPAuthenticationError:
        print("[EMAIL] Authentication failed. Check SENDER_EMAIL and SENDER_PASSWORD.")
    except Exception as e:
        print(f"[EMAIL] Failed to send email: {e}")
cv2.namedWindow('Video')
cv2.setMouseCallback('Video', draw_polygon)
def preprocess(img):
    height, width = img.shape[:2]
    ratio = height / width
    img = cv2.resize(img, (640, int(640 * ratio)))
    return img
while True:
    ret, frame = cap.read()

    if not ret:
        print("Video ended or frame could not be read.")
        break

    frame_detected = frame.copy()
    frame = preprocess(frame)
    results = model(frame)
    for index, row in results.pandas().xyxy[0].iterrows():
        center_x = None
        center_y = None
        if row['name'] in target_classes:
            name = str(row['name'])
            x1 = int(row['xmin'])
            y1 = int(row['ymin'])
            x2 = int(row['xmax'])
            y2 = int(row['ymax'])
            center_x = int((x1 + x2) / 2)
            center_y = int((y1 + y2) / 2)
            # Draw bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 3)
            # Write name
            cv2.putText(frame, name, (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
            # Draw center
            cv2.circle(frame, (center_x, center_y), 5, (0, 0, 255), -1)
        # Drawing the polygon
        if len(pts) >= 4:
            frame_copy = frame.copy()
            cv2.fillPoly(frame_copy, np.array([pts]), (0, 255, 0))
            frame = cv2.addWeighted(frame_copy, 0.1, frame, 0.9, 0)
            if center_x is not None and center_y is not None:
                # Checking if the center of the object is inside the polygon and if the object is a person
                if inside_polygon((center_x, center_y), np.array([pts])) and name == 'person':
                    mask = np.zeros_like(frame)
                    points = np.array([[x1, y1], [x1, y2], [x2, y2], [x2, y1]])
                    points = points.reshape((-1, 1, 2))
                    mask = cv2.fillPoly(mask, [points], (255, 255, 255))
                    saved_image_path = None          # ← NEW: track the path for the email
                    if count < number_of_photos:
                        print("Trying to save image...")
                        save_dir = os.path.join(os.getcwd(), "detected_photos")
                        if not os.path.exists(save_dir):
                            os.makedirs(save_dir)
                        # Get current timestamp
                        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                        file_path = os.path.join(save_dir, f"detected_{timestamp}.jpg")
                        print("Saving to:", file_path)
                        saved = cv2.imwrite(file_path, frame)
                        print("Saved:", saved)
                        saved_image_path = file_path  
                    if audio_available and not pygame.mixer.music.get_busy():
                        pygame.mixer.music.play()
                   
                    seconds_since_last = (
                        (datetime.now() - last_email_time).total_seconds()
                        if last_email_time is not None
                        else EMAIL_COOLDOWN_SECONDS + 1   
                    )
                    if seconds_since_last >= EMAIL_COOLDOWN_SECONDS:
                        
                        email_image = saved_image_path or os.path.join(
                            os.getcwd(), "detected_photos",
                            sorted(os.listdir(os.path.join(os.getcwd(), "detected_photos")))[-1]
                        ) if os.path.isdir(os.path.join(os.getcwd(), "detected_photos")) else None
                        if email_image:
                            send_email_alert(email_image)   
                        else:
                            print("[EMAIL] No image available to attach yet; skipping email.")
                    cv2.putText(frame, "Target", (center_x, center_y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    cv2.putText(frame, "Person Detected", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                    count += 1
    cv2.imshow("Video", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()
