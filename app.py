from flask import (
    Flask,
    render_template,
    jsonify,
    request,
    redirect,
    url_for,
    session
)

import sqlite3
import os
import json
import uuid

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

import firebase_admin
from firebase_admin import (
    credentials,
    messaging
)


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)

app.secret_key = "smarttraffic_fresh_secret_key"

app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ============================================================
# DATABASE
# ============================================================

DATABASE = "traffic.db"


def get_db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_database():

    conn = get_db()

    cursor = conn.cursor()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # FIREBASE TOKENS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS firebase_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # --------------------------------------------------------
    # TRAFFIC SERVER STATE
    #
    # This protects against:
    # - duplicate requests
    # - delayed Render requests
    # - old/out-of-order requests
    # - repeated notifications
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traffic_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            source_id TEXT,
            last_sequence INTEGER DEFAULT 0,
            last_status TEXT DEFAULT 'NORMAL'
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO traffic_state
        (id, source_id, last_sequence, last_status)
        VALUES
        (1, NULL, 0, 'NORMAL')
    """)

    conn.commit()

    conn.close()


init_database()


# ============================================================
# FIREBASE INITIALIZATION
# ============================================================

firebase_initialized = False


def initialize_firebase():

    global firebase_initialized

    try:

        if firebase_admin._apps:

            firebase_initialized = True

            print("✅ Firebase Admin already initialized")

            return

        service_account_path = "firebase-service-account.json"

        if os.path.exists(service_account_path):

            cred = credentials.Certificate(
                service_account_path
            )

            firebase_admin.initialize_app(
                cred
            )

            firebase_initialized = True

            print(
                "✅ Firebase Admin initialized "
                "using firebase-service-account.json"
            )

            return

        # ----------------------------------------------------
        # Render secret file path
        # ----------------------------------------------------

        render_secret_path = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT"
        )

        if render_secret_path and os.path.exists(
            render_secret_path
        ):

            cred = credentials.Certificate(
                render_secret_path
            )

            firebase_admin.initialize_app(
                cred
            )

            firebase_initialized = True

            print(
                "✅ Firebase Admin initialized "
                "using Render secret file"
            )

            return

        # ----------------------------------------------------
        # JSON environment variable fallback
        # ----------------------------------------------------

        firebase_json = os.environ.get(
            "FIREBASE_SERVICE_ACCOUNT_JSON"
        )

        if firebase_json:

            service_account_info = json.loads(
                firebase_json
            )

            cred = credentials.Certificate(
                service_account_info
            )

            firebase_admin.initialize_app(
                cred
            )

            firebase_initialized = True

            print(
                "✅ Firebase Admin initialized "
                "using environment JSON"
            )

            return

        print(
            "⚠️ Firebase service account not found"
        )

    except Exception as e:

        print(
            "❌ Firebase initialization failed:",
            str(e)
        )

        firebase_initialized = False


initialize_firebase()


# ============================================================
# TRAFFIC DATA
# ============================================================

traffic_data = {

    "vehicle_count": 0,

    "traffic_status": "NORMAL"
}


# ============================================================
# SEND FIREBASE TRAFFIC NOTIFICATION
# ============================================================

def send_traffic_notification(
    traffic_status,
    vehicle_count
):

    if not firebase_initialized:

        print(
            "❌ Firebase is not initialized"
        )

        return 0

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT token
        FROM firebase_tokens
    """)

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        print(
            "⚠️ No Firebase devices registered"
        )

        return 0

    # --------------------------------------------------------
    # Notification content
    # --------------------------------------------------------

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

    sent_count = 0

    invalid_tokens = []

    # --------------------------------------------------------
    # Send notification to every registered device
    # --------------------------------------------------------

    for row in rows:

        token = row["token"]

        try:

            message = messaging.Message(

                notification=messaging.Notification(

                    title=title,

                    body=body
                ),

                data={

                    "traffic_status": traffic_status,

                    "vehicle_count": str(
                        vehicle_count
                    )
                },

                token=token
            )

            messaging.send(message)

            sent_count += 1

            print(
                f"   ✅ Notification sent to device"
            )

        except Exception as e:

            error_text = str(e)

            print(
                "   ❌ Firebase notification failed:",
                error_text
            )

            # ------------------------------------------------
            # Remove obviously invalid/unregistered tokens
            # ------------------------------------------------

            if (
                "registration-token-not-registered"
                in error_text.lower()
                or
                "unregistered"
                in error_text.lower()
            ):

                invalid_tokens.append(token)

    # --------------------------------------------------------
    # Remove invalid tokens
    # --------------------------------------------------------

    if invalid_tokens:

        conn = get_db()

        cursor = conn.cursor()

        for token in invalid_tokens:

            cursor.execute("""
                DELETE FROM firebase_tokens
                WHERE token = ?
            """, (token,))

        conn.commit()

        conn.close()

        print(
            f"🧹 Removed {len(invalid_tokens)} invalid device(s)"
        )

    return sent_count


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "home.html"
    )


# ============================================================
# REGISTER
# ============================================================

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

        password_hash = generate_password_hash(
            password
        )

        try:

            conn = get_db()

            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users
                (name, email, password)
                VALUES (?, ?, ?)
            """, (
                name,
                email,
                password_hash
            ))

            conn.commit()

            conn.close()

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            return render_template(
                "register.html",
                error="Email already registered."
            )

        except Exception as e:

            print(
                "❌ Registration error:",
                str(e)
            )

            return render_template(
                "register.html",
                error="Registration failed."
            )

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

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

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM users
            WHERE email = ?
        """, (email,))

        user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session.clear()

            session["user_id"] = user["id"]

            session["user_name"] = user["name"]

            session["user_email"] = user["email"]

            session.permanent = True

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


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "dashboard.html"
    )


# ============================================================
# NOTIFICATIONS PAGE
# ============================================================

@app.route("/notifications")
def notifications():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    return render_template(
        "notifications.html"
    )


# ============================================================
# REGISTER FIREBASE TOKEN
# ============================================================

@app.route(
    "/firebase-token",
    methods=["POST"]
)
def firebase_token():

    if "user_id" not in session:

        return jsonify({
            "success": False,
            "message": "Not logged in"
        }), 401

    try:

        data = request.get_json(
            silent=True
        ) or {}

        token = data.get(
            "token"
        )

        if not token:

            return jsonify({
                "success": False,
                "message": "Token missing"
            }), 400

        user_id = session["user_id"]

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO firebase_tokens
            (user_id, token)
            VALUES (?, ?)
        """, (
            user_id,
            token
        ))

        conn.commit()

        conn.close()

        print(
            f"✅ Firebase token registered for user {user_id}"
        )

        return jsonify({

            "success": True,

            "message": "Firebase token registered"
        })

    except Exception as e:

        print(
            "❌ Firebase token error:",
            str(e)
        )

        return jsonify({

            "success": False,

            "message": str(e)
        }), 500


# ============================================================
# TEST FIREBASE NOTIFICATION
# ============================================================

@app.route(
    "/test-firebase-notification",
    methods=["POST"]
)
def test_firebase_notification():

    if "user_id" not in session:

        return jsonify({
            "success": False,
            "message": "Not logged in"
        }), 401

    if not firebase_initialized:

        return jsonify({
            "success": False,
            "message": "Firebase not initialized"
        }), 500

    try:

        user_id = session["user_id"]

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
            SELECT token
            FROM firebase_tokens
            WHERE user_id = ?
        """, (user_id,))

        rows = cursor.fetchall()

        conn.close()

        if not rows:

            return jsonify({

                "success": False,

                "message":
                    "No Firebase device registered."
            }), 400

        sent = 0

        for row in rows:

            try:

                message = messaging.Message(

                    notification=messaging.Notification(

                        title="🚦 Smart Traffic Test",

                        body="Test notification received successfully."
                    ),

                    token=row["token"]
                )

                messaging.send(message)

                sent += 1

            except Exception as e:

                print(
                    "❌ Test notification error:",
                    str(e)
                )

        if sent == 0:

            return jsonify({

                "success": False,

                "message":
                    "Unable to send notification."
            }), 500

        return jsonify({

            "success": True,

            "message":
                f"Test notification sent to {sent} device(s)."
        })

    except Exception as e:

        print(
            "❌ Test notification error:",
            str(e)
        )

        return jsonify({

            "success": False,

            "message": str(e)
        }), 500


# ============================================================
# UPDATE TRAFFIC
# ============================================================

@app.route(
    "/update_traffic",
    methods=["POST"]
)
def update_traffic():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        # ----------------------------------------------------
        # Read request
        # ----------------------------------------------------

        vehicle_count = int(
            data.get(
                "vehicle_count",
                0
            )
        )

        traffic_status = str(
            data.get(
                "traffic_status",
                "NORMAL"
            )
        ).upper().strip()

        source_id = str(
            data.get(
                "source_id",
                ""
            )
        ).strip()

        sequence = int(
            data.get(
                "sequence",
                0
            )
        )

        # ----------------------------------------------------
        # Validate
        # ----------------------------------------------------

        allowed_statuses = {
            "NORMAL",
            "MODERATE",
            "HEAVY"
        }

        if traffic_status not in allowed_statuses:

            return jsonify({

                "success": False,

                "message":
                    "Invalid traffic status"
            }), 400

        if vehicle_count < 0:

            vehicle_count = 0

        if not source_id:

            return jsonify({

                "success": False,

                "message":
                    "source_id is required"
            }), 400

        if sequence < 1:

            return jsonify({

                "success": False,

                "message":
                    "Invalid sequence"
            }), 400

        # ----------------------------------------------------
        # Open database
        # ----------------------------------------------------

        conn = get_db()

        cursor = conn.cursor()

        # ----------------------------------------------------
        # Lock/update traffic state safely
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                source_id,
                last_sequence,
                last_status
            FROM traffic_state
            WHERE id = 1
        """)

        state = cursor.fetchone()

        stored_source = state["source_id"]

        stored_sequence = state["last_sequence"]

        previous_status = state["last_status"]

        # ----------------------------------------------------
        # NEW DETECTOR SESSION
        #
        # A new source_id means traffic_detection.py
        # was restarted.
        # ----------------------------------------------------

        if stored_source != source_id:

            stored_source = source_id

            stored_sequence = 0

            previous_status = (
                traffic_data.get(
                    "traffic_status",
                    "NORMAL"
                )
            )

        # ----------------------------------------------------
        # Reject old/delayed requests
        # ----------------------------------------------------

        if sequence <= stored_sequence:

            conn.close()

            print(
                f"⏭️ Ignoring old Render request: "
                f"sequence={sequence}, "
                f"last={stored_sequence}"
            )

            return jsonify({

                "success": True,

                "ignored": True,

                "reason":
                    "old_or_duplicate_request",

                "traffic_status":
                    traffic_data["traffic_status"],

                "vehicle_count":
                    traffic_data["vehicle_count"]
            })

        # ----------------------------------------------------
        # Determine whether status changed
        # ----------------------------------------------------

        status_changed = (
            traffic_status != previous_status
        )

        # ----------------------------------------------------
        # Update global dashboard data
        # ----------------------------------------------------

        traffic_data["vehicle_count"] = (
            vehicle_count
        )

        traffic_data["traffic_status"] = (
            traffic_status
        )

        # ----------------------------------------------------
        # Save state BEFORE sending notification.
        #
        # This prevents duplicate notifications if another
        # request arrives while Firebase is sending.
        # ----------------------------------------------------

        cursor.execute("""
            UPDATE traffic_state
            SET
                source_id = ?,
                last_sequence = ?,
                last_status = ?
            WHERE id = 1
        """, (
            source_id,
            sequence,
            traffic_status
        ))

        conn.commit()

        conn.close()

        # ----------------------------------------------------
        # STATUS DID NOT CHANGE
        #
        # Update dashboard only.
        # DO NOT send notification.
        # ----------------------------------------------------

        if not status_changed:

            return jsonify({

                "success": True,

                "notification_sent": False,

                "traffic_status":
                    traffic_status,

                "vehicle_count":
                    vehicle_count,

                "sequence":
                    sequence
            })

        # ----------------------------------------------------
        # STATUS CHANGED
        #
        # Exactly ONE notification for this transition.
        # ----------------------------------------------------

        print("")
        print(
            "=========================================="
        )

        print(
            "🚦 TRAFFIC STATUS CHANGED"
        )

        print(
            f"   Previous : {previous_status}"
        )

        print(
            f"   New      : {traffic_status}"
        )

        print(
            f"   Vehicles : {vehicle_count}"
        )

        print(
            f"   Sequence : {sequence}"
        )

        print(
            "🔔 SENDING TRAFFIC NOTIFICATION"
        )

        sent_count = send_traffic_notification(

            traffic_status,

            vehicle_count
        )

        print(
            f"✅ Notification sent to "
            f"{sent_count} device(s)."
        )

        print(
            "=========================================="
        )

        print("")

        return jsonify({

            "success": True,

            "notification_sent": True,

            "sent_count":
                sent_count,

            "traffic_status":
                traffic_status,

            "vehicle_count":
                vehicle_count,

            "sequence":
                sequence
        })

    except Exception as e:

        print(
            "❌ /update_traffic error:",
            str(e)
        )

        return jsonify({

            "success": False,

            "message": str(e)
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    conn = get_db()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            source_id,
            last_sequence,
            last_status
        FROM traffic_state
        WHERE id = 1
    """)

    state = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM firebase_tokens
    """)

    token_count = cursor.fetchone()["count"]

    conn.close()

    return jsonify({

        "status": "online",

        "firebase": firebase_initialized,

        "traffic": traffic_data,

        "registered_devices":
            token_count,

        "server_sequence":
            state["last_sequence"]
            if state else 0,

        "server_status":
            state["last_status"]
            if state else "NORMAL"
    })


# ============================================================
# RUN LOCALLY
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )