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
import time
import json

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

import firebase_admin

from firebase_admin import (
    credentials,
    messaging
)


# ==================================================
# FLASK APPLICATION
# ==================================================

app = Flask(__name__)

app.secret_key = "smarttraffic_fresh_secret_key"

# Keep users logged in for 30 days
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30

app.config["SESSION_COOKIE_HTTPONLY"] = True

app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ==================================================
# DATABASE
# ==================================================

DATABASE = "traffic.db"


def get_db():

    connection = sqlite3.connect(
        DATABASE
    )

    connection.row_factory = sqlite3.Row

    return connection


def create_database():

    connection = get_db()

    cursor = connection.cursor()


    # ==================================================
    # USERS
    # ==================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            email TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL

        )
    """)


    # ==================================================
    # FIREBASE TOKENS
    # ==================================================

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS firebase_tokens (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            token TEXT UNIQUE NOT NULL

        )
    """)


    connection.commit()

    connection.close()


create_database()


# ==================================================
# FIREBASE CONFIGURATION
# ==================================================

FIREBASE_CREDENTIALS = (
    "firebase-service-account.json"
)

firebase_initialized = False


try:

    # ==================================================
    # METHOD 1 — RENDER SECRET FILE
    # ==================================================

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
            "======================================"
        )

        print(
            "Firebase Admin initialized successfully."
        )

        print(
            "Using Secret File:"
        )

        print(
            FIREBASE_CREDENTIALS
        )

        print(
            "======================================"
        )


    # ==================================================
    # METHOD 2 — ENVIRONMENT VARIABLE
    # ==================================================

    elif os.environ.get(
        "FIREBASE_SERVICE_ACCOUNT"
    ):

        print(
            "======================================"
        )

        print(
            "Firebase JSON file not found."
        )

        print(
            "Trying FIREBASE_SERVICE_ACCOUNT..."
        )

        print(
            "======================================"
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
            "======================================"
        )

        print(
            "Firebase Admin initialized successfully."
        )

        print(
            "Using FIREBASE_SERVICE_ACCOUNT."
        )

        print(
            "======================================"
        )


    else:

        print(
            "======================================"
        )

        print(
            "FIREBASE CONFIGURATION ERROR"
        )

        print(
            "Firebase service account JSON file"
        )

        print(
            "not found and FIREBASE_SERVICE_ACCOUNT"
        )

        print(
            "is not configured."
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

    print(error)

    print(
        "======================================"
    )


# ==================================================
# TRAFFIC DATA
# ==================================================

traffic_data = {

    "vehicle_count": 0,

    "traffic_status": "NORMAL"

}


# ==================================================
# NOTIFICATION CONTROL
# ==================================================

candidate_status = ""

candidate_start_time = 0

last_notified_status = ""

last_notification_time = 0


# ==================================================
# SETTINGS
# ==================================================

# Traffic must remain unchanged for this period
# before NORMAL/MODERATE is considered confirmed.

CONFIRMATION_TIME = 2


# Small protection against duplicate notifications.
# This is NOT a global 60-second lock.

NOTIFICATION_COOLDOWN = 10


# ==================================================
# FIREBASE SERVICE WORKER
# ==================================================

@app.route(
    "/firebase-messaging-sw.js"
)
def firebase_messaging_sw():

    return send_from_directory(

        app.static_folder,

        "firebase-messaging-sw.js"

    )


# ==================================================
# HOME
# ==================================================

@app.route("/")
def home():

    # If already logged in,
    # open dashboard directly.

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )


    return render_template(
        "home.html"
    )


# ==================================================
# REGISTER
# ==================================================

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
                error="Please fill in all fields."
            )


        connection = get_db()

        cursor = connection.cursor()


        cursor.execute(

            "SELECT id FROM users WHERE email = ?",

            (email,)

        )


        existing_user = cursor.fetchone()


        if existing_user:

            connection.close()


            return render_template(

                "register.html",

                error="Email already registered."

            )


        password_hash = generate_password_hash(
            password
        )


        cursor.execute(

            """
            INSERT INTO users
            (name, email, password)

            VALUES (?, ?, ?)
            """,

            (
                name,
                email,
                password_hash
            )

        )


        connection.commit()

        connection.close()


        return redirect(
            url_for("login")
        )


    return render_template(
        "register.html"
    )


# ==================================================
# LOGIN
# ==================================================

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

            "SELECT * FROM users WHERE email = ?",

            (email,)

        )


        user = cursor.fetchone()


        connection.close()


        if user and check_password_hash(

            user["password"],

            password

        ):

            # Make login session persistent

            session.permanent = True


            session["user_id"] = (
                user["id"]
            )


            session["user_name"] = (
                user["name"]
            )


            session["user_email"] = (
                user["email"]
            )


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


# ==================================================
# LOGOUT
# ==================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ==================================================
# DASHBOARD
# ==================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )


    return render_template(

        "dashboard.html",

        name=session.get(
            "user_name"
        ),

        email=session.get(
            "user_email"
        )

    )


# ==================================================
# TRAFFIC API
# ==================================================

@app.route("/traffic")
def traffic():

    return jsonify(
        traffic_data
    )


# ==================================================
# SEND NOTIFICATION TO ALL DEVICES
# ==================================================

def send_traffic_notification(

    traffic_status,

    vehicle_count

):

    if not firebase_initialized:

        print(
            "❌ Firebase is not initialized."
        )

        return 0


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


    sent_count = 0


    for row in rows:

        token = row["token"]


        message = messaging.Message(

            notification=messaging.Notification(

                title="🚦 Smart Traffic Alert",

                body=(

                    f"Traffic is {traffic_status}. "

                    f"Vehicles detected: "
                    f"{vehicle_count}"

                )

            ),

            token=token

        )


        try:

            response = messaging.send(
                message
            )


            print(
                "✅ Firebase notification sent:",
                response
            )


            sent_count += 1


        except Exception as error:

            print(
                "❌ Firebase notification error:"
            )

            print(error)


    return sent_count


# ==================================================
# UPDATE TRAFFIC
# ==================================================

@app.route(
    "/update_traffic",
    methods=["POST"]
)
def update_traffic():

    global traffic_data

    global candidate_status

    global candidate_start_time

    global last_notified_status

    global last_notification_time


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({

            "success": False,

            "message":
                "No traffic data received."

        }), 400


    # ==================================================
    # VEHICLE COUNT
    # ==================================================

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


    # ==================================================
    # TRAFFIC STATUS
    # ==================================================

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

        traffic_status = "NORMAL"


    # ==================================================
    # UPDATE DASHBOARD IMMEDIATELY
    # ==================================================

    traffic_data["vehicle_count"] = (
        vehicle_count
    )

    traffic_data["traffic_status"] = (
        traffic_status
    )


    print(

        f"Traffic: {traffic_status} | "
        f"Vehicles: {vehicle_count}"

    )


    current_time = time.time()


    # ==================================================
    # HEAVY TRAFFIC
    # ==================================================

    if traffic_status == "HEAVY":

        # Heavy is sent immediately when
        # status changes into HEAVY.

        if last_notified_status != "HEAVY":

            print(
                "======================================"
            )

            print(
                "🚨 HEAVY TRAFFIC DETECTED"
            )

            print(
                "🚨 HEAVY notification"
            )

            print(
                "======================================"
            )


            sent_count = (
                send_traffic_notification(

                    traffic_status,

                    vehicle_count

                )
            )


            if sent_count > 0:

                last_notified_status = (
                    "HEAVY"
                )

                last_notification_time = (
                    current_time
                )

                candidate_status = ""

                candidate_start_time = 0


                return jsonify({

                    "success": True,

                    "vehicle_count":
                        vehicle_count,

                    "traffic_status":
                        traffic_status,

                    "notification":
                        "HEAVY sent",

                    "notification_sent":
                        sent_count

                })


        return jsonify({

            "success": True,

            "vehicle_count":
                vehicle_count,

            "traffic_status":
                traffic_status,

            "notification":
                "HEAVY already notified"

        })


    # ==================================================
    # SAME STATUS ALREADY NOTIFIED
    # ==================================================

    if traffic_status == last_notified_status:

        candidate_status = ""

        candidate_start_time = 0


        return jsonify({

            "success": True,

            "vehicle_count":
                vehicle_count,

            "traffic_status":
                traffic_status,

            "notification":
                "not needed"

        })


    # ==================================================
    # NEW STATUS
    # ==================================================

    if traffic_status != candidate_status:

        candidate_status = (
            traffic_status
        )

        candidate_start_time = (
            current_time
        )


        print(

            f"⏳ {traffic_status} detected."

        )

        print(

            f"Waiting {CONFIRMATION_TIME} "
            f"seconds..."

        )


        return jsonify({

            "success": True,

            "vehicle_count":
                vehicle_count,

            "traffic_status":
                traffic_status,

            "notification":
                "waiting for confirmation"

        })


    # ==================================================
    # CONFIRMATION
    # ==================================================

    elapsed = (

        current_time
        -
        candidate_start_time

    )


    if elapsed < CONFIRMATION_TIME:

        return jsonify({

            "success": True,

            "vehicle_count":
                vehicle_count,

            "traffic_status":
                traffic_status,

            "notification":
                "waiting for confirmation"

        })


    # ==================================================
    # SMALL DUPLICATE PROTECTION
    # ==================================================

    cooldown_elapsed = (

        current_time
        -
        last_notification_time

    )


    # Only block if the status is the same
    # as the previous notification.
    #
    # A genuine status change is allowed through.

    if (

        last_notified_status == traffic_status

        and

        cooldown_elapsed <
        NOTIFICATION_COOLDOWN

    ):

        return jsonify({

            "success": True,

            "vehicle_count":
                vehicle_count,

            "traffic_status":
                traffic_status,

            "notification":
                "cooldown"

        })


    # ==================================================
    # SEND NORMAL / MODERATE
    # ==================================================

    print(
        "======================================"
    )

    print(
        "🔔 SENDING TRAFFIC NOTIFICATION"
    )

    print(
        "Status:",
        traffic_status
    )

    print(
        "Vehicles:",
        vehicle_count
    )

    print(
        "======================================"
    )


    sent_count = (
        send_traffic_notification(

            traffic_status,

            vehicle_count

        )
    )


    # ==================================================
    # RECORD SUCCESSFUL NOTIFICATION
    # ==================================================

    if sent_count > 0:

        last_notified_status = (
            traffic_status
        )

        last_notification_time = (
            current_time
        )

        candidate_status = ""

        candidate_start_time = 0


        print(

            f"✅ Notification sent to "
            f"{sent_count} device(s)."

        )


    return jsonify({

        "success": True,

        "vehicle_count":
            vehicle_count,

        "traffic_status":
            traffic_status,

        "notification_sent":
            sent_count

    })


# ==================================================
# SAVE FIREBASE TOKEN
# ==================================================

@app.route(
    "/firebase-token",
    methods=["POST"]
)
def firebase_token():

    if "user_id" not in session:

        return jsonify({

            "success": False,

            "message":
                "Please login first."

        }), 401


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({

            "success": False,

            "message":
                "No Firebase token received."

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


    try:

        connection = get_db()

        cursor = connection.cursor()


        # If this token already exists,
        # update its user_id.
        #
        # If it is a new phone,
        # create a new row.

        cursor.execute(

            """
            INSERT OR REPLACE INTO firebase_tokens
            (user_id, token)

            VALUES (?, ?)
            """,

            (

                session["user_id"],

                token

            )

        )


        connection.commit()

        connection.close()


        print(
            "Firebase token saved successfully."
        )


        return jsonify({

            "success": True,

            "message":
                "Firebase token saved successfully."

        })


    except Exception as error:

        print(
            "Firebase token database error:"
        )

        print(error)


        return jsonify({

            "success": False,

            "message":
                str(error)

        }), 500


# ==================================================
# TEST FIREBASE NOTIFICATION
# ==================================================

@app.route(
    "/test-firebase-notification",
    methods=["POST"]
)
def test_firebase_notification():

    if "user_id" not in session:

        return jsonify({

            "success": False,

            "message":
                "Please login first."

        }), 401


    if not firebase_initialized:

        return jsonify({

            "success": False,

            "message":
                "Firebase Admin is not initialized."

        }), 500


    try:

        connection = get_db()

        cursor = connection.cursor()


        cursor.execute(

            """
            SELECT token
            FROM firebase_tokens
            WHERE user_id = ?
            """,

            (

                session["user_id"],

            )

        )


        rows = cursor.fetchall()

        connection.close()


        if not rows:

            return jsonify({

                "success": False,

                "message":
                    "No Firebase device token found."

            }), 400


        sent_count = 0


        for row in rows:

            message = messaging.Message(

                notification=messaging.Notification(

                    title="🚦 Smart Traffic",

                    body=(

                        "Test notification from "
                        "Smart Traffic Fresh."

                    )

                ),

                token=row["token"]

            )


            try:

                messaging.send(message)

                sent_count += 1


            except Exception as token_error:

                print(
                    "Firebase token error:"
                )

                print(token_error)


        if sent_count == 0:

            return jsonify({

                "success": False,

                "message":
                    "Firebase could not send "
                    "the notification."

            }), 500


        return jsonify({

            "success": True,

            "message":
                f"Test notification sent to "
                f"{sent_count} device(s)."

        })


    except Exception as error:

        print(
            "Firebase notification error:"
        )

        print(error)


        return jsonify({

            "success": False,

            "message":
                str(error)

        }), 500


# ==================================================
# NOTIFICATIONS PAGE
# ==================================================

@app.route("/notifications")
def notifications():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )


    return render_template(
        "notifications.html"
    )


# ==================================================
# HEALTH CHECK
# ==================================================

@app.route("/health")
def health():

    return jsonify({

        "status": "online",

        "firebase":
            firebase_initialized,

        "traffic":
            traffic_data

    })


# ==================================================
# RUN FLASK
# ==================================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(

            os.environ.get(

                "PORT",

                5000

            )

        ),

        debug=False,

        use_reloader=False

    )