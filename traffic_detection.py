from ultralytics import YOLO
import cv2
import serial
import time
import requests
from collections import deque
import statistics


# ==================================================
# SETTINGS
# ==================================================

ARDUINO_PORT = "COM7"

ARDUINO_BAUDRATE = 9600

FLASK_URL = "https://smart-traffic-system-c36o.onrender.com/update_traffic"

# Send traffic data to Render once every second
SERVER_UPDATE_INTERVAL = 1.0

# Number of recent vehicle counts used for smoothing
SMOOTHING_FRAMES = 5


# ==================================================
# CONNECT TO ARDUINO
# ==================================================

try:

    arduino = serial.Serial(
        ARDUINO_PORT,
        ARDUINO_BAUDRATE,
        timeout=1
    )

    time.sleep(2)

    print("✅ Arduino connected:", ARDUINO_PORT)

except Exception as error:

    print("❌ Arduino connection failed:")
    print(error)

    exit()


# ==================================================
# LOAD YOLO
# ==================================================

try:

    model = YOLO("yolo11n.pt")

    print("✅ YOLO model loaded.")

except Exception as error:

    print("❌ YOLO model could not be loaded:")
    print(error)

    arduino.close()

    exit()


# ==================================================
# CAMERA
# ==================================================

camera = cv2.VideoCapture(0)

if not camera.isOpened():

    print("❌ Camera could not be opened.")

    arduino.close()

    exit()


# ==================================================
# VEHICLE CLASSES
# ==================================================

vehicle_classes = {

    2: "car",

    3: "motorcycle",

    5: "bus",

    7: "truck"

}


# ==================================================
# TRAFFIC SETTINGS
# ==================================================

# 0 - 3 vehicles = NORMAL
# 4 - 6 vehicles = MODERATE
# 7+ vehicles = HEAVY

def get_traffic_status(vehicle_count):

    if vehicle_count <= 3:

        return "NORMAL"

    elif vehicle_count <= 6:

        return "MODERATE"

    else:

        return "HEAVY"


# ==================================================
# STATUS / SERVER VARIABLES
# ==================================================

last_arduino_status = ""

last_server_status = ""

last_server_update = 0


# ==================================================
# VEHICLE COUNT SMOOTHING
# ==================================================

recent_counts = deque(
    maxlen=SMOOTHING_FRAMES
)


# ==================================================
# START MESSAGE
# ==================================================

print("======================================")
print("SMART TRAFFIC SYSTEM")
print("======================================")
print("Camera       : ON")
print("YOLO         : ON")
print("Arduino      : ON")
print("Flask        : ON")
print("Count smooth : 5 frames")
print("Server update: 1 second")
print("Confirmation : 2 seconds")
print("Press Q      : STOP")
print("======================================")


# ==================================================
# MAIN LOOP
# ==================================================

try:

    while True:

        # ==========================================
        # READ CAMERA FRAME
        # ==========================================

        success, frame = camera.read()

        if not success:

            print("❌ Camera frame error.")

            break


        # ==========================================
        # YOLO DETECTION
        # ==========================================

        results = model(
            frame,
            verbose=False
        )


        raw_vehicle_count = 0


        # ==========================================
        # COUNT VEHICLES
        # ==========================================

        for result in results:

            for box in result.boxes:

                class_id = int(
                    box.cls[0]
                )

                if class_id in vehicle_classes:

                    raw_vehicle_count += 1


        # ==========================================
        # SMOOTH VEHICLE COUNT
        # ==========================================

        recent_counts.append(
            raw_vehicle_count
        )


        # Median prevents one bad YOLO frame
        # from immediately changing traffic status.

        vehicle_count = int(
            statistics.median(
                recent_counts
            )
        )


        # ==========================================
        # TRAFFIC STATUS
        # ==========================================

        traffic_status = get_traffic_status(
            vehicle_count
        )


        # ==========================================
        # SEND TO ARDUINO
        # ==========================================

        if traffic_status != last_arduino_status:

            try:

                arduino.write(
                    (
                        traffic_status + "\n"
                    ).encode()
                )

                print(
                    f"🚦 Arduino: {traffic_status}"
                )

                last_arduino_status = (
                    traffic_status
                )

            except Exception as error:

                print(
                    "❌ Arduino error:",
                    error
                )


        # ==========================================
        # SEND TO RENDER
        # ==========================================

        current_time = time.time()


        if (
            current_time - last_server_update
            >= SERVER_UPDATE_INTERVAL
        ):

            try:

                response = requests.post(

                    FLASK_URL,

                    json={

                        "vehicle_count":
                            vehicle_count,

                        "traffic_status":
                            traffic_status

                    },

                    timeout=5

                )


                if response.status_code == 200:

                    # Print only when status changes
                    # to keep the terminal readable.

                    if traffic_status != last_server_status:

                        print(
                            f"🌐 Render: "
                            f"{traffic_status} | "
                            f"Vehicles: "
                            f"{vehicle_count}"
                        )

                        last_server_status = (
                            traffic_status
                        )

                else:

                    print(
                        "❌ Flask error:",
                        response.status_code
                    )

            except Exception as error:

                print(
                    "❌ Flask connection error:",
                    error
                )


            last_server_update = current_time


        # ==========================================
        # DISPLAY YOLO RESULT
        # ==========================================

        annotated_frame = results[0].plot()


        cv2.putText(

            annotated_frame,

            f"Vehicles: {vehicle_count}",

            (20, 40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 0),

            2

        )


        cv2.putText(

            annotated_frame,

            f"Traffic: {traffic_status}",

            (20, 80),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            (0, 255, 255),

            2

        )


        # Show raw count for debugging

        cv2.putText(

            annotated_frame,

            f"Raw count: {raw_vehicle_count}",

            (20, 120),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        # ==========================================
        # SHOW CAMERA
        # ==========================================

        cv2.imshow(

            "Smart Traffic Detection",

            annotated_frame

        )


        # ==========================================
        # QUIT
        # ==========================================

        if cv2.waitKey(1) & 0xFF == ord("q"):

            break


# ==================================================
# CLEANUP
# ==================================================

except KeyboardInterrupt:

    print("\n🛑 System stopped by user.")


finally:

    camera.release()

    arduino.close()

    cv2.destroyAllWindows()

    print("======================================")
    print("Smart Traffic System stopped.")
    print("======================================")