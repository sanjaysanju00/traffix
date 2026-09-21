import cv2
import time
import statistics
import threading
import queue
import uuid

import requests

import serial

from ultralytics import YOLO


# =========================================================
# CONFIGURATION
# =========================================================

MODEL_PATH = "yolo11n.pt"

CAMERA_INDEX = 0


# ---------------------------------------------------------
# RENDER SERVER
# ---------------------------------------------------------

SERVER_URL = (
    "https://smart-traffic-system-c36o.onrender.com"
    "/update_traffic"
)


# ---------------------------------------------------------
# ARDUINO
# ---------------------------------------------------------

ARDUINO_PORT = "COM7"

ARDUINO_BAUD_RATE = 9600


# ---------------------------------------------------------
# YOLO VEHICLE CLASSES
# ---------------------------------------------------------

VEHICLE_CLASSES = {

    "car",

    "motorcycle",

    "bus",

    "truck"

}


# =========================================================
# TRAFFIC THRESHOLDS
# =========================================================

# 0 - 3 vehicles
# NORMAL

# 4 - 6 vehicles
# MODERATE

# 7+ vehicles
# HEAVY

NORMAL_MAX = 3

MODERATE_MAX = 6


# =========================================================
# SMOOTHING
# =========================================================

SMOOTHING_FRAMES = 7


STATUS_CONFIRMATION_COUNT = 3


# =========================================================
# SERVER UPDATE
# =========================================================
#
# This is how often the latest traffic state is sent
# to Render.
#
# IMPORTANT:
# The HTTP request happens in a separate thread.
# Therefore YOLO does NOT wait for Render.
#

SERVER_UPDATE_INTERVAL = 1.0


# =========================================================
# HTTP TIMEOUT
# =========================================================

SERVER_TIMEOUT = 3


# =========================================================
# CREATE UNIQUE DETECTOR ID
# =========================================================

SOURCE_ID = str(
    uuid.uuid4()
)


# =========================================================
# GLOBAL STATE
# =========================================================

latest_update = None

update_lock = threading.Lock()


stop_sender = False


sequence_number = 0


# =========================================================
# HTTP SESSION
# =========================================================

http_session = requests.Session()


# =========================================================
# SEND LATEST TRAFFIC TO RENDER
# =========================================================

def render_sender():

    global latest_update

    global stop_sender


    print(
        "🌐 Render sender thread started."
    )


    last_sent_signature = None

    last_send_time = 0


    while not stop_sender:

        update = None


        # -------------------------------------------------
        # GET LATEST UPDATE
        # -------------------------------------------------

        with update_lock:

            if latest_update is not None:

                update = latest_update.copy()


        if update is None:

            time.sleep(
                0.1
            )

            continue


        current_time = time.time()


        # -------------------------------------------------
        # SEND EVERY SERVER_UPDATE_INTERVAL
        # -------------------------------------------------

        if (
            current_time -
            last_send_time
            <
            SERVER_UPDATE_INTERVAL
        ):

            time.sleep(
                0.05
            )

            continue


        signature = (

            update["traffic_status"],

            update["vehicle_count"],

            update["sequence"]

        )


        # -------------------------------------------------
        # SEND
        # -------------------------------------------------

        try:

            response = (
                http_session.post(

                    SERVER_URL,

                    json=update,

                    timeout=SERVER_TIMEOUT

                )
            )


            last_send_time = (
                time.time()
            )


            if response.ok:

                try:

                    result = (
                        response.json()
                    )

                except Exception:

                    result = {}


                if result.get(
                    "ignored"
                ):

                    print(
                        "🌐 Render: "
                        "old update ignored."
                    )

                else:

                    print(
                        "🌐 Render: "
                        f"{update['traffic_status']} | "
                        f"Vehicles: "
                        f"{update['vehicle_count']} | "
                        f"Seq: "
                        f"{update['sequence']}"
                    )


            else:

                print(
                    "⚠️ Render returned HTTP "
                    f"{response.status_code}"
                )


        except requests.exceptions.Timeout:

            last_send_time = (
                time.time()
            )

            print(
                "⚠️ Render request timed out."
                " Camera continues normally."
            )


        except requests.exceptions.RequestException as error:

            last_send_time = (
                time.time()
            )

            print(
                "⚠️ Render connection error:"
            )

            print(
                error
            )


        except Exception as error:

            last_send_time = (
                time.time()
            )

            print(
                "⚠️ Render update error:"
            )

            print(
                error
            )


        time.sleep(
            0.05
        )


    print(
        "🌐 Render sender thread stopped."
    )


# =========================================================
# QUEUE LATEST SERVER UPDATE
# =========================================================

def queue_render_update(
    traffic_status,
    vehicle_count,
    sequence
):

    global latest_update


    data = {

        "vehicle_count":
            int(vehicle_count),

        "traffic_status":
            traffic_status,

        "source_id":
            SOURCE_ID,

        "sequence":
            sequence

    }


    with update_lock:

        # -------------------------------------------------
        # IMPORTANT:
        #
        # We keep ONLY the newest update.
        #
        # If internet is slow, the program does not
        # build a huge queue of old traffic states.
        # -------------------------------------------------

        latest_update = data


# =========================================================
# CLASSIFY TRAFFIC
# =========================================================

def classify_traffic(
    vehicle_count
):

    if vehicle_count <= NORMAL_MAX:

        return "NORMAL"


    elif vehicle_count <= MODERATE_MAX:

        return "MODERATE"


    else:

        return "HEAVY"


# =========================================================
# ARDUINO SETUP
# =========================================================

arduino = None


try:

    arduino = serial.Serial(

        ARDUINO_PORT,

        ARDUINO_BAUD_RATE,

        timeout=1

    )


    time.sleep(2)


    print(
        "======================================"
    )

    print(
        f"Arduino connected: {ARDUINO_PORT}"
    )

    print(
        "======================================"
    )


except Exception as error:

    print(
        "⚠️ Arduino connection failed:"
    )

    print(
        error
    )

    print(
        "Continuing without Arduino..."
    )


# =========================================================
# SEND STATUS TO ARDUINO
# =========================================================

def send_to_arduino(
    traffic_status
):

    if arduino is None:

        return


    try:

        command = (
            traffic_status
            + "\n"
        )


        arduino.write(
            command.encode()
        )


        print(
            f"🔌 Arduino: "
            f"{traffic_status}"
        )


    except Exception as error:

        print(
            "⚠️ Arduino send error:"
        )

        print(
            error
        )


# =========================================================
# LOAD YOLO MODEL
# =========================================================

print(
    "Loading YOLO model..."
)


model = YOLO(
    MODEL_PATH
)


print(
    "YOLO model loaded."
)


# =========================================================
# OPEN CAMERA
# =========================================================

cap = cv2.VideoCapture(
    CAMERA_INDEX
)


if not cap.isOpened():

    print(
        "❌ Could not open camera."
    )

    if arduino:

        arduino.close()

    raise SystemExit


print(
    "📷 Camera started."
)


# =========================================================
# START RENDER THREAD
# =========================================================

sender_thread = threading.Thread(

    target=render_sender,

    daemon=True

)


sender_thread.start()


# =========================================================
# TRAFFIC SMOOTHING DATA
# =========================================================

recent_counts = []


candidate_status = None

candidate_count = 0


confirmed_status = "NORMAL"


# =========================================================
# INITIAL SERVER UPDATE
# =========================================================

sequence_number += 1


queue_render_update(

    confirmed_status,

    0,

    sequence_number

)


# =========================================================
# MAIN CAMERA LOOP
# =========================================================

try:

    while True:

        success, frame = (
            cap.read()
        )


        if not success:

            print(
                "⚠️ Camera frame could not be read."
            )

            time.sleep(
                0.1
            )

            continue


        # -------------------------------------------------
        # YOLO DETECTION
        # -------------------------------------------------

        results = model(
            frame,
            verbose=False
        )


        raw_vehicle_count = 0


        # -------------------------------------------------
        # COUNT VEHICLES
        # -------------------------------------------------

        for result in results:

            if result.boxes is None:

                continue


            for box in result.boxes:

                class_id = int(
                    box.cls[0]
                )


                class_name = (
                    model.names[class_id]
                    .lower()
                )


                if class_name in VEHICLE_CLASSES:

                    raw_vehicle_count += 1


        # -------------------------------------------------
        # SMOOTH VEHICLE COUNT
        # -------------------------------------------------

        recent_counts.append(
            raw_vehicle_count
        )


        if len(recent_counts) > SMOOTHING_FRAMES:

            recent_counts.pop(0)


        smoothed_count = int(
            statistics.median(
                recent_counts
            )
        )


        # -------------------------------------------------
        # CLASSIFY TRAFFIC
        # -------------------------------------------------

        detected_status = (
            classify_traffic(
                smoothed_count
            )
        )


        print(
            f"Raw: {raw_vehicle_count} | "
            f"Smooth: {smoothed_count} | "
            f"Detected: {detected_status}"
        )


        # -------------------------------------------------
        # STATUS CONFIRMATION
        # -------------------------------------------------
        #
        # A status must appear consistently for several
        # frames before it becomes confirmed.
        #
        # This prevents:
        #
        # NORMAL
        # HEAVY
        # NORMAL
        # HEAVY
        #
        # caused by a single YOLO counting fluctuation.
        #

        if detected_status == candidate_status:

            candidate_count += 1


        else:

            candidate_status = (
                detected_status
            )

            candidate_count = 1


        # -------------------------------------------------
        # CONFIRM STATUS
        # -------------------------------------------------

        if (
            candidate_count
            >=
            STATUS_CONFIRMATION_COUNT
        ):

            if (
                candidate_status
                !=
                confirmed_status
            ):

                confirmed_status = (
                    candidate_status
                )


                print(
                    "======================================"
                )

                print(
                    "CONFIRMED STATUS: "
                    f"{confirmed_status}"
                )

                print(
                    f"Vehicles: "
                    f"{smoothed_count}"
                )

                print(
                    "======================================"
                )


                # -----------------------------------------
                # ARDUINO
                # -----------------------------------------

                send_to_arduino(
                    confirmed_status
                )


                # -----------------------------------------
                # RENDER
                # -----------------------------------------

                sequence_number += 1


                queue_render_update(

                    confirmed_status,

                    smoothed_count,

                    sequence_number

                )


        # -------------------------------------------------
        # KEEP RENDER UPDATED WITH CURRENT COUNT
        # -------------------------------------------------
        #
        # This updates vehicle count without causing a
        # notification unless the traffic status changes.
        #

        else:

            # Only update the queued data.
            #
            # The Render thread controls the actual
            # network request frequency.

            queue_render_update(

                confirmed_status,

                smoothed_count,

                sequence_number

            )


        # -------------------------------------------------
        # DRAW DETECTIONS
        # -------------------------------------------------

        annotated_frame = (
            results[0].plot()
            if results
            else frame
        )


        # -------------------------------------------------
        # DISPLAY STATUS
        # -------------------------------------------------

        cv2.putText(

            annotated_frame,

            f"Vehicles: {smoothed_count}",

            (20, 40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 0),

            2

        )


        cv2.putText(

            annotated_frame,

            f"Traffic: {confirmed_status}",

            (20, 80),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 255),

            2

        )


        # -------------------------------------------------
        # SHOW CAMERA
        # -------------------------------------------------

        cv2.imshow(

            "Smart Traffic Detection",

            annotated_frame

        )


        # -------------------------------------------------
        # EXIT WITH Q
        # -------------------------------------------------

        key = (
            cv2.waitKey(1)
            & 0xFF
        )


        if key == ord("q"):

            break


except KeyboardInterrupt:

    print(
        "Program stopped by user."
    )


finally:

    # =====================================================
    # STOP RENDER THREAD
    # =====================================================

    stop_sender = True


    sender_thread.join(
        timeout=2
    )


    # =====================================================
    # CLOSE CAMERA
    # =====================================================

    cap.release()


    cv2.destroyAllWindows()


    # =====================================================
    # CLOSE ARDUINO
    # =====================================================

    if arduino is not None:

        try:

            arduino.close()

        except Exception:

            pass


    print(
        "======================================"
    )

    print(
        "Smart Traffic Detection stopped."
    )

    print(
        "======================================"
    )