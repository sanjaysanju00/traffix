from ultralytics import YOLO
import cv2
import serial
import time
import requests
from collections import deque
import statistics


# ============================================================
# SETTINGS
# ============================================================

ARDUINO_PORT = "COM7"

ARDUINO_BAUDRATE = 9600

FLASK_URL = (
    "https://smart-traffic-system-c36o.onrender.com"
    "/update_traffic"
)


# Send data to Render once every second
SERVER_UPDATE_INTERVAL = 1.0


# Number of frames used for vehicle-count smoothing
SMOOTHING_FRAMES = 7


# A new status must be detected in this many
# consecutive server-update cycles before changing.
STATUS_CONFIRMATION_COUNT = 3


# ============================================================
# CONNECT TO ARDUINO
# ============================================================

try:

    arduino = serial.Serial(

        ARDUINO_PORT,

        ARDUINO_BAUDRATE,

        timeout=1

    )

    time.sleep(2)


    print(
        "=========================================="
    )

    print(
        f"✅ Arduino connected: {ARDUINO_PORT}"
    )

    print(
        "=========================================="
    )


except Exception as error:

    print(
        "❌ Arduino connection failed:"
    )

    print(error)

    exit()


# ============================================================
# LOAD YOLO
# ============================================================

print(
    "Loading YOLO model..."
)


model = YOLO(
    "yolo11n.pt"
)


print(
    "✅ YOLO model loaded"
)


# ============================================================
# OPEN CAMERA
# ============================================================

camera = cv2.VideoCapture(
    0
)


if not camera.isOpened():

    print(
        "❌ Camera could not be opened."
    )

    arduino.close()

    exit()


print(
    "✅ Camera started"
)


# ============================================================
# VEHICLE CLASSES
# ============================================================

vehicle_classes = {

    2: "car",

    3: "motorcycle",

    5: "bus",

    7: "truck"

}


# ============================================================
# VEHICLE COUNT SMOOTHING
# ============================================================

recent_counts = deque(

    maxlen=SMOOTHING_FRAMES

)


# ============================================================
# TRAFFIC STATUS CONTROL
# ============================================================

confirmed_status = "NORMAL"

candidate_status = "NORMAL"

candidate_count = 0


# ============================================================
# ARDUINO CONTROL
# ============================================================

last_arduino_status = ""


# ============================================================
# RENDER CONTROL
# ============================================================

last_server_update = 0

last_render_status = ""

last_render_count = -1


# ============================================================
# FUNCTION:
# DETERMINE TRAFFIC STATUS
# ============================================================

def get_traffic_status(
    vehicle_count
):

    if vehicle_count <= 3:

        return "NORMAL"

    elif vehicle_count <= 6:

        return "MODERATE"

    else:

        return "HEAVY"


# ============================================================
# FUNCTION:
# CONFIRM TRAFFIC STATUS
# ============================================================

def update_confirmed_status(
    new_status
):

    global confirmed_status

    global candidate_status

    global candidate_count


    # --------------------------------------------------------
    # Already confirmed
    # --------------------------------------------------------

    if new_status == confirmed_status:

        candidate_status = (
            new_status
        )

        candidate_count = 0

        return confirmed_status


    # --------------------------------------------------------
    # New candidate status
    # --------------------------------------------------------

    if new_status != candidate_status:

        candidate_status = (
            new_status
        )

        candidate_count = 1


    else:

        candidate_count += 1


    # --------------------------------------------------------
    # Confirm after consecutive detections
    # --------------------------------------------------------

    if (
        candidate_count
        >= STATUS_CONFIRMATION_COUNT
    ):

        confirmed_status = (
            candidate_status
        )

        candidate_count = 0


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


    return confirmed_status


# ============================================================
# START
# ============================================================

print("")

print(
    "=========================================="
)

print(
    "🚦 SMART TRAFFIC DETECTION STARTED"
)

print(
    "=========================================="
)

print("")

print(
    f"Count smoothing: "
    f"{SMOOTHING_FRAMES} frames"
)

print(
    f"Status confirmation: "
    f"{STATUS_CONFIRMATION_COUNT} cycles"
)

print(
    "Render update: every 1 second"
)

print("")

print(
    "Press Q to stop."
)

print("")


# ============================================================
# MAIN LOOP
# ============================================================

try:

    while True:

        # ====================================================
        # READ CAMERA
        # ====================================================

        success, frame = camera.read()


        if not success:

            print(
                "❌ Camera frame could not be read."
            )

            break


        # ====================================================
        # YOLO DETECTION
        # ====================================================

        results = model(

            frame,

            verbose=False

        )


        # ====================================================
        # COUNT VEHICLES
        # ====================================================

        raw_vehicle_count = 0


        for result in results:

            if result.boxes is None:

                continue


            for box in result.boxes:

                class_id = int(
                    box.cls[0]
                )


                if class_id in vehicle_classes:

                    raw_vehicle_count += 1


        # ====================================================
        # STORE COUNT
        # ====================================================

        recent_counts.append(

            raw_vehicle_count

        )


        # ====================================================
        # SMOOTH COUNT
        # ====================================================

        smoothed_vehicle_count = int(

            statistics.median(
                recent_counts
            )

        )


        # ====================================================
        # DETECT STATUS
        # ====================================================

        detected_status = (

            get_traffic_status(

                smoothed_vehicle_count

            )

        )


        # ====================================================
        # CONFIRM STATUS
        # ====================================================

        traffic_status = (

            update_confirmed_status(

                detected_status

            )

        )


        # ====================================================
        # SEND TO ARDUINO
        # ====================================================

        if (
            traffic_status
            != last_arduino_status
        ):

            try:

                arduino.write(

                    (
                        traffic_status
                        + "\n"
                    ).encode()

                )


                print(

                    f"🔴 Arduino: "
                    f"{traffic_status}"

                )


                last_arduino_status = (

                    traffic_status

                )


            except Exception as error:

                print(
                    "❌ Arduino send error:"
                )

                print(error)


        # ====================================================
        # SEND TO RENDER
        # ====================================================

        current_time = time.time()


        if (

            current_time
            -
            last_server_update

            >=

            SERVER_UPDATE_INTERVAL

        ):

            last_server_update = (
                current_time
            )


            try:

                response = requests.post(

                    FLASK_URL,

                    json={

                        "vehicle_count":
                            smoothed_vehicle_count,

                        "traffic_status":
                            traffic_status

                    },

                    timeout=5

                )


                # --------------------------------------------
                # Print status when something changes
                # --------------------------------------------

                if (

                    traffic_status
                    != last_render_status

                    or

                    smoothed_vehicle_count
                    != last_render_count

                ):

                    print(

                        f"🌐 Render: "
                        f"{traffic_status} "
                        f"| Vehicles: "
                        f"{smoothed_vehicle_count}"

                    )


                    last_render_status = (

                        traffic_status

                    )

                    last_render_count = (

                        smoothed_vehicle_count

                    )


                # --------------------------------------------
                # HTTP ERROR
                # --------------------------------------------

                if (
                    response.status_code
                    != 200
                ):

                    print(

                        f"⚠️ Render HTTP "
                        f"{response.status_code}"

                    )


            except requests.exceptions.Timeout:

                print(
                    "⚠️ Render request timed out."
                )


            except requests.exceptions.RequestException as error:

                print(
                    "❌ Render connection error:"
                )

                print(error)


            except Exception as error:

                print(
                    "❌ Server update error:"
                )

                print(error)


        # ====================================================
        # DRAW YOLO BOXES
        # ====================================================

        display_frame = frame.copy()


        for result in results:

            if result.boxes is None:

                continue


            for box in result.boxes:

                class_id = int(
                    box.cls[0]
                )


                if class_id not in vehicle_classes:

                    continue


                confidence = float(
                    box.conf[0]
                )


                x1, y1, x2, y2 = map(

                    int,

                    box.xyxy[0]

                )


                label = (

                    f"{vehicle_classes[class_id]} "
                    f"{confidence:.2f}"

                )


                cv2.rectangle(

                    display_frame,

                    (x1, y1),

                    (x2, y2),

                    (0, 255, 0),

                    2

                )


                cv2.putText(

                    display_frame,

                    label,

                    (x1, y1 - 10),

                    cv2.FONT_HERSHEY_SIMPLEX,

                    0.5,

                    (0, 255, 0),

                    2

                )


        # ====================================================
        # DISPLAY VEHICLE COUNT
        # ====================================================

        cv2.putText(

            display_frame,

            f"Vehicles: "
            f"{smoothed_vehicle_count}",

            (20, 40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (255, 255, 255),

            2

        )


        # ====================================================
        # DISPLAY TRAFFIC STATUS
        # ====================================================

        cv2.putText(

            display_frame,

            f"Traffic: "
            f"{traffic_status}",

            (20, 80),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (255, 255, 255),

            2

        )


        # ====================================================
        # DISPLAY RAW COUNT
        # ====================================================

        cv2.putText(

            display_frame,

            f"Raw: "
            f"{raw_vehicle_count}",

            (20, 120),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        # ====================================================
        # DISPLAY STATUS BEING CHECKED
        # ====================================================

        if (
            candidate_status
            != confirmed_status
        ):

            cv2.putText(

                display_frame,

                f"Checking: "
                f"{candidate_status}",

                (20, 155),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.65,

                (255, 255, 255),

                2

            )


        # ====================================================
        # SHOW CAMERA
        # ====================================================

        cv2.imshow(

            "Smart Traffic Detection",

            display_frame

        )


        # ====================================================
        # PRESS Q TO EXIT
        # ====================================================

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

finally:

    camera.release()

    cv2.destroyAllWindows()


    try:

        arduino.close()

    except Exception:

        pass


    print("")

    print(
        "=========================================="
    )

    print(
        "✅ Smart Traffic Detection stopped"
    )

    print(
        "=========================================="
    )