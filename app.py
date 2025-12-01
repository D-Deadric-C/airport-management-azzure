from flask import Flask, request, jsonify, Response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import os
import csv
import io
import random

app = Flask(__name__)
CORS(app)
@app.route("/")
def home():
    return jsonify({
        "message": "Airport Management API is running ✅",
        "status": "ok"
    })


# ----------------- OWNER SETTINGS -----------------
# This is the ONLY email that will become admin.
OWNER_ADMIN_EMAIL = "admin@mail.com"

# ----------------- SAFER DATABASE LOCATION -----------------
os.makedirs(app.instance_path, exist_ok=True)
db_path = os.path.join(app.instance_path, "airport.db")

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ----------------- LOAD AIRPORT DATA -----------------
AIRPORTS_FILE = os.path.join(app.root_path, "airports.json")
if not os.path.exists(AIRPORTS_FILE):
    sample_airports = [
        {"code": "DEL", "city": "Delhi", "country": "India"},
        {"code": "BOM", "city": "Mumbai", "country": "India"},
        {"code": "DXB", "city": "Dubai", "country": "UAE"},
        {"code": "LHR", "city": "London", "country": "UK"},
        {"code": "JFK", "city": "New York", "country": "USA"},
    ]
    with open(AIRPORTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sample_airports, f, indent=2)


def load_airports():
    with open(AIRPORTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------- MODELS -----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # "admin", "passenger", "staff"
    age = db.Column(db.Integer)
    phone = db.Column(db.String(30))
    is_verified = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "age": self.age,
            "phone": self.phone,
            "is_verified": self.is_verified,
        }


class OtpCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(30), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_used = db.Column(db.Boolean, default=False)


class Flight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False)
    source = db.Column(db.String(10), nullable=False)       # IATA code like DEL
    destination = db.Column(db.String(10), nullable=False)  # IATA code
    departure_time = db.Column(db.String(30), nullable=False)
    arrival_time = db.Column(db.String(30), nullable=False)
    total_seats = db.Column(db.Integer, nullable=False)
    available_seats = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="On Time")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "source": self.source,
            "destination": self.destination,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "total_seats": self.total_seats,
            "available_seats": self.available_seats,
            "status": self.status,
        }


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey("flight.id"), nullable=False)
    num_seats = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(30), default="Confirmed")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # pricing fields
    base_price = db.Column(db.Integer, nullable=False, default=0)
    final_price = db.Column(db.Integer, nullable=False, default=0)
    discount_reason = db.Column(db.String(100))

    user = db.relationship("User")
    flight = db.relationship("Flight")

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "flight": self.flight.to_dict(),
            "num_seats": self.num_seats,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "base_price": self.base_price,
            "final_price": self.final_price,
            "discount_reason": self.discount_reason,
        }


class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user": self.user.to_dict(),
            "message": self.message,
            "rating": self.rating,
            "created_at": self.created_at.isoformat(),
        }


class Baggage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_number = db.Column(db.String(50), unique=True, nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"))
    status = db.Column(db.String(50), default="Checked-in")
    last_location = db.Column(db.String(200), default="N/A")

    booking = db.relationship("Booking")

    def to_dict(self):
        return {
            "id": self.id,
            "tag_number": self.tag_number,
            "status": self.status,
            "last_location": self.last_location,
            "booking_id": self.booking_id,
        }


# ----------------- INIT DB -----------------

with app.app_context():
    db.create_all()


# ----------------- HELPER: PRICING -----------------

BASE_PRICE_PER_SEAT = 5000  # demo price


def calculate_price(user: User, num_seats: int):
    base = BASE_PRICE_PER_SEAT * num_seats
    final = base
    reason = None

    # student discount for .edu emails
    if user.email.lower().endswith(".edu"):
        final = int(base * 0.8)
        reason = "Student .edu discount (20%)"

    return base, final, reason


# ----------------- API ROUTES -----------------

# --------- AIRPORTS ---------
@app.route("/api/airports", methods=["GET"])
def get_airports():
    return jsonify(load_airports())


# --------- OTP ---------
@app.route("/api/request-otp", methods=["POST"])
def request_otp():
    data = request.json or {}
    phone = data.get("phone")
    if not phone:
        return jsonify({"error": "phone is required"}), 400

    code = f"{random.randint(0, 999999):06d}"

    otp = OtpCode(phone=phone, code=code, is_used=False)
    db.session.add(otp)
    db.session.commit()

    # In real life you would send via SMS, here we just return it
    return jsonify({"message": "OTP generated", "otp": code})


# --------- AUTH / REGISTER + LOGIN + PASSWORD ---------
@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    phone = data.get("phone")
    age_raw = data.get("age")
    otp_code = data.get("otp")

    if not all([name, email, password, phone, otp_code]):
        return jsonify({"error": "name, email, password, phone and otp are required"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400

    # Verify OTP (simple, no expiry for demo)
    otp = (
        OtpCode.query.filter_by(phone=phone, code=str(otp_code), is_used=False)
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp:
        return jsonify({"error": "Invalid or used OTP"}), 400

    otp.is_used = True

    age = None
    if age_raw is not None:
        try:
            age = int(age_raw)
        except ValueError:
            return jsonify({"error": "age must be a number"}), 400

    # Role is decided on the backend:
    # owner email becomes admin, everyone else passenger
    if email.lower() == OWNER_ADMIN_EMAIL.lower():
        role = "admin"
    else:
        role = "passenger"

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        age=age,
        phone=phone,
        is_verified=True,
    )

    db.session.add(user)
    db.session.commit()
    db.session.commit()  # commit OTP is_used and user

    return jsonify(user.to_dict()), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({"user": user.to_dict()})


@app.route("/api/change-password", methods=["POST"])
def change_password():
    data = request.json or {}
    user_id = data.get("user_id")
    old_password = data.get("old_password")
    new_password = data.get("new_password")

    if not user_id or not old_password or not new_password:
        return jsonify({"error": "user_id, old_password, and new_password are required"}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not check_password_hash(user.password_hash, old_password):
        return jsonify({"error": "Incorrect old password"}), 401

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"message": "Password updated successfully"})


# --------- PROFILE ---------
@app.route("/api/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route("/api/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.json or {}

    if "name" in data:
        user.name = data["name"]

    if "age" in data:
        age_raw = data["age"]
        if age_raw in (None, ""):
            user.age = None
        else:
            try:
                user.age = int(age_raw)
            except ValueError:
                return jsonify({"error": "age must be a number"}), 400

    db.session.commit()
    return jsonify(user.to_dict())


# --------- FLIGHTS ---------
@app.route("/api/flights", methods=["GET"])
def get_flights():
    flights = Flight.query.all()
    return jsonify([f.to_dict() for f in flights])


@app.route("/api/flights", methods=["POST"])
def create_flight():
    data = request.json or {}

    required = ["code", "source", "destination", "departure_time", "arrival_time", "total_seats"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": "Missing required flight fields"}), 400

    airports = load_airports()
    valid_codes = {a["code"] for a in airports}

    if data["source"] not in valid_codes or data["destination"] not in valid_codes:
        return jsonify({"error": "Invalid airport code"}), 400

    if data["source"] == data["destination"]:
        return jsonify({"error": "Source and destination cannot be same"}), 400

    total_seats = int(data["total_seats"])

    flight = Flight(
        code=data["code"],
        source=data["source"],
        destination=data["destination"],
        departure_time=data["departure_time"],
        arrival_time=data["arrival_time"],
        total_seats=total_seats,
        available_seats=total_seats,
        status=data.get("status", "On Time"),
    )

    db.session.add(flight)
    db.session.commit()

    return jsonify(flight.to_dict()), 201


@app.route("/api/flights/<int:flight_id>", methods=["PUT"])
def update_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    data = request.json or {}

    airports = load_airports()
    valid_codes = {a["code"] for a in airports}

    if "source" in data and data["source"] not in valid_codes:
        return jsonify({"error": "Invalid source airport"}), 400

    if "destination" in data and data["destination"] not in valid_codes:
        return jsonify({"error": "Invalid destination airport"}), 400

    for field in [
        "code",
        "source",
        "destination",
        "departure_time",
        "arrival_time",
        "total_seats",
        "available_seats",
        "status",
    ]:
        if field in data:
            setattr(flight, field, data[field])

    db.session.commit()
    return jsonify(flight.to_dict())


@app.route("/api/flights/<int:flight_id>", methods=["DELETE"])
def delete_flight(flight_id):
    flight = Flight.query.get_or_404(flight_id)
    db.session.delete(flight)
    db.session.commit()
    return jsonify({"message": "Deleted"})


# --------- BOOKINGS ---------
@app.route("/api/bookings", methods=["POST"])
def create_booking():
    data = request.json or {}

    user = User.query.get_or_404(data["user_id"])
    flight = Flight.query.get_or_404(data["flight_id"])
    num_seats = int(data.get("num_seats", 1))

    if num_seats <= 0:
        return jsonify({"error": "Number of seats must be positive"}), 400

    if flight.available_seats < num_seats:
        return jsonify({"error": "Not enough seats available"}), 400

    base_price, final_price, reason = calculate_price(user, num_seats)

    booking = Booking(
        user_id=user.id,
        flight_id=flight.id,
        num_seats=num_seats,
        base_price=base_price,
        final_price=final_price,
        discount_reason=reason,
    )
    flight.available_seats -= num_seats

    db.session.add(booking)
    db.session.commit()

    return jsonify(booking.to_dict()), 201


@app.route("/api/bookings/user/<int:user_id>", methods=["GET"])
def get_user_bookings(user_id):
    bookings = Booking.query.filter_by(user_id=user_id).order_by(Booking.created_at.desc()).all()
    return jsonify([b.to_dict() for b in bookings])


# --------- FEEDBACK ---------
@app.route("/api/feedback", methods=["POST"])
def create_feedback():
    data = request.json or {}

    fb = Feedback(
        user_id=data["user_id"],
        message=data["message"],
        rating=data["rating"],
    )

    db.session.add(fb)
    db.session.commit()

    return jsonify(fb.to_dict()), 201


@app.route("/api/feedback", methods=["GET"])
def list_feedback():
    feedback = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return jsonify([f.to_dict() for f in feedback])


@app.route("/api/feedback/user/<int:user_id>", methods=["GET"])
def list_user_feedback(user_id):
    feedback = Feedback.query.filter_by(user_id=user_id).order_by(Feedback.created_at.desc()).all()
    return jsonify([f.to_dict() for f in feedback])


# --------- BAGGAGE ---------
@app.route("/api/baggage", methods=["POST"])
def create_baggage():
    data = request.json or {}

    bag = Baggage(
        tag_number=data["tag_number"],
        booking_id=data.get("booking_id"),
        status=data.get("status", "Checked-in"),
        last_location=data.get("last_location", "N/A"),
    )

    db.session.add(bag)
    db.session.commit()

    return jsonify(bag.to_dict()), 201


@app.route("/api/baggage/<string:tag_number>", methods=["GET"])
def get_baggage(tag_number):
    bag = Baggage.query.filter_by(tag_number=tag_number).first()

    if not bag:
        return jsonify({"error": "Not found"}), 404

    return jsonify(bag.to_dict())


# --------- ADMIN SUMMARY / CSV / IMPORT ---------
@app.route("/api/admin/summary", methods=["GET"])
def admin_summary():
    total_users = User.query.count()
    total_passengers = User.query.filter_by(role="passenger").count()
    total_employees = total_users - total_passengers
    total_flights = Flight.query.count()
    total_bookings = Booking.query.count()
    total_feedback = Feedback.query.count()

    return jsonify({
        "total_users": total_users,
        "total_passengers": total_passengers,
        "total_employees": total_employees,
        "total_flights": total_flights,
        "total_bookings": total_bookings,
        "total_feedback": total_feedback,
    })


@app.route("/api/admin/import-employees", methods=["POST"])
def import_employees():
    """
    Expects JSON: { "path": "employees.csv" }
    CSV format: name,email,password,role(optional)
    """
    data = request.json or {}
    path = data.get("path")
    if not path:
        return jsonify({"error": "path is required"}), 400

    # path is relative to backend folder
    abs_path = os.path.join(app.root_path, path)

    if not os.path.exists(abs_path):
        return jsonify({"error": f"File not found: {abs_path}"}), 400

    created = 0
    skipped = 0

    with open(abs_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            email = row.get("email")
            name = row.get("name")
            password = row.get("password", "password123")
            role = row.get("role", "staff")

            if not email or not name:
                continue

            if User.query.filter_by(email=email).first():
                skipped += 1
                continue

            u = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                is_verified=True,
            )
            db.session.add(u)
            created += 1

    db.session.commit()

    return jsonify({"created": created, "skipped_existing": skipped})


@app.route("/api/admin/feedback-export", methods=["GET"])
def feedback_export_csv():
    feedback = Feedback.query.order_by(Feedback.created_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "user_name", "user_email", "rating", "message", "created_at"])
    for f in feedback:
        writer.writerow([
            f.id,
            f.user.name,
            f.user.email,
            f.rating,
            f.message,
            f.created_at.isoformat(),
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedback.csv"},
    )


# ----------------- RUN -----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

