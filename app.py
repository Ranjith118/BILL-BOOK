from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify, send_file, abort, Response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy import func
import os, csv, io, re

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized

from database.models import db, User, Business, Customer, Product, Bill, BillItem
from utils.invoice_generator import generate_invoice_pdf

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('BILLBOOK_SECRET', 'billbook-change-in-production')

# Use PostgreSQL on Render, SQLite locally
# Use PostgreSQL if DATABASE_URL is set, otherwise SQLite
database_url = os.environ.get('DATABASE_URL', '')
if database_url:
    database_url = database_url.replace('postgres://', 'postgresql+pg8000://')
    database_url = database_url.replace('postgresql://', 'postgresql+pg8000://')
else:
    # SQLite for local dev and when no DB is configured
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'billbook.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    database_url = 'sqlite:///' + db_path
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'images')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Secure cookies on production (HTTPS)
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('RENDER', False)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'instance'), exist_ok=True)

# Google OAuth — allow HTTP only in dev
if not os.environ.get('RENDER'):
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID', ''),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
    scope=['openid', 'https://www.googleapis.com/auth/userinfo.email',
           'https://www.googleapis.com/auth/userinfo.profile'],
    redirect_url=os.environ.get('GOOGLE_REDIRECT_URL', None)
)
app.register_blueprint(google_bp, url_prefix='/auth')

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def _is_email(contact):
    return bool(re.match(r'^[\w\.\+\-]+@[\w\.-]+\.\w{2,}$', contact.strip()))

# ─── Auth ────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if User.query.count() == 0:
        return redirect(url_for('register'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if not user or not user.password_hash:
            flash('No account found with this email.', 'danger')
            return render_template('login.html')
        if not check_password_hash(user.password_hash, password):
            flash('Incorrect password.', 'danger')
            return render_template('login.html')
        login_user(user)
        return redirect(url_for('setup') if not Business.query.first() else url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        dob_str   = request.form.get('dob', '').strip()
        email     = request.form.get('email', '').strip().lower()
        password  = request.form.get('password', '')
        confirm   = request.form.get('confirm_password', '')
        if not full_name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        if not _is_email(email):
            flash('Enter a valid email address.', 'danger')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('Account already exists. Please login.', 'danger')
            return redirect(url_for('login'))
        dob_date = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        user = User(full_name=full_name, email=email, dob=dob_date,
                    password_hash=generate_password_hash(password),
                    role='admin', is_verified=True)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Account created! Set up your business to continue.', 'success')
        return redirect(url_for('setup'))
    return render_template('register.html')

@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not token:
        flash('Google login failed.', 'danger')
        return redirect(url_for('login'))
    resp = blueprint.session.get('/oauth2/v2/userinfo')
    if not resp.ok:
        flash('Could not fetch Google account info.', 'danger')
        return redirect(url_for('login'))
    info = resp.json()
    email = info.get('email', '').strip().lower()
    full_name = info.get('name', '')
    user = User.query.filter_by(email=email).first()
    if user:
        login_user(user)
        next_url = url_for('setup') if not Business.query.first() else url_for('dashboard')
        return redirect(next_url)
    session['google_email']     = email
    session['google_full_name'] = full_name
    return redirect(url_for('google_complete_profile'))

@app.route('/auth/google/authorized')
def google_authorized():
    # Handled by oauth_authorized signal above
    return redirect(url_for('dashboard'))
@app.route('/google/complete-profile', methods=['GET', 'POST'])
def google_complete_profile():
    email = session.get('google_email')
    if not email:
        return redirect(url_for('login'))
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip() or session.get('google_full_name', '')
        dob_str   = request.form.get('dob', '').strip()
        dob_date  = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
        user = User(full_name=full_name, email=email, dob=dob_date,
                    role='admin', is_verified=True)
        db.session.add(user)
        db.session.commit()
        session.pop('google_email', None)
        session.pop('google_full_name', None)
        login_user(user)
        flash('Account created! Set up your business to continue.', 'success')
        return redirect(url_for('setup'))
    return render_template('google_complete_profile.html',
                           email=email,
                           full_name=session.get('google_full_name', ''))

@app.route('/register/send-otp', methods=['POST'])
def register_send_otp():
    full_name = request.form.get('full_name', '').strip()
    dob       = request.form.get('dob', '').strip()
    email     = request.form.get('contact', '').strip().lower()
    if not full_name or not email:
        flash('Name and email are required.', 'danger')
        return render_template('register.html')
    if not is_email(email):
        flash('Enter a valid email address.', 'danger')
        return render_template('register.html')
    if User.query.filter_by(email=email).first():
        flash('Account already exists with this email. Please login.', 'danger')
        return redirect(url_for('login'))
    session['reg_full_name'] = full_name
    session['reg_dob']       = dob
    session['reg_contact']   = email
    try:
        _generate_and_send_otp(email, 'register')
    except EnvironmentError as e:
        flash(str(e), 'danger')
        return render_template('register.html')
    flash('OTP sent. Check your email inbox.', 'info')
    return render_template('otp_verify.html', contact=email, purpose='register')

@app.route('/register/verify-otp', methods=['POST'])
def register_verify_otp():
    email = request.form.get('contact', '').strip().lower()
    code  = request.form.get('otp', '').strip()
    if not _verify_otp(email, code, 'register'):
        flash('Invalid or expired OTP. Try again.', 'danger')
        return render_template('otp_verify.html', contact=email, purpose='register')
    full_name = session.pop('reg_full_name', '')
    dob_str   = session.pop('reg_dob', '')
    dob_date  = datetime.strptime(dob_str, '%Y-%m-%d').date() if dob_str else None
    user = User(full_name=full_name, email=email, dob=dob_date, role='admin', is_verified=True)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    flash('Account created! Set up your business to continue.', 'success')
    return redirect(url_for('setup'))

# ─── Password-based Login & Register ─────────────────────────────────────────

@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    if request.method == 'POST':
        logo_filename = None
        if 'logo' in request.files and request.files['logo'].filename:
            f = request.files['logo']
            logo_filename = secure_filename(f.filename)
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename))
        biz = Business.query.first()
        if biz:
            biz.name = request.form['name']; biz.address = request.form['address']
            biz.phone = request.form['phone']; biz.email = request.form['email']
            biz.gst_number = request.form['gst_number']
            if logo_filename: biz.logo = logo_filename
        else:
            biz = Business(name=request.form['name'], address=request.form['address'],
                           phone=request.form['phone'], email=request.form['email'],
                           gst_number=request.form['gst_number'], logo=logo_filename)
            db.session.add(biz)
        db.session.commit()
        flash('Business setup complete. Welcome to BillBook!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('setup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    if not Business.query.first():
        return redirect(url_for('setup'))
    today = date.today()
    seven_days_ago = today - timedelta(days=7)

    try:
        total_sales_today = db.session.query(func.sum(Bill.total_amount)).filter(
            func.cast(Bill.date, db.Date) == today).scalar() or 0
    except Exception:
        total_sales_today = 0

    total_bills = Bill.query.count()
    total_customers = Customer.query.count()
    total_products = Product.query.count()
    low_stock = Product.query.filter(Product.stock < 5).all()

    try:
        monthly = db.session.query(
            func.to_char(Bill.date, 'YYYY-MM').label('month'),
            func.sum(Bill.total_amount).label('revenue')
        ).group_by(func.to_char(Bill.date, 'YYYY-MM')).order_by('month').limit(6).all()
    except Exception:
        # SQLite fallback
        monthly = db.session.query(
            func.strftime('%Y-%m', Bill.date).label('month'),
            func.sum(Bill.total_amount).label('revenue')
        ).group_by('month').order_by('month').limit(6).all()

    try:
        daily = db.session.query(
            func.to_char(Bill.date, 'DD-MM').label('day'),
            func.sum(Bill.total_amount).label('sales')
        ).filter(Bill.date >= seven_days_ago).group_by(
            func.to_char(Bill.date, 'DD-MM')).order_by('day').all()
    except Exception:
        daily = db.session.query(
            func.strftime('%d-%m', Bill.date).label('day'),
            func.sum(Bill.total_amount).label('sales')
        ).filter(Bill.date >= seven_days_ago).group_by('day').order_by('day').all()

    return render_template('dashboard.html',
        total_sales_today=total_sales_today, total_bills=total_bills,
        total_customers=total_customers, total_products=total_products,
        low_stock=low_stock,
        monthly_labels=[r.month for r in monthly], monthly_data=[r.revenue for r in monthly],
        daily_labels=[r.day for r in daily], daily_data=[r.sales for r in daily],
    )

# ─── Business ────────────────────────────────────────────────────────────────

@app.route('/business', methods=['GET', 'POST'])
@login_required
def business():
    biz = Business.query.first()
    if request.method == 'POST':
        logo_filename = biz.logo if biz else None
        sig_filename  = biz.signature if biz else None
        logo_data = biz.logo_data if biz else None
        logo_mime = biz.logo_mimetype if biz else None
        sig_data  = biz.signature_data if biz else None
        sig_mime  = biz.signature_mimetype if biz else None

        if 'logo' in request.files and request.files['logo'].filename:
            f = request.files['logo']
            logo_filename = secure_filename(f.filename)
            logo_mime = f.mimetype
            f.seek(0); logo_data = f.read()
            f.seek(0); f.save(os.path.join(app.config['UPLOAD_FOLDER'], logo_filename))

        if 'signature' in request.files and request.files['signature'].filename:
            f = request.files['signature']
            sig_filename = secure_filename(f.filename)
            sig_mime = f.mimetype
            f.seek(0); sig_data = f.read()
            f.seek(0); f.save(os.path.join(app.config['UPLOAD_FOLDER'], sig_filename))

        if request.form.get('clear_logo'):
            logo_filename = None; logo_data = None; logo_mime = None
        if request.form.get('clear_signature'):
            sig_filename = None; sig_data = None; sig_mime = None

        data = dict(name=request.form['name'], address=request.form['address'],
                    phone=request.form['phone'], email=request.form['email'],
                    gst_number=request.form['gst_number'],
                    logo=logo_filename, signature=sig_filename,
                    logo_size=request.form.get('logo_size', 'medium'),
                    logo_data=logo_data, logo_mimetype=logo_mime,
                    signature_data=sig_data, signature_mimetype=sig_mime,
                    terms=request.form.get('terms', '').strip()
                          or request.form.get('terms_hidden', '').strip() or None)
        if biz:
            for k, v in data.items(): setattr(biz, k, v)
        else:
            biz = Business(**data); db.session.add(biz)
        db.session.commit()
        flash('Business details saved.', 'success')
        return redirect(url_for('business'))
    return render_template('business.html', biz=biz)


@app.route('/biz-image/<string:kind>')
def biz_image(kind):
    """Serve logo or signature from DB (works on cloud where filesystem is ephemeral)."""
    from flask import Response as FlaskResponse
    biz = Business.query.first()
    if not biz: return '', 404
    if kind == 'logo' and biz.logo_data:
        return FlaskResponse(biz.logo_data, mimetype=biz.logo_mimetype or 'image/png')
    if kind == 'signature' and biz.signature_data:
        return FlaskResponse(biz.signature_data, mimetype=biz.signature_mimetype or 'image/png')
    return '', 404

# ─── Customers ───────────────────────────────────────────────────────────────

@app.route('/customers')
@login_required
def customers():
    q = request.args.get('q', '')
    query = Customer.query
    if q:
        query = query.filter(Customer.name.ilike(f'%{q}%') | Customer.phone.ilike(f'%{q}%'))
    return render_template('customers.html', customers=query.all(), q=q)

@app.route('/customers/<int:id>/bills')
@login_required
def customer_bills(id):
    c = Customer.query.get_or_404(id)
    bills = Bill.query.filter_by(customer_id=id).order_by(Bill.date.desc()).all()
    total_spent = sum(b.total_amount for b in bills)
    return render_template('customer_bills.html', customer=c, bills=bills, total_spent=total_spent)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        c = Customer(name=request.form['name'], phone=request.form['phone'],
                     address=request.form['address'], email=request.form['email'])
        db.session.add(c); db.session.commit()
        flash('Customer added.', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)

@app.route('/customers/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_customer(id):
    c = Customer.query.get_or_404(id)
    if request.method == 'POST':
        c.name = request.form['name']; c.phone = request.form['phone']
        c.address = request.form['address']; c.email = request.form['email']
        db.session.commit(); flash('Customer updated.', 'success')
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=c)

@app.route('/customers/delete/<int:id>', methods=['POST'])
@login_required
def delete_customer(id):
    c = Customer.query.get_or_404(id)
    db.session.delete(c); db.session.commit()
    flash('Customer deleted.', 'info')
    return redirect(url_for('customers'))

# ─── Products ────────────────────────────────────────────────────────────────

@app.route('/products')
@login_required
def products():
    q = request.args.get('q', '')
    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f'%{q}%') | Product.category.ilike(f'%{q}%'))
    return render_template('products.html', products=query.all(), q=q)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        p = Product(name=request.form['name'], category=request.form['category'],
                    price=float(request.form['price']), stock=int(request.form['stock']),
                    gst=float(request.form['gst']), description=request.form['description'],
                    barcode=request.form.get('barcode') or None)
        db.session.add(p); db.session.commit()
        flash('Product added.', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', product=None)

@app.route('/products/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    p = Product.query.get_or_404(id)
    if request.method == 'POST':
        p.name = request.form['name']; p.category = request.form['category']
        p.price = float(request.form['price']); p.stock = int(request.form['stock'])
        p.gst = float(request.form['gst']); p.description = request.form['description']
        p.barcode = request.form.get('barcode') or None
        db.session.commit(); flash('Product updated.', 'success')
        return redirect(url_for('products'))
    return render_template('product_form.html', product=p)

@app.route('/products/delete/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    p = Product.query.get_or_404(id)
    db.session.delete(p); db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('products'))

@app.route('/api/product/<int:id>')
@login_required
def api_product(id):
    p = Product.query.get_or_404(id)
    return jsonify({'id': p.product_id, 'name': p.name, 'price': p.price, 'gst': p.gst, 'stock': p.stock})

@app.route('/api/product/barcode/<code>')
@login_required
def api_product_barcode(code):
    p = Product.query.filter_by(barcode=code).first()
    if not p: return jsonify({'error': 'Not found'}), 404
    return jsonify({'id': p.product_id, 'name': p.name, 'price': p.price, 'gst': p.gst, 'stock': p.stock})

# ─── Billing ─────────────────────────────────────────────────────────────────

@app.route('/billing', methods=['GET', 'POST'])
@login_required
def billing():
    customers_list = Customer.query.all()
    products_list = Product.query.all()
    biz = Business.query.first()
    default_terms = biz.terms if biz and biz.terms else ''
    if request.method == 'POST':
        customer_id = int(request.form['customer_id'])
        discount = float(request.form.get('discount', 0))
        payment_method = request.form.get('payment_method', 'cash')
        payment_status = request.form.get('payment_status', 'paid')
        notes = request.form.get('notes', '').strip()
        product_ids = request.form.getlist('product_id[]')
        quantities = request.form.getlist('quantity[]')
        bill = Bill(customer_id=customer_id, discount=discount,
                    payment_method=payment_method, payment_status=payment_status,
                    notes=notes or None)
        db.session.add(bill); db.session.flush()
        subtotal = 0; gst_total = 0
        for pid, qty in zip(product_ids, quantities):
            p = Product.query.get(int(pid)); qty = int(qty)
            if p and qty > 0:
                item_sub = p.price * qty; item_gst = item_sub * p.gst / 100
                subtotal += item_sub; gst_total += item_gst
                db.session.add(BillItem(bill_id=bill.bill_id, product_id=p.product_id,
                                        quantity=qty, price=p.price, gst=p.gst))
                p.stock = max(0, p.stock - qty)
        bill.subtotal = round(subtotal, 2)
        bill.gst_amount = round(gst_total, 2)
        bill.total_amount = round(subtotal + gst_total - discount, 2)
        db.session.commit()
        _save_invoice_pdf(bill)
        flash(f'Bill #{bill.bill_id} created successfully.', 'success')
        return redirect(url_for('invoice', bill_id=bill.bill_id))
    return render_template('billing.html', customers=customers_list,
                           products=products_list, default_terms=default_terms)

# ─── Invoice ─────────────────────────────────────────────────────────────────

def _invoice_pdf_path(bill_id):
    folder = os.path.join(os.path.dirname(__file__), 'static', 'invoices')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f'invoice_{bill_id}.pdf')

def _save_invoice_pdf(bill):
    biz = Business.query.first()
    buf = generate_invoice_pdf(bill, biz)
    with open(_invoice_pdf_path(bill.bill_id), 'wb') as f:
        f.write(buf.read())

@app.route('/invoice/<int:bill_id>')
@login_required
def invoice(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    biz = Business.query.first()
    if not os.path.exists(_invoice_pdf_path(bill_id)):
        _save_invoice_pdf(bill)
    pdf_url = url_for('invoice_pdf_download', bill_id=bill_id, _external=True)
    return render_template('invoice.html', bill=bill, biz=biz, pdf_url=pdf_url)

@app.route('/invoice/<int:bill_id>/pdf')
@login_required
def invoice_pdf(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    biz = Business.query.first()
    buf = generate_invoice_pdf(bill, biz)
    return send_file(buf, mimetype='application/pdf',
                     download_name=f'invoice_{bill_id}.pdf', as_attachment=False)

@app.route('/invoice/<int:bill_id>/download')
@login_required
def invoice_pdf_download(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    _save_invoice_pdf(bill)  # always regenerate fresh
    path = _invoice_pdf_path(bill_id)
    return send_file(path, mimetype='application/pdf',
                     download_name=f'invoice_{bill_id}.pdf', as_attachment=True)

@app.route('/invoice/<int:bill_id>/share')
def invoice_share(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    biz = Business.query.first()
    return render_template('invoice_share.html', bill=bill, biz=biz)

# ─── Bills ───────────────────────────────────────────────────────────────────

@app.route('/bills')
@login_required
def bills():
    q = request.args.get('q', '').strip()
    date_filter = request.args.get('date', '').strip()
    query = Bill.query
    if q and q.isdigit():
        query = query.filter(Bill.bill_id == int(q))
    if date_filter:
        query = query.filter(func.cast(Bill.date, db.Date) == date_filter)
    return render_template('bills.html', bills=query.order_by(Bill.date.desc()).all(),
                           q=q, date_filter=date_filter)

@app.route('/bills/delete/<int:bill_id>', methods=['POST'])
@login_required
def delete_bill(bill_id):
    if current_user.role != 'admin': abort(403)
    bill = Bill.query.get_or_404(bill_id)
    db.session.delete(bill); db.session.commit()
    flash('Bill deleted.', 'info')
    return redirect(url_for('bills'))

# ─── Reports ─────────────────────────────────────────────────────────────────

@app.route('/reports')
@login_required
def reports():
    top_products = db.session.query(
        Product.name, func.sum(BillItem.quantity).label('total_qty')
    ).join(BillItem).group_by(Product.product_id)\
     .order_by(func.sum(BillItem.quantity).desc()).limit(5).all()

    try:
        monthly = db.session.query(
            func.to_char(Bill.date, 'Mon YYYY').label('month'),
            func.sum(Bill.total_amount).label('revenue')
        ).group_by(func.to_char(Bill.date, 'YYYY-MM'), func.to_char(Bill.date, 'Mon YYYY'))\
         .order_by(func.to_char(Bill.date, 'YYYY-MM')).limit(12).all()
    except Exception:
        monthly = db.session.query(
            func.strftime('%b %Y', Bill.date).label('month'),
            func.sum(Bill.total_amount).label('revenue')
        ).group_by(func.strftime('%Y-%m', Bill.date))\
         .order_by(func.strftime('%Y-%m', Bill.date)).limit(12).all()

    total_revenue = db.session.query(func.sum(Bill.total_amount)).scalar() or 0
    return render_template('reports.html',
        top_products=top_products,
        monthly_labels=[r.month for r in monthly],
        monthly_data=[r.revenue for r in monthly],
        total_revenue=total_revenue,
    )

# ─── Users ───────────────────────────────────────────────────────────────────

@app.route('/users')
@login_required
def users():
    if current_user.role != 'admin': abort(403)
    return render_template('users.html', users=User.query.all())

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if current_user.role != 'admin': abort(403)
    if request.method == 'POST':
        contact = request.form['contact'].strip()
        u = User(full_name=request.form['full_name'], role=request.form['role'], is_verified=True)
        if is_email(contact): u.email = contact
        else: u.phone = contact
        db.session.add(u); db.session.commit()
        flash('User added.', 'success')
        return redirect(url_for('users'))
    return render_template('user_form.html', user=None)

@app.route('/users/delete/<int:id>', methods=['POST'])
@login_required
def delete_user(id):
    if current_user.role != 'admin': abort(403)
    u = User.query.get_or_404(id)
    db.session.delete(u); db.session.commit()
    flash('User deleted.', 'info')
    return redirect(url_for('users'))

# ─── Profile ─────────────────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form['full_name'].strip()
        dob_str = request.form.get('dob', '')
        if dob_str:
            current_user.dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

# ─── Duplicate Bill ───────────────────────────────────────────────────────────

@app.route('/bills/duplicate/<int:bill_id>', methods=['POST'])
@login_required
def duplicate_bill(bill_id):
    original = Bill.query.get_or_404(bill_id)
    new_bill = Bill(
        customer_id=original.customer_id,
        discount=original.discount,
        payment_method=original.payment_method,
        payment_status='pending',
        notes=original.notes
    )
    db.session.add(new_bill); db.session.flush()
    subtotal = 0; gst_total = 0
    for item in original.items:
        p = Product.query.get(item.product_id)
        if p:
            item_sub = item.price * item.quantity
            item_gst = item_sub * item.gst / 100
            subtotal += item_sub; gst_total += item_gst
            db.session.add(BillItem(bill_id=new_bill.bill_id, product_id=item.product_id,
                                    quantity=item.quantity, price=item.price, gst=item.gst))
            p.stock = max(0, p.stock - item.quantity)
    new_bill.subtotal = round(subtotal, 2)
    new_bill.gst_amount = round(gst_total, 2)
    new_bill.total_amount = round(subtotal + gst_total - new_bill.discount, 2)
    db.session.commit()
    _save_invoice_pdf(new_bill)
    flash(f'Bill duplicated as #{new_bill.bill_id}.', 'success')
    return redirect(url_for('invoice', bill_id=new_bill.bill_id))

# ─── Payment Status Update ────────────────────────────────────────────────────

@app.route('/bills/<int:bill_id>/payment-status', methods=['POST'])
@login_required
def update_payment_status(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    bill.payment_status = request.form.get('payment_status', 'paid')
    db.session.commit()
    flash('Payment status updated.', 'success')
    return redirect(url_for('bills'))

# ─── Email Invoice ────────────────────────────────────────────────────────────

@app.route('/invoice/<int:bill_id>/email', methods=['POST'])
@login_required
def email_invoice(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    customer_email = bill.customer.email
    if not customer_email:
        flash('Customer has no email address.', 'danger')
        return redirect(url_for('invoice', bill_id=bill_id))
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        host = os.environ.get('SMTP_HOST', ''); port = int(os.environ.get('SMTP_PORT', 587))
        user = os.environ.get('SMTP_USER', ''); pwd = os.environ.get('SMTP_PASS', '')
        biz = Business.query.first()
        biz_name = biz.name if biz else 'BillBook'

        if not all([host, user, pwd]):
            flash('SMTP not configured in .env', 'danger')
            return redirect(url_for('invoice', bill_id=bill_id))

        path = _invoice_pdf_path(bill_id)
        if not os.path.exists(path): _save_invoice_pdf(bill)

        msg = MIMEMultipart()
        msg['Subject'] = f'Invoice #{bill_id} from {biz_name}'
        msg['From'] = f'{biz_name} <{user}>'
        msg['To'] = customer_email
        msg.attach(MIMEText(f'<p>Dear {bill.customer.name},</p><p>Please find your invoice attached.</p><p>Total: <b>Rs.{bill.total_amount:.2f}</b></p><p>Thank you!</p>', 'html'))

        with open(path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename=invoice_{bill_id}.pdf')
            msg.attach(part)

        with smtplib.SMTP(host, port) as s:
            s.ehlo(); s.starttls(); s.login(user, pwd); s.send_message(msg)

        flash(f'Invoice emailed to {customer_email}.', 'success')
    except Exception as e:
        flash(f'Email failed: {str(e)}', 'danger')
    return redirect(url_for('invoice', bill_id=bill_id))

# ─── Export Reports ───────────────────────────────────────────────────────────

@app.route('/reports/export/csv')
@login_required
def export_reports_csv():
    bills = Bill.query.order_by(Bill.date.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Bill #', 'Date', 'Customer', 'Subtotal', 'GST', 'Discount', 'Total', 'Payment Method', 'Payment Status'])
    for b in bills:
        writer.writerow([b.bill_id, b.date.strftime('%d-%m-%Y %H:%M'),
                         b.customer.name, b.subtotal, b.gst_amount,
                         b.discount, b.total_amount, b.payment_method,
                         getattr(b, 'payment_status', 'paid')])
    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=sales_report.csv'})

# ─── GST Report ───────────────────────────────────────────────────────────────

@app.route('/reports/gst')
@login_required
def gst_report():
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    try:
        start = datetime.strptime(month + '-01', '%Y-%m-%d')
        if start.month == 12:
            end = start.replace(year=start.year+1, month=1)
        else:
            end = start.replace(month=start.month+1)
    except ValueError:
        start = date.today().replace(day=1)
        end = date.today()

    bills = Bill.query.filter(Bill.date >= start, Bill.date < end).all()
    total_taxable = sum(b.subtotal for b in bills)
    total_gst = sum(b.gst_amount for b in bills)
    total_revenue = sum(b.total_amount for b in bills)

    # GST breakdown by rate
    gst_breakdown = db.session.query(
        BillItem.gst.label('rate'),
        func.sum(BillItem.price * BillItem.quantity).label('taxable'),
        func.sum(BillItem.price * BillItem.quantity * BillItem.gst / 100).label('tax')
    ).join(Bill).filter(Bill.date >= start, Bill.date < end)\
     .group_by(BillItem.gst).order_by(BillItem.gst).all()

    return render_template('gst_report.html',
        month=month, bills=bills,
        total_taxable=total_taxable, total_gst=total_gst, total_revenue=total_revenue,
        gst_breakdown=gst_breakdown)

# ─── Init ────────────────────────────────────────────────────────────────────

def create_tables():
    with app.app_context():
        db.create_all()

# Run migrations and create tables on startup
def create_tables():
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"Warning: Could not create tables: {e}")

create_tables()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
