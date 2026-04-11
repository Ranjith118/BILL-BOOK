import sqlite3, os

db_path = os.path.join(os.path.dirname(__file__), 'instance', 'billbook.db')
conn = sqlite3.connect(db_path)

def add_col(table, col, col_type):
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if col not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}')
        print(f'added {table}.{col}')

# bills
add_col('bills', 'payment_status', "VARCHAR(20) DEFAULT 'paid'")
add_col('bills', 'notes', 'TEXT')

# business
add_col('business', 'terms', 'TEXT')
add_col('business', 'logo', 'VARCHAR(200)')
add_col('business', 'signature', 'VARCHAR(200)')
add_col('business', 'logo_size', "VARCHAR(10) DEFAULT 'medium'")
add_col('business', 'logo_data', 'BLOB')
add_col('business', 'logo_mimetype', 'VARCHAR(50)')
add_col('business', 'signature_data', 'BLOB')
add_col('business', 'signature_mimetype', 'VARCHAR(50)')
add_col('business', 'user_id', 'INTEGER')

# users
add_col('users', 'password_hash', 'VARCHAR(200)')

# customers
add_col('customers', 'user_id', 'INTEGER')

# products
add_col('products', 'user_id', 'INTEGER')

conn.commit()
conn.close()
print('Migration complete')
