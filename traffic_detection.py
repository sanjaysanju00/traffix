from ultralytics import YOLO
import cv2
import serial
import time
import requests


# ==================================================
# SETTINGS
# ==================================================

ARDUINO_PORT = "COM7"

ARDUINO_BAUDRATE = 9600

FLASK_URL = "https://smart-traffic-system-c36o.onrender.com/update_traffic"


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

    print(
        "✅ Arduino connected:",
        ARDUINO_PORT
    )


except Exception as error:

    print(
        "❌ Arduino connection failed:"
    )

    print(error)

    exit()


# ==================================================
# LOAD YOLO
# ==================================================

model = YOLO(
    "yolo11n.pt"
)


# ==================================================
# CAMERA
# ==================================================

camera = cv2.VideoCapture(0)


if not camera.isOpened():

    print(
        "❌ Camera could not be opened."
    )

    arduino.close()

    exit()


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
print("Confirmation : 5 seconds")
print("Cooldown     : 60 seconds")
print("Press Q      : STOP")
print("======================================")


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
# LAST ARDUINO STATUS
# ==================================================

last_arduino_status = ""


# ==================================================
# MAIN LOOP
# ==================================================

while True:

    success, frame = camera.read()


    if not success:

        print(
            "❌ Camera frame error."
        )

        break


    # ==============================================
    # YOLO
    # ==============================================

    results = model(

        frame,

        verbose=False

    )


    vehicle_count = 0


    # ==============================================
    # COUNT VEHICLES
    # ==============================================

    for result in results:

        for box in result.boxes:

            class_id = int(
                box.cls[0]
            )


            if class_id in vehicle_classes:

                vehicle_count += 1


    # ==============================================
    # TRAFFIC STATUS
    # ==============================================

    if vehicle_count <= 3:

        traffic_status = "NORMAL"


    elif vehicle_count <= 6:

        traffic_status = "MODERATE"


    else:

        traffic_status = "HEAVY"


    # ==============================================
    # SEND TO ARDUINO
    # ==============================================

    if traffic_status != last_arduino_status:

        try:

            arduino.write(

                (
                    traffic_status
                    + "\n"
                ).encode()

            )

            print(
                "Arduino:",
                traffic_status
            )

            last_arduino_status = traffic_status


        except Exception as error:

            print(
                "❌ Arduino error:",
                error
            )


    # ==============================================
    # SEND TO FLASK
    # ==============================================

    try:

        response = requests.post(

            FLASK_URL,

            json={

                "vehicle_count":
                    vehicle_count,

                "traffic_status":
                    traffic_status

            },

            timeout=2

        )


        if response.status_code != 200:

            print(
                "❌ Flask error:",
                response.status_code
            )


    except Exception as error:

        print(
            "❌ Flask connection error:",
            error
        )


    # ==============================================
    # DISPLAY
    # ==============================================

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


    # ==============================================
    # SHOW CAMERA
    # ==============================================

    cv2.imshow(

        "Smart Traffic Detection",

        annotated_frame

    )


    # ==============================================
    # QUIT
    # ==============================================

    if cv2.waitKey(1) & 0xFF == ord("q"):

        break


# ==================================================
# CLEANUP
# ==================================================

camera.release()

arduino.close()

cv2.destroyAllWindows()


print("======================================")
print("Smart Traffic System stopped.")
print("======================================")