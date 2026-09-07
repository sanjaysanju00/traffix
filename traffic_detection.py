import cv2
import time
import requests
import serial
import statistics
import uuid

from collections import deque
from ultralytics import YOLO


# ============================================================
# CONFIGURATION
# ============================================================

ARDUINO_PORT = "COM7"

ARDUINO_BAUDRATE = 9600

SERVER_URL = (
    "https://smart-traffic-system-c36o.onrender.com/update_traffic"
)

# Send traffic information to Render every 2 seconds.
SERVER_UPDATE_INTERVAL = 2.0

# Number of camera frames used for vehicle-count smoothing.
SMOOTHING_FRAMES = 7

# Number of consecutive calculated statuses required
# before accepting a new traffic status.
STATUS_CONFIRMATION_COUNT = 3

# YOLO confidence.
YOLO_CONFIDENCE = 0.35

# Camera.
CAMERA_INDEX = 0


# ============================================================
# VEHICLE CLASSES
# ============================================================

# COCO classes:
#
# 2  = car
# 3  = motorcycle
# 5  = bus
# 7  = truck

VEHICLE_CLASSES = {
    2,
    3,
    5,
    7
}


# ============================================================
# TRAFFIC STATUS
# ============================================================

def calculate_status(vehicle_count):

    # --------------------------------------------------------
    # NORMAL
    # --------------------------------------------------------

    if vehicle_count <= 3:

        return "NORMAL"

    # --------------------------------------------------------
    # MODERATE
    # --------------------------------------------------------

    elif vehicle_count <= 6:

        return "MODERATE"

    # --------------------------------------------------------
    # HEAVY
    # --------------------------------------------------------

    else:

        return "HEAVY"


# ============================================================
# ARDUINO
# ============================================================

arduino = None


try:

    arduino = serial.Serial(
        ARDUINO_PORT,
        ARDUINO_BAUDRATE,
        timeout=1
    )

    time.sleep(2)

    print("==========================================")
    print(
        f"✅ Arduino connected: {ARDUINO_PORT}"
    )
    print("==========================================")

except Exception as e:

    print("==========================================")
    print("⚠️ Arduino connection failed")
    print(
        f"   {e}"
    )
    print("==========================================")

    arduino = None


# ============================================================
# SEND STATUS TO ARDUINO
# ============================================================

def send_to_arduino(status):

    if arduino is None:

        return

    try:

        arduino.write(
            (status + "\n").encode()
        )

        print(
            f"🔴 Arduino: {status}"
        )

    except Exception as e:

        print(
            "⚠️ Arduino send error:",
            e
        )


# ============================================================
# LOAD YOLO
# ============================================================

print("Loading YOLO model...")

model = YOLO(
    "yolo11n.pt"
)

print("✅ YOLO model loaded")


# ============================================================
# START CAMERA
# ============================================================

camera = cv2.VideoCapture(
    CAMERA_INDEX
)

if not camera.isOpened():

    print(
        "❌ Camera could not be opened."
    )

    if arduino:

        arduino.close()

    raise SystemExit


print("✅ Camera started")


# ============================================================
# UNIQUE DETECTOR SESSION
#
# Every time this program starts, a new source_id is created.
# This lets Render recognize that sequence numbers belong to
# this particular detector session.
# ============================================================

SOURCE_ID = str(
    uuid.uuid4()
)

sequence = 0


# ============================================================
# VARIABLES
# ============================================================

count_history = deque(
    maxlen=SMOOTHING_FRAMES
)

confirmed_status = "NORMAL"

candidate_status = None

candidate_count = 0

last_server_update = 0

last_sent_status = None

last_sent_vehicle_count = None


# ============================================================
# START MESSAGE
# ============================================================

print("")
print("==========================================")
print("🚦 SMART TRAFFIC DETECTION STARTED")
print("==========================================")
print("")
print(
    f"Count smoothing: {SMOOTHING_FRAMES} frames"
)
print(
    f"Status confirmation: "
    f"{STATUS_CONFIRMATION_COUNT} cycles"
)
print(
    f"Render update: every "
    f"{SERVER_UPDATE_INTERVAL} seconds"
)
print("")
print(
    "Notifications are sent ONLY when the "
    "confirmed status changes."
)
print("")
print("Press Q to stop.")
print("")


# ============================================================
# INITIAL ARDUINO STATUS
# ============================================================

send_to_arduino(
    "NORMAL"
)


# ============================================================
# MAIN LOOP
# ============================================================

try:

    while True:

        success, frame = camera.read()

        if not success:

            print(
                "⚠️ Camera frame could not be read."
            )

            time.sleep(0.1)

            continue

        # ----------------------------------------------------
        # YOLO DETECTION
        # ----------------------------------------------------

        results = model(
            frame,
            conf=YOLO_CONFIDENCE,
            verbose=False
        )

        raw_vehicle_count = 0

        # ----------------------------------------------------
        # Count vehicles
        # ----------------------------------------------------

        for result in results:

            if result.boxes is None:

                continue

            for box in result.boxes:

                class_id = int(
                    box.cls[0]
                )

                if class_id in VEHICLE_CLASSES:

                    raw_vehicle_count += 1

        # ----------------------------------------------------
        # Add raw count to smoothing history
        # ----------------------------------------------------

        count_history.append(
            raw_vehicle_count
        )

        # ----------------------------------------------------
        # Median smoothing
        # ----------------------------------------------------

        if len(count_history) > 0:

            smoothed_count = int(
                round(
                    statistics.median(
                        count_history
                    )
                )
            )

        else:

            smoothed_count = 0

        # ----------------------------------------------------
        # Calculate candidate status
        # ----------------------------------------------------

        calculated_status = calculate_status(
            smoothed_count
        )

        # ----------------------------------------------------
        # STATUS CONFIRMATION
        #
        # A new status must appear 3 consecutive
        # processing cycles before becoming confirmed.
        # ----------------------------------------------------

        if calculated_status == confirmed_status:

            candidate_status = None

            candidate_count = 0

        else:

            if calculated_status == candidate_status:

                candidate_count += 1

            else:

                candidate_status = calculated_status

                candidate_count = 1

            # ------------------------------------------------
            # Confirm new status
            # ------------------------------------------------

            if candidate_count >= STATUS_CONFIRMATION_COUNT:

                confirmed_status = (
                    calculated_status
                )

                candidate_status = None

                candidate_count = 0

                print("")
                print(
                    "=========================================="
                )

                print(
                    f"✅ CONFIRMED STATUS: "
                    f"{confirmed_status}"
                )

                print(
                    "=========================================="
                )

                # --------------------------------------------
                # Arduino changes immediately
                # --------------------------------------------

                send_to_arduino(
                    confirmed_status
                )

        # ----------------------------------------------------
        # SEND TO RENDER
        #
        # Only one request can be active at a time because
        # requests.post() completes before the loop continues.
        #
        # This prevents a pile-up of overlapping requests.
        # ----------------------------------------------------

        current_time = time.time()

        if (
            current_time - last_server_update
            >= SERVER_UPDATE_INTERVAL
        ):

            sequence += 1

            payload = {

                "vehicle_count":
                    smoothed_count,

                "traffic_status":
                    confirmed_status,

                "source_id":
                    SOURCE_ID,

                "sequence":
                    sequence
            }

            try:

                response = requests.post(

                    SERVER_URL,

                    json=payload,

                    timeout=8
                )

                last_server_update = (
                    time.time()
                )

                # ------------------------------------------------
                # Server response
                # ------------------------------------------------

                if response.ok:

                    try:

                        response_data = (
                            response.json()
                        )

                    except Exception:

                        response_data = {}

                    ignored = response_data.get(
                        "ignored",
                        False
                    )

                    if ignored:

                        print(
                            f"⏭️ Render ignored old "
                            f"request #{sequence}"
                        )

                    else:

                        print(
                            f"🌐 Render: "
                            f"{confirmed_status} | "
                            f"Vehicles: "
                            f"{smoothed_count}"
                        )

                else:

                    print(
                        f"⚠️ Render returned "
                        f"HTTP {response.status_code}"
                    )

            except requests.exceptions.Timeout:

                last_server_update = (
                    time.time()
                )

                print(
                    "⚠️ Render request timed out."
                )

            except requests.exceptions.RequestException as e:

                last_server_update = (
                    time.time()
                )

                print(
                    "⚠️ Render request failed:",
                    e
                )

            except Exception as e:

                last_server_update = (
                    time.time()
                )

                print(
                    "⚠️ Unexpected Render error:",
                    e
                )

        # ----------------------------------------------------
        # DISPLAY INFORMATION ON CAMERA
        # ----------------------------------------------------

        display_text = (
            f"Vehicles: {smoothed_count}"
        )

        status_text = (
            f"Traffic: {confirmed_status}"
        )

        cv2.putText(

            frame,

            display_text,

            (20, 40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 0),

            2
        )

        cv2.putText(

            frame,

            status_text,

            (20, 80),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 255),

            2
        )

        # ----------------------------------------------------
        # SHOW FRAME
        # ----------------------------------------------------

        cv2.imshow(
            "Smart Traffic Detection",
            frame
        )

        # ----------------------------------------------------
        # Q TO EXIT
        # ----------------------------------------------------

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):

            print("")
            print(
                "🛑 Q pressed. Stopping..."
            )

            break


# ============================================================
# CLEANUP
# ============================================================

except KeyboardInterrupt:

    print("")
    print(
        "🛑 Program interrupted."
    )


finally:

    camera.release()

    cv2.destroyAllWindows()

    if arduino is not None:

        try:

            arduino.close()

        except Exception:

            pass

    print("")
    print("==========================================")
    print(
        "✅ Smart Traffic Detection stopped"
    )
    print("==========================================")