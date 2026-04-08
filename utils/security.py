"""
Security utilities:
- AES-256 encryption for OTP codes stored in DB
- HMAC-signed session tokens
- OTP delivery via Twilio (SMS) or SMTP (email) only — no console fallback
"""
import os, re, hmac, hashlib, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ── Encryption key derived from SECRET_KEY env var ───────────────────────────
_RAW_SECRET = os.environ.get('BILLBOOK_SECRET', 'billbook-change-this-in-production-32x')

def _derive_key(secret: str) -> bytes:
    """Derive a 256-bit AES key from the app secret using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'billbook_salt_v1',
        iterations=100_000,
    )
    return kdf.derive(secret.encode())

_AES_KEY = _derive_key(_RAW_SECRET)

# ── AES-256-GCM Encrypt / Decrypt ────────────────────────────────────────────

def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded nonce+ciphertext."""
    aesgcm = AESGCM(_AES_KEY)
    nonce = os.urandom(12)                          # 96-bit nonce
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()

def decrypt(token: str) -> str:
    """Decrypt a base64-encoded nonce+ciphertext. Returns plaintext."""
    raw = base64.urlsafe_b64decode(token.encode())
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(_AES_KEY)
    return aesgcm.decrypt(nonce, ct, None).decode()

# ── HMAC integrity check for contact field ───────────────────────────────────

def sign(value: str) -> str:
    return hmac.new(_AES_KEY, value.encode(), hashlib.sha256).hexdigest()

def verify_sign(value: str, signature: str) -> bool:
    expected = hmac.new(_AES_KEY, value.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# ── Contact type detection ────────────────────────────────────────────────────

def is_email(contact: str) -> bool:
    return bool(re.match(r'^[\w\.\+\-]+@[\w\.-]+\.\w{2,}$', contact.strip()))

def deliver_otp(email: str, code: str) -> bool:
    """Send OTP via SMTP email only."""
    return send_otp_email(email, code)

# ── OTP Delivery ─────────────────────────────────────────────────────────────

def send_otp_sms(phone: str, code: str) -> bool:
    """Send OTP via Twilio SMS. Raises if credentials not set."""
    sid   = os.environ.get('TWILIO_SID', '').strip()
    token = os.environ.get('TWILIO_AUTH_TOKEN', '').strip()
    from_ = os.environ.get('TWILIO_FROM', '').strip()

    if not all([sid, token, from_]):
        raise EnvironmentError(
            "Twilio credentials not configured. "
            "Set TWILIO_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM environment variables."
        )

    from twilio.rest import Client
    normalized = phone if phone.startswith('+') else f'+91{phone}'
    Client(sid, token).messages.create(
        body=f"Your BillBook OTP is {code}. Valid for 10 minutes. Do not share this with anyone.",
        from_=from_,
        to=normalized
    )
    return True

def send_otp_email(email: str, code: str) -> bool:
    """Send OTP via SMTP email. Raises if credentials not set."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    host = os.environ.get('SMTP_HOST', '').strip()
    port = int(os.environ.get('SMTP_PORT', 587))
    user = os.environ.get('SMTP_USER', '').strip()
    pwd  = os.environ.get('SMTP_PASS', '').strip()

    if not all([host, user, pwd]):
        raise EnvironmentError(
            "SMTP credentials not configured. "
            "Set SMTP_HOST, SMTP_USER, SMTP_PASS environment variables."
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:32px;
                border:1px solid #eee;border-radius:12px;">
      <h2 style="color:#e94560;margin-bottom:4px;">BillBook</h2>
      <p style="color:#555;">Your one-time login code is:</p>
      <div style="font-size:42px;font-weight:bold;letter-spacing:12px;
                  color:#1a1a2e;padding:16px 0;">{code}</div>
      <p style="color:#888;font-size:13px;">
        This code expires in <strong>10 minutes</strong>.<br/>
        Never share this code with anyone.
      </p>
      <hr style="border:none;border-top:1px solid #eee;"/>
      <p style="color:#aaa;font-size:11px;">
        If you didn't request this, ignore this email.
      </p>
    </div>
    """

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'BillBook OTP: {code}'
    msg['From']    = f'BillBook <{user}>'
    msg['To']      = email
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(host, port) as s:
        s.ehlo()
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True

def deliver_otp(email: str, code: str) -> bool:
    """Send OTP via SMTP email only."""
    return send_otp_email(email, code)
