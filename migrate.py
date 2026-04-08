import sqlite3, os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'billbook.db')
conn = sqlite3.connect(db_path)

# bills table
bill_cols = [r[1] for r in conn.execute('PRAGMA table_info(bills)').fetchall()]
if 'payment_status' not in bill_cols:
    conn.execute("ALTER TABLE bills ADD COLUMN payment_status VARCHAR(20) DEFAULT 'paid'")
    print('added payment_status')
if 'notes' not in bill_cols:
    conn.execute("ALTER TABLE bills ADD COLUMN notes TEXT")
    print('added notes')

# business table
biz_cols = [r[1] for r in conn.execute('PRAGMA table_info(business)').fetchall()]
if 'terms' not in biz_cols:
    conn.execute("ALTER TABLE business ADD COLUMN terms TEXT")
    print('added terms')
if 'logo' not in biz_cols:
    conn.execute("ALTER TABLE business ADD COLUMN logo VARCHAR(200)")
    print('added logo')
if 'signature' not in biz_cols:
    conn.execute("ALTER TABLE business ADD COLUMN signature VARCHAR(200)")
    print('added signature')
if 'logo_size' not in biz_cols:
    conn.execute("ALTER TABLE business ADD COLUMN logo_size VARCHAR(10) DEFAULT 'medium'")
    print('added logo_size')

# users table
user_cols = [r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()]
if 'password_hash' not in user_cols:
    conn.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(200)")
    print('added password_hash')

conn.commit()
conn.close()
print('Migration complete')
