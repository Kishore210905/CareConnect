"""CareConnect: healthcare appointment and medication management (Flask + MySQL).

Infrastructure endpoints (/health, /version, /db, /stress) are used by the ALB, CI/CD and demos.
DEMO SOFTWARE: not a certified medical system. Do not store real patient data.
"""
import os
import re
import secrets
import socket
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

import mysql.connector
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from app import config, db

BASE_DIR = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
HOST = socket.gethostname()
TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Kolkata"))

app.config.update(
    SECRET_KEY=config.flask_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
app.teardown_appcontext(db.close_db)

NO_CSRF_ENDPOINTS = {"health", "version", "db_check", "stress", "static"}
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


# ------------------------------------------------------------------ helpers
def now_local():
    return datetime.now(TZ).replace(tzinfo=None)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token, "app_version": APP_VERSION, "host": HOST}


@app.before_request
def protect_forms():
    if request.method == "POST" and request.endpoint not in NO_CSRF_ENDPOINTS:
        sent = request.form.get("csrf_token", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
            abort(400, "Your session expired or the form was invalid. Please reload the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    if "uid" in session:
        resp.headers["Cache-Control"] = "no-store"  # do not cache personal pages
    return resp


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "uid" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("dashboard")


def check_slot(doctor, when, now):
    """Return an error message if the requested slot is not bookable, else None."""
    if when <= now:
        return "Please choose a future date and time."
    if when > now + timedelta(days=90):
        return "Appointments can be booked up to 90 days ahead."
    days = [d.strip() for d in (doctor.get("available_days") or "").split(",") if d.strip()]
    if when.strftime("%a") not in days:
        return f"{doctor['name']} is available on: {', '.join(days)}."
    if not 9 <= when.hour < 17:
        return "Appointments are available between 09:00 and 17:00."
    if when.minute not in (0, 30):
        return "Please choose a time on the hour or half hour."
    return None


# ------------------------------------------------------------------ error handling
@app.errorhandler(mysql.connector.Error)
def database_error(exc):
    app.logger.error("Database error: %s", exc)
    return render_template("error.html", code=503,
                           message="The database is temporarily unavailable. Please try again in a moment."), 503


@app.errorhandler(HTTPException)
def http_error(exc):
    return render_template("error.html", code=exc.code, message=exc.description), exc.code


# ------------------------------------------------------------------ public pages + auth
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        email = f.get("email", "").strip().lower()
        password = f.get("password", "")
        errors = []
        if not name or len(name) > 100:
            errors.append("Name is required (max 100 characters).")
        if not EMAIL_RE.fullmatch(email) or len(email) > 150:
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != f.get("confirm", ""):
            errors.append("Passwords do not match.")
        if not errors:
            try:
                db.execute("INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,'patient')",
                           (name, email, generate_password_hash(password)))
            except mysql.connector.errors.IntegrityError:
                errors.append("An account with this email already exists.")
            else:
                flash("Account created. Please sign in.", "ok")
                return redirect(url_for("login"))
        for e in errors:
            flash(e, "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.query("SELECT id, name, password FROM users WHERE email=%s", (email,), one=True)
        if user and check_password_hash(user["password"], password):
            session.clear()
            session.permanent = True
            session["uid"], session["user_name"] = user["id"], user["name"]
            return redirect(safe_next(request.args.get("next")))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))


# ------------------------------------------------------------------ patient features
@app.route("/dashboard")
@login_required
def dashboard():
    uid, now = session["uid"], now_local()
    upcoming = db.query("SELECT COUNT(*) AS n FROM appointments WHERE patient_id=%s AND status='Booked' "
                        "AND appointment_date >= %s", (uid, now), one=True)["n"]
    meds = db.query("SELECT COUNT(*) AS n FROM medications WHERE patient_id=%s", (uid,), one=True)["n"]
    nxt = db.query("SELECT a.appointment_date, d.name AS doctor_name, d.specialization "
                   "FROM appointments a JOIN doctors d ON a.doctor_id=d.id "
                   "WHERE a.patient_id=%s AND a.status='Booked' AND a.appointment_date >= %s "
                   "ORDER BY a.appointment_date LIMIT 1", (uid, now), one=True)
    return render_template("dashboard.html", name=session["user_name"], upcoming=upcoming, meds=meds, nxt=nxt)


@app.route("/doctors")
def doctors():
    return render_template("doctors.html", doctors=db.query("SELECT * FROM doctors ORDER BY name"))


@app.route("/book/<int:doctor_id>", methods=["GET", "POST"])
@login_required
def book(doctor_id):
    doctor = db.query("SELECT * FROM doctors WHERE id=%s", (doctor_id,), one=True)
    if doctor is None:
        abort(404)
    now = now_local()
    if request.method == "POST":
        raw = request.form.get("appointment_date", "")
        reason = request.form.get("reason", "").strip()
        errors = []
        when = None
        try:
            when = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            errors.append("Please choose a valid date and time.")
        if when:
            msg = check_slot(doctor, when, now)
            if msg:
                errors.append(msg)
        if not reason or len(reason) > 500:
            errors.append("Please describe the reason for the visit (max 500 characters).")
        if not errors:
            if db.query("SELECT id FROM appointments WHERE doctor_id=%s AND appointment_date=%s AND status='Booked'",
                        (doctor_id, when), one=True):
                errors.append("That slot is already taken. Please choose another time.")
            elif db.query("SELECT id FROM appointments WHERE patient_id=%s AND appointment_date=%s AND status='Booked'",
                          (session["uid"], when), one=True):
                errors.append("You already have an appointment at that time.")
        if not errors:
            db.execute("INSERT INTO appointments(patient_id,doctor_id,appointment_date,reason,status) "
                       "VALUES(%s,%s,%s,%s,'Booked')", (session["uid"], doctor_id, when, reason))
            flash("Appointment booked.", "ok")
            return redirect(url_for("appointments"))
        for e in errors:
            flash(e, "error")
    return render_template("book.html", doctor=doctor, min_dt=now.strftime("%Y-%m-%dT%H:%M"))


@app.route("/appointments")
@login_required
def appointments():
    rows = db.query("SELECT a.*, d.name AS doctor_name, d.specialization "
                    "FROM appointments a JOIN doctors d ON a.doctor_id=d.id "
                    "WHERE a.patient_id=%s ORDER BY a.appointment_date DESC", (session["uid"],))
    return render_template("appointments.html", appointments=rows, now=now_local())


@app.route("/cancel/<int:appointment_id>", methods=["POST"])
@login_required
def cancel(appointment_id):
    _, changed = db.execute("UPDATE appointments SET status='Cancelled' "
                            "WHERE id=%s AND patient_id=%s AND status='Booked'", (appointment_id, session["uid"]))
    flash("Appointment cancelled." if changed else "Nothing to cancel.", "info")
    return redirect(url_for("appointments"))


@app.route("/medications", methods=["GET", "POST"])
@login_required
def medications():
    if request.method == "POST":
        medicine = request.form.get("medicine", "").strip()
        dosage = request.form.get("dosage", "").strip()
        schedule = request.form.get("schedule", "").strip()
        if not medicine or len(medicine) > 150 or len(dosage) > 100 or len(schedule) > 100:
            flash("Medicine name is required; dosage and schedule must be under 100 characters.", "error")
        else:
            db.execute("INSERT INTO medications(patient_id,medicine,dosage,schedule) VALUES(%s,%s,%s,%s)",
                       (session["uid"], medicine, dosage, schedule))
            flash("Medication added.", "ok")
            return redirect(url_for("medications"))
    rows = db.query("SELECT * FROM medications WHERE patient_id=%s ORDER BY id DESC", (session["uid"],))
    return render_template("medications.html", medications=rows)


@app.route("/medications/<int:med_id>/delete", methods=["POST"])
@login_required
def medication_delete(med_id):
    db.execute("DELETE FROM medications WHERE id=%s AND patient_id=%s", (med_id, session["uid"]))
    flash("Medication removed.", "info")
    return redirect(url_for("medications"))


# ------------------------------------------------------------------ infrastructure endpoints
@app.route("/health")
def health():
    # Independent of the database on purpose: a DB blip must not make the ALB kill every instance.
    return jsonify({"status": "healthy", "version": APP_VERSION}), 200


@app.route("/version")
def version():
    return jsonify({"version": APP_VERSION, "host": HOST})


@app.route("/db")
def db_check():
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(database="connected"), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify(database="unreachable", error=type(exc).__name__), 503


@app.route("/stress")
def stress():
    """LAB ONLY: burn CPU to trigger auto scaling. Disabled unless ENABLE_STRESS=true."""
    if os.getenv("ENABLE_STRESS", "false").lower() != "true":
        return jsonify(error="disabled"), 404
    seconds = min(int(request.args.get("seconds", 30)), 50)  # ALB idle timeout is 60s
    end = time.time() + seconds
    while time.time() < end:
        _ = sum(i * i for i in range(10000))
    return jsonify(burned_seconds=seconds)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
