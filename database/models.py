from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    dob = db.Column(db.Date, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), default='admin')
    is_verified = db.Column(db.Boolean, default=False)

class OTP(db.Model):
    __tablename__ = 'otps'
    id = db.Column(db.Integer, primary_key=True)
    contact_hash = db.Column(db.String(64), nullable=False)   # SHA-256 hash of contact
    code_encrypted = db.Column(db.Text, nullable=False)        # AES-256-GCM encrypted OTP
    purpose = db.Column(db.String(20), default='login')        # register / login
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used = db.Column(db.Boolean, default=False)
    attempts = db.Column(db.Integer, default=0)                # brute-force protection

class Business(db.Model):
    __tablename__ = 'business'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120))
    address = db.Column(db.Text)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    gst_number = db.Column(db.String(50))
    logo = db.Column(db.String(200), nullable=True)
    logo_size = db.Column(db.String(10), default='medium')
    signature = db.Column(db.String(200), nullable=True)
    terms = db.Column(db.Text, nullable=True)
    logo_data = db.Column(db.LargeBinary, nullable=True)
    logo_mimetype = db.Column(db.String(50), nullable=True)
    signature_data = db.Column(db.LargeBinary, nullable=True)
    signature_mimetype = db.Column(db.String(50), nullable=True)

class Customer(db.Model):
    __tablename__ = 'customers'
    customer_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    email = db.Column(db.String(120))
    bills = db.relationship('Bill', backref='customer', lazy=True)

class Product(db.Model):
    __tablename__ = 'products'
    product_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80))
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    gst = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    barcode = db.Column(db.String(100))

class Bill(db.Model):
    __tablename__ = 'bills'
    bill_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    subtotal = db.Column(db.Float, default=0.0)
    gst_amount = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    payment_method = db.Column(db.String(30), default='cash')
    payment_status = db.Column(db.String(20), default='paid')  # paid / pending / partial
    notes = db.Column(db.Text, nullable=True)
    items = db.relationship('BillItem', backref='bill', lazy=True, cascade='all, delete-orphan')

class BillItem(db.Model):
    __tablename__ = 'bill_items'
    bill_item_id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.bill_id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.product_id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    gst = db.Column(db.Float, default=0.0)
    product = db.relationship('Product')
