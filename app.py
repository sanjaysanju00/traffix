from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory
)

import sqlite3
import os
import json
import time
import threading

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

import firebase_admin

from firebase_admin import (
    credentials,
    messaging
)


# =========================================================
# FLASK APPLICATION
# =========================================================

app = Flask(__name__)

app.secret_key = "smarttraffic_fresh_secret_key"

app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30

app.config["SESSION_COOKIE_HTTPONLY"] = True

app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# =========================================================
# DATABASE
# =========================================================

DATABASE = "traffic.db"


def get_db():

    connection = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    connection.row_factory = sqlite3.Row

    return connection


def create_database():

    connection = get_db()

    cursor = connection.cursor()


    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            email TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL

        )
        """
    )


    # -----------------------------------------------------
    # FIREBASE TOKENS
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS firebase_tokens (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            token TEXT UNIQUE NOT NULL

        )
        """
    )


    # -----------------------------------------------------
    # TRAFFIC STATE
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS traffic_state (

            id INTEGER PRIMARY KEY CHECK (id = 1),

            source_id TEXT,

            last_sequence INTEGER DEFAULT 0,

            last_status TEXT DEFAULT 'NORMAL'

        )
        """
    )


    cursor.execute(
        """
        INSERT OR IGNORE INTO traffic_state
        (
            id,
            source_id,
            last_sequence,
            last_status
        )
        VALUES
        (
            1,
            '',
            0,
            'NORMAL'
        )
        """
    )


    connection.commit()

    connection.close()


create_database()


# =========================================================
# FIREBASE ADMIN CONFIGURATION
# =========================================================

FIREBASE_CREDENTIALS = "firebase-service-account.json"

firebase_initialized = False


try:

    # -----------------------------------------------------
    # RENDER SECRET FILE
    # -----------------------------------------------------

    if os.path.exists(
        FIREBASE_CREDENTIALS
    ):

        print(
            "======================================"
        )

        print(
            "Firebase JSON file found."
        )

        print(
            "Loading Firebase service account..."
        )

        print(
            "======================================"
        )


        cred = credentials.Certificate(
            FIREBASE_CREDENTIALS
        )


        firebase_admin.initialize_app(
            cred
        )


        firebase_initialized = True


        print(
            "Firebase Admin initialized successfully."
        )


    # -----------------------------------------------------
    # ENVIRONMENT VARIABLE FALLBACK
    # -----------------------------------------------------

    elif os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT"
    ):

        print(
            "Firebase JSON file not found."
        )

        print(
            "Using FIREBASE_SERVICE_ACCOUNT."
        )


        firebase_json = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT"
        )


        firebase_info = json.loads(
            firebase_json
        )


        cred = credentials.Certificate(
            firebase_info
        )


        firebase_admin.initialize_app(
            cred
        )


        firebase_initialized = True


        print(
            "Firebase Admin initialized successfully."
        )


    else:

        print(
            "======================================"
        )

        print(
            "Firebase configuration not found."
        )

        print(
            "======================================"
        )


except Exception as error:

    print(
        "======================================"
    )

    print(
        "Firebase initialization failed:"
    )

    print(
        error
    )

    print(
        "======================================"
    )


# =========================================================
# TRAFFIC DATA
# =========================================================

traffic_data = {

    "vehicle_count": 0,

    "traffic_status": "NORMAL"

}


# Lock protects traffic_data from simultaneous requests.

traffic_lock = threading.Lock()


# =========================================================
# HELPER: GET CURRENT TRAFFIC
# =========================================================

def get_current_traffic():

    with traffic_lock:

        return {

            "vehicle_count":
                traffic_data[
                    "vehicle_count"
                ],

            "traffic_status":
                traffic_data[
                    "traffic_status"
                ]

        }


# =========================================================
# FIREBASE NOTIFICATION
# =========================================================

def send_traffic_notification(
    traffic_status,
    vehicle_count
):

    if not firebase_initialized:

        print(
            "❌ Firebase is not initialized."
        )

        return 0


    # -----------------------------------------------------
    # GET ALL REGISTERED TOKENS
    # -----------------------------------------------------

    connection = get_db()

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT token
        FROM firebase_tokens
        """
    )


    rows = cursor.fetchall()

    connection.close()


    if not rows:

        print(
            "⚠️ No Firebase devices registered."
        )

        return 0


    # -----------------------------------------------------
    # REMOVE DUPLICATE TOKENS
    # -----------------------------------------------------

    tokens = []

    seen = set()


    for row in rows:

        token = row["token"]

        if token and token not in seen:

            seen.add(token)

            tokens.append(token)


    if not tokens:

        print(
            "⚠️ No valid Firebase tokens."
        )

        return 0


    # -----------------------------------------------------
    # NOTIFICATION CONTENT
    # -----------------------------------------------------

    if traffic_status == "HEAVY":

        title = "🚨 Heavy Traffic Alert"

        body = (
            f"Heavy traffic detected. "
            f"{vehicle_count} vehicles detected."
        )


    elif traffic_status == "MODERATE":

        title = "⚠️ Moderate Traffic Alert"

        body = (
            f"Moderate traffic detected. "
            f"{vehicle_count} vehicles detected."
        )


    else:

        title = "🟢 Traffic Cleared"

        body = (
            "Traffic is normal now. "
            "The road is clear."
        )


    # -----------------------------------------------------
    # SEND TO ALL DEVICES IN MULTICAST BATCHES
    # -----------------------------------------------------
    #
    # Firebase allows up to 500 registration tokens
    # in one multicast message.
    #
    # This is much better than:
    #
    # Phone 1 -> wait -> Phone 2 -> wait -> Phone 3
    #
    # -----------------------------------------------------

    total_sent = 0

    invalid_tokens = []


    for start in range(
        0,
        len(tokens),
        500
    ):

        batch_tokens = tokens[
            start:start + 500
        ]


        message = messaging.MulticastMessage(

            notification=messaging.Notification(

                title=title,

                body=body

            ),

            tokens=batch_tokens

        )


        try:

            response = messaging.send_each_for_multicast(
                message
            )


            print(
                "======================================"
            )

            print(
                "Firebase multicast result"
            )

            print(
                f"Devices in batch: {len(batch_tokens)}"
            )

            print(
                f"Successful: {response.success_count}"
            )

            print(
                f"Failed: {response.failure_count}"
            )

            print(
                "======================================"
            )


            total_sent += (
                response.success_count
            )


            # -------------------------------------------------
            # FIND INVALID TOKENS
            # -------------------------------------------------

            for index, send_response in enumerate(
                response.responses
            ):

                if send_response.success:

                    continue


                error = send_response.exception

                if error is None:

                    continue


                error_text = str(
                    error
                ).lower()


                if (
                    "registration-token-not-registered"
                    in error_text
                    or
                    "requested entity was not found"
                    in error_text
                    or
                    "not registered"
                    in error_text
                ):

                    invalid_tokens.append(
                        batch_tokens[index]
                    )


        except Exception as error:

            print(
                "❌ Firebase multicast error:"
            )

            print(
                error
            )


    # -----------------------------------------------------
    # DELETE INVALID TOKENS
    # -----------------------------------------------------

    if invalid_tokens:

        connection = get_db()

        cursor = connection.cursor()


        for token in invalid_tokens:

            cursor.execute(
                """
                DELETE FROM firebase_tokens
                WHERE token = ?
                """,
                (token,)
            )


        connection.commit()

        connection.close()


        print(
            f"🗑️ Removed {len(invalid_tokens)} "
            f"invalid Firebase token(s)."
        )


    print(
        f"📱 Notification sent successfully "
        f"to {total_sent} device(s)."
    )


    return total_sent


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if session.get("user_id"):

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "home.html"
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()


        email = request.form.get(
            "email",
            ""
        ).strip().lower()


        password = request.form.get(
            "password",
            ""
        )


        if not name or not email or not password:

            return render_template(
                "register.html",
                error="Please fill all fields."
            )


        hashed_password = (
            generate_password_hash(
                password
            )
        )


        connection = get_db()

        cursor = connection.cursor()


        try:

            cursor.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password
                )
                VALUES
                (
                    ?,
                    ?,
                    ?
                )
                """,
                (
                    name,
                    email,
                    hashed_password
                )
            )


            connection.commit()

            connection.close()


            return redirect(
                url_for("login")
            )


        except sqlite3.IntegrityError:

            connection.close()


            return render_template(
                "register.html",
                error="Email already registered."
            )


    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()


        password = request.form.get(
            "password",
            ""
        )


        connection = get_db()

        cursor = connection.cursor()


        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        )


        user = cursor.fetchone()

        connection.close()


        if user and check_password_hash(
            user["password"],
            password
        ):

            session.permanent = True

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]


            return redirect(
                url_for("dashboard")
            )


        return render_template(
            "login.html",
            error="Invalid email or password."
        )


    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    if not session.get("user_id"):

        return redirect(
            url_for("login")
        )


    return render_template(
        "dashboard.html"
    )


# =========================================================
# NOTIFICATIONS PAGE
# =========================================================

@app.route("/notifications")
def notifications():

    if not session.get("user_id"):

        return redirect(
            url_for("login")
        )


    return render_template(
        "notifications.html"
    )


# =========================================================
# FIREBASE TOKEN REGISTRATION
# =========================================================

@app.route(
    "/firebase-token",
    methods=["POST"]
)
def firebase_token():

    if not session.get("user_id"):

        return jsonify({

            "success": False,

            "message":
                "Login required."

        }), 401


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({

            "success": False,

            "message":
                "No token data received."

        }), 400


    token = str(
        data.get(
            "token",
            ""
        )
    ).strip()


    if not token:

        return jsonify({

            "success": False,

            "message":
                "Firebase token is empty."

        }), 400


    user_id = session["user_id"]


    connection = get_db()

    cursor = connection.cursor()


    cursor.execute(
        """
        INSERT OR REPLACE INTO firebase_tokens
        (
            user_id,
            token
        )
        VALUES
        (
            ?,
            ?
        )
        """,
        (
            user_id,
            token
        )
    )


    connection.commit()


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM firebase_tokens
        """
    )


    total_devices = cursor.fetchone()[0]


    connection.close()


    print(
        "======================================"
    )

    print(
        "Firebase token registered."
    )

    print(
        f"User ID: {user_id}"
    )

    print(
        f"Total registered devices: {total_devices}"
    )

    print(
        "======================================"
    )


    return jsonify({

        "success": True,

        "message":
            "Firebase token registered successfully.",

        "total_devices":
            total_devices

    })


# =========================================================
# TEST FIREBASE NOTIFICATION
# =========================================================

@app.route(
    "/test-firebase-notification",
    methods=["POST"]
)
def test_firebase_notification():

    if not session.get("user_id"):

        return jsonify({

            "success": False,

            "message":
                "Login required."

        }), 401


    if not firebase_initialized:

        return jsonify({

            "success": False,

            "message":
                "Firebase is not initialized."

        }), 500


    user_id = session["user_id"]


    connection = get_db()

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT token
        FROM firebase_tokens
        WHERE user_id = ?
        """,
        (user_id,)
    )


    rows = cursor.fetchall()

    connection.close()


    if not rows:

        return jsonify({

            "success": False,

            "message":
                "No Firebase device is registered for this account."

        }), 404


    tokens = []

    seen = set()


    for row in rows:

        token = row["token"]

        if token and token not in seen:

            seen.add(token)

            tokens.append(token)


    message = messaging.MulticastMessage(

        notification=messaging.Notification(

            title="🚦 Smart Traffic Test",

            body=(
                "Firebase notification is working "
                "successfully on this device."
            )

        ),

        tokens=tokens

    )


    try:

        response = (
            messaging.send_each_for_multicast(
                message
            )
        )


        print(
            "======================================"
        )

        print(
            "TEST FIREBASE NOTIFICATION"
        )

        print(
            f"Successful: {response.success_count}"
        )

        print(
            f"Failed: {response.failure_count}"
        )

        print(
            "======================================"
        )


        return jsonify({

            "success":
                response.success_count > 0,

            "sent":
                response.success_count,

            "failed":
                response.failure_count,

            "message":
                "Test notification sent."

        })


    except Exception as error:

        print(
            "❌ Test Firebase notification error:"
        )

        print(
            error
        )


        return jsonify({

            "success": False,

            "message":
                str(error)

        }), 500


# =========================================================
# UPDATE TRAFFIC FROM YOLO
# =========================================================

@app.route(
    "/update_traffic",
    methods=["POST"]
)
def update_traffic():

    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({

            "success": False,

            "message":
                "No traffic data received."

        }), 400


    # -----------------------------------------------------
    # VEHICLE COUNT
    # -----------------------------------------------------

    try:

        vehicle_count = int(
            data.get(
                "vehicle_count",
                0
            )
        )

    except Exception:

        vehicle_count = 0


    if vehicle_count < 0:

        vehicle_count = 0


    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    traffic_status = str(
        data.get(
            "traffic_status",
            "NORMAL"
        )
    ).strip().upper()


    if traffic_status not in [
        "NORMAL",
        "MODERATE",
        "HEAVY"
    ]:

        return jsonify({

            "success": False,

            "message":
                "Invalid traffic status."

        }), 400


    # -----------------------------------------------------
    # SOURCE AND SEQUENCE
    # -----------------------------------------------------

    source_id = str(
        data.get(
            "source_id",
            "default"
        )
    ).strip()


    if not source_id:

        source_id = "default"


    try:

        sequence = int(
            data.get(
                "sequence",
                0
            )
        )

    except Exception:

        sequence = 0


    # -----------------------------------------------------
    # READ LAST SERVER STATE
    # -----------------------------------------------------

    connection = get_db()

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT
            source_id,
            last_sequence,
            last_status
        FROM traffic_state
        WHERE id = 1
        """
    )


    state = cursor.fetchone()


    if state:

        previous_source_id = (
            state["source_id"]
        )

        previous_sequence = int(
            state["last_sequence"] or 0
        )

        previous_status = (
            state["last_status"]
            or
            "NORMAL"
        )

    else:

        previous_source_id = ""

        previous_sequence = 0

        previous_status = "NORMAL"


    # -----------------------------------------------------
    # REJECT OLD REQUESTS
    # -----------------------------------------------------

    if (
        source_id ==
        previous_source_id
        and
        sequence <= previous_sequence
    ):

        connection.close()


        return jsonify({

            "success": True,

            "ignored": True,

            "message":
                "Old traffic update ignored."

        })


    # -----------------------------------------------------
    # UPDATE SERVER STATE
    # -----------------------------------------------------

    cursor.execute(
        """
        UPDATE traffic_state

        SET
            source_id = ?,
            last_sequence = ?,
            last_status = ?

        WHERE id = 1
        """,
        (
            source_id,
            sequence,
            traffic_status
        )
    )


    connection.commit()

    connection.close()


    # -----------------------------------------------------
    # UPDATE CURRENT TRAFFIC
    # -----------------------------------------------------

    with traffic_lock:

        traffic_data[
            "vehicle_count"
        ] = vehicle_count

        traffic_data[
            "traffic_status"
        ] = traffic_status


    print(
        f"🌐 Traffic update: "
        f"{traffic_status} | "
        f"Vehicles: {vehicle_count} | "
        f"Sequence: {sequence}"
    )


    # -----------------------------------------------------
    # NOTIFICATION ONLY ON STATUS CHANGE
    # -----------------------------------------------------
    #
    # This is important.
    #
    # YOLO may send:
    #
    # MODERATE
    # MODERATE
    # MODERATE
    # MODERATE
    #
    # We DO NOT send four phone notifications.
    #
    # We send only when the confirmed status changes.
    #
    # -----------------------------------------------------

    status_changed = (
        traffic_status !=
        previous_status
    )


    if status_changed:

        print(
            "--------------------------------------"
        )

        print(
            f"Traffic status changed:"
        )

        print(
            f"{previous_status} → "
            f"{traffic_status}"
        )

        print(
            "Sending Firebase notification..."
        )

        print(
            "--------------------------------------"
        )


        sent_count = (
            send_traffic_notification(
                traffic_status,
                vehicle_count
            )
        )


        print(
            f"Firebase result: "
            f"{sent_count} device(s)"
        )


    return jsonify({

        "success": True,

        "ignored": False,

        "vehicle_count":
            vehicle_count,

        "traffic_status":
            traffic_status,

        "sequence":
            sequence,

        "status_changed":
            status_changed

    })


# =========================================================
# TRAFFIC DATA FOR DASHBOARD
# =========================================================

@app.route("/traffic")
def traffic():

    current = (
        get_current_traffic()
    )


    return jsonify({

        "vehicle_count":
            current[
                "vehicle_count"
            ],

        "traffic_status":
            current[
                "traffic_status"
            ]

    })


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    connection = get_db()

    cursor = connection.cursor()


    cursor.execute(
        """
        SELECT COUNT(*)
        FROM firebase_tokens
        """
    )


    registered_devices = (
        cursor.fetchone()[0]
    )


    cursor.execute(
        """
        SELECT
            source_id,
            last_sequence,
            last_status
        FROM traffic_state
        WHERE id = 1
        """
    )


    state = cursor.fetchone()


    connection.close()


    return jsonify({

        "status":
            "online",

        "firebase":
            firebase_initialized,

        "registered_devices":
            registered_devices,

        "server_sequence":
            state["last_sequence"]
            if state
            else 0,

        "server_status":
            state["last_status"]
            if state
            else "NORMAL"

    })


# =========================================================
# SERVICE WORKER
# =========================================================

@app.route(
    "/firebase-messaging-sw.js"
)
def firebase_messaging_service_worker():

    return send_from_directory(
        "static",
        "firebase-messaging-sw.js"
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )