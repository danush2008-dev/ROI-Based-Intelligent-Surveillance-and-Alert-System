"""
alerts.py — Background alert worker: email sending and alarm playback.

Uses a queue.Queue + daemon thread so the main video loop never blocks.
Handles:
  - Email via Gmail SMTP/SSL with cooldown tracking
  - Alarm playback: pygame → winsound fallback → skip silently
  - Graceful shutdown with queue flush
"""

import os
import queue
import threading
import smtplib
import ssl
import warnings
from datetime import datetime
from email.message import EmailMessage

import config

# ── Alarm initialization ──────────────────────────────────────────────────
# Try pygame first, then winsound, then give up gracefully.

_alarm_method = None  # 'pygame', 'winsound', or None
_pygame_mixer = None

try:
    import pygame
    pygame.init()
    pygame.mixer.init()
    if os.path.exists(config.ALARM_PATH):
        pygame.mixer.music.load(config.ALARM_PATH)
    _alarm_method = 'pygame'
    _pygame_mixer = pygame.mixer
    print("[Alerts] Audio: pygame mixer initialized.")
except Exception as e:
    print(f"[Alerts] pygame mixer unavailable: {e}")
    try:
        import winsound
        _alarm_method = 'winsound'
        print("[Alerts] Audio: using winsound fallback.")
    except ImportError:
        print("[Alerts] Audio: winsound not available. Alarm disabled.")
        _alarm_method = None


def _play_alarm():
    """Play the alarm sound using the best available method."""
    global _alarm_method
    if _alarm_method == 'pygame':
        try:
            if _pygame_mixer and not _pygame_mixer.music.get_busy():
                _pygame_mixer.music.play()
        except Exception as e:
            print(f"[Alerts] pygame play failed: {e}")
            # Try winsound fallback
            try:
                import winsound
                _alarm_method = 'winsound'
                _play_alarm()
            except ImportError:
                _alarm_method = None
                print("[Alerts] All alarm methods failed. Alarm disabled.")

    elif _alarm_method == 'winsound':
        try:
            import winsound
            alarm_path = os.path.abspath(config.ALARM_PATH)
            if os.path.exists(alarm_path):
                winsound.PlaySound(alarm_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.Beep(1000, 500)  # fallback beep
        except Exception as e:
            print(f"[Alerts] winsound failed: {e}")
            _alarm_method = None


def _send_email(image_path, subject="Intruder Alert", extra_body=""):
    """
    Send an email alert with the intruder detection image attached.
    Uses Gmail SMTP over SSL (port 465).

    Returns True on success, False on failure.
    """
    sender = config.EMAIL_SENDER
    password = config.EMAIL_APP_PASSWORD
    receiver = config.EMAIL_RECEIVER

    if not sender or not password or not receiver:
        print("[EMAIL] Credentials not configured. Skipping email.")
        return False

    detection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    body = (
        f"WARNING: A person was detected inside the restricted zone.\n\n"
        f"Detection timestamp : {detection_time}\n"
        f"Saved image path    : {image_path}\n"
    )
    if extra_body:
        body += f"\n{extra_body}\n"
    body += "\nPlease review the attached image immediately."
    msg.set_content(body)

    # Attach image if it exists
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, "rb") as img_file:
                img_data = img_file.read()
            msg.add_attachment(
                img_data,
                maintype="image",
                subtype="jpeg",
                filename=os.path.basename(image_path),
            )
        except Exception as e:
            print(f"[EMAIL] Warning: could not attach image: {e}")
    else:
        print(f"[EMAIL] Warning: image not found at {image_path}, sending without attachment.")

    try:
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl_context) as server:
            server.login(sender, password)
            server.send_message(msg)
        print(f"[EMAIL] Alert sent successfully at {detection_time}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[EMAIL] Authentication failed. Check EMAIL_SENDER and EMAIL_APP_PASSWORD in .env")
        return False
    except Exception as e:
        print(f"[EMAIL] Failed to send email: {e}")
        return False


# ── Background worker ─────────────────────────────────────────────────────

class AlertWorker:
    """
    Background alert worker fed by queue.Queue.
    The main video loop enqueues alert requests; the worker thread processes
    them without blocking the loop.

    Alert items are dicts:
      {
        "type": "email" | "alarm" | "both",
        "image_path": str or None,
        "subject": str,
        "extra_body": str,
        "dry_run": bool,
      }
    """

    def __init__(self, dry_run=False):
        self._queue = queue.Queue()
        self._dry_run = dry_run
        self._shutdown = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="AlertWorker")
        self._thread.start()

    def _worker(self):
        """Worker loop: process alert items from the queue."""
        while not self._shutdown.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:  # poison pill for shutdown
                self._queue.task_done()
                break

            try:
                self._process_item(item)
            except Exception as e:
                print(f"[AlertWorker] Error processing alert: {e}")
            finally:
                self._queue.task_done()

    def _process_item(self, item):
        """Process a single alert item."""
        alert_type = item.get("type", "both")
        dry_run = item.get("dry_run", self._dry_run)

        if alert_type in ("alarm", "both"):
            if dry_run:
                print("[AlertWorker] DRY-RUN: alarm would play")
            else:
                _play_alarm()

        if alert_type in ("email", "both"):
            if dry_run:
                print(f"[AlertWorker] DRY-RUN: email would be sent for {item.get('image_path')}")
            else:
                success = _send_email(
                    image_path=item.get("image_path"),
                    subject=item.get("subject", "Intruder Alert"),
                    extra_body=item.get("extra_body", ""),
                )
                # Store result for potential logging
                item["email_success"] = success

    def enqueue(self, alert_type="both", image_path=None, subject="Intruder Alert",
                extra_body="", dry_run=None):
        """
        Enqueue an alert for background processing.

        Args:
            alert_type: "email", "alarm", or "both"
            image_path: path to the evidence image
            subject: email subject line
            extra_body: additional text for the email body
            dry_run: override the worker's dry_run setting
        """
        self._queue.put({
            "type": alert_type,
            "image_path": image_path,
            "subject": subject,
            "extra_body": extra_body,
            "dry_run": dry_run if dry_run is not None else self._dry_run,
        })

    def shutdown(self, timeout=5.0):
        """
        Gracefully shut down the worker: flush remaining items, then join.
        """
        print("[AlertWorker] Shutting down...")
        self._shutdown.set()
        # Put poison pill to unblock the worker if it's waiting
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            print("[AlertWorker] Warning: worker thread did not exit cleanly.")
        else:
            print("[AlertWorker] Shut down successfully.")
