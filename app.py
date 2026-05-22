from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = 'baandee_secret_key'
DB_NAME = 'Rental_management.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # ตารางที่ 1: Rooms
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Rooms (
            room_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            room_number    TEXT NOT NULL,
            floor          TEXT DEFAULT '',
            status         TEXT DEFAULT 'Available',
            condo_name     TEXT DEFAULT 'Baandee Condo',
            room_size      REAL DEFAULT 0.0,
            room_image_url TEXT DEFAULT '',
            monthly_rent   REAL
        )
    ''')

    # ตารางที่ 2: Tenants (แยกออกมาจาก Rooms)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Tenants (
            tenant_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name   TEXT NOT NULL DEFAULT '',
            last_name    TEXT NOT NULL DEFAULT '',
            phone        TEXT DEFAULT '',
            email        TEXT DEFAULT '',
            id_card      TEXT DEFAULT '',
            created_at   TEXT DEFAULT (date('now'))
        )
    ''')

    # ตารางที่ 3: Contracts (สัญญาเช่า - แยกออกมาเป็นตารางเองอย่างสมบูรณ์)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Contracts (
            contract_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id      INTEGER NOT NULL,
            tenant_id    INTEGER NOT NULL,
            start_date   TEXT NOT NULL,
            end_date     TEXT NOT NULL,
            monthly_rent REAL NOT NULL,
            deposit      REAL DEFAULT 0.0,
            status       TEXT DEFAULT 'Active',
            note         TEXT DEFAULT '',
            created_at   TEXT DEFAULT (date('now')),
            FOREIGN KEY (room_id)   REFERENCES Rooms (room_id),
            FOREIGN KEY (tenant_id) REFERENCES Tenants (tenant_id)
        )
    ''')

    # ตารางที่ 4: Payments
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Payments (
            payment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id        INTEGER,
            contract_id    INTEGER,
            amount         REAL,
            payment_date   TEXT,
            payment_status TEXT,
            note           TEXT DEFAULT '',
            FOREIGN KEY (room_id)     REFERENCES Rooms (room_id),
            FOREIGN KEY (contract_id) REFERENCES Contracts (contract_id)
        )
    ''')

    # ตารางที่ 5: MaintenanceRequests
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS MaintenanceRequests (
            request_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id      INTEGER,
            description  TEXT,
            request_date TEXT,
            status       TEXT,
            FOREIGN KEY (room_id) REFERENCES Rooms (room_id)
        )
    ''')

    # Migration: ดึงข้อมูลจากตาราง Rooms เก่า (ที่มี tenant columns) มาสร้าง Tenants + Contracts
    try:
        old_cols = [row[1] for row in cursor.execute("PRAGMA table_info(Rooms)").fetchall()]
        if 'tenant_name' in old_cols:
            old_rooms = cursor.execute(
                "SELECT room_id, tenant_name, first_name, last_name, phone, tenant_phone, email, tenant_email, "
                "monthly_rent, start_date, end_date, status FROM Rooms WHERE tenant_name != '' OR first_name != ''"
            ).fetchall()
            for r in old_rooms:
                fn = r['first_name'] or (r['tenant_name'].split(' ', 1)[0] if r['tenant_name'] else '')
                ln = r['last_name']  or (r['tenant_name'].split(' ', 1)[1] if r['tenant_name'] and ' ' in r['tenant_name'] else '')
                ph = r['phone'] or r['tenant_phone'] or ''
                em = r['email'] or r['tenant_email'] or ''
                if fn:
                    existing = cursor.execute(
                        "SELECT tenant_id FROM Tenants WHERE first_name=? AND last_name=? AND phone=?",
                        (fn, ln, ph)
                    ).fetchone()
                    if not existing:
                        cursor.execute(
                            "INSERT INTO Tenants (first_name, last_name, phone, email) VALUES (?, ?, ?, ?)",
                            (fn, ln, ph, em)
                        )
                        tenant_id = cursor.lastrowid
                    else:
                        tenant_id = existing['tenant_id']

                    if r['start_date']:
                        existing_contract = cursor.execute(
                            "SELECT contract_id FROM Contracts WHERE room_id=? AND tenant_id=?",
                            (r['room_id'], tenant_id)
                        ).fetchone()
                        if not existing_contract:
                            cursor.execute(
                                "INSERT INTO Contracts (room_id, tenant_id, start_date, end_date, monthly_rent, status) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (r['room_id'], tenant_id, r['start_date'], r['end_date'],
                                 r['monthly_rent'] or 0, r['status'] or 'Active')
                            )

            # ลบ columns เก่าออกจาก Rooms โดยสร้างตารางใหม่
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Rooms_new (
                    room_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number    TEXT NOT NULL,
                    floor          TEXT DEFAULT '',
                    status         TEXT DEFAULT 'Available',
                    condo_name     TEXT DEFAULT 'Baandee Condo',
                    room_size      REAL DEFAULT 0.0,
                    room_image_url TEXT DEFAULT '',
                    monthly_rent   REAL
                )
            ''')
            cursor.execute('''
                INSERT OR IGNORE INTO Rooms_new (room_id, room_number, floor, status, condo_name, room_size, room_image_url, monthly_rent)
                SELECT room_id, room_number, floor, status, condo_name, room_size,
                       COALESCE(room_image_url,''), monthly_rent
                FROM Rooms
            ''')
            cursor.execute("DROP TABLE Rooms")
            cursor.execute("ALTER TABLE Rooms_new RENAME TO Rooms")
    except Exception as e:
        print(f"Migration note: {e}")

    conn.commit()
    conn.close()

init_db()

# ─── Helper ────────────────────────────────────────────────────────────────────

def get_active_contract(conn, room_id):
    return conn.execute(
        '''SELECT c.contract_id, c.room_id, c.tenant_id,
                  c.start_date, c.end_date,
                  CAST(c.monthly_rent AS REAL) AS monthly_rent,
                  CAST(c.deposit AS REAL) AS deposit,
                  c.status, c.note,
                  t.first_name, t.last_name, t.phone, t.email
           FROM Contracts c JOIN Tenants t ON c.tenant_id = t.tenant_id
           WHERE c.room_id = ? AND c.status = 'Active'
           ORDER BY c.contract_id DESC LIMIT 1''',
        (room_id,)
    ).fetchone()

# ─── Index ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db_connection()
    # 1. ดึงข้อมูลห้องพักทั้งหมดออกมาก่อน
    rooms = conn.execute('SELECT * FROM Rooms ORDER BY room_id DESC').fetchall()
    
    rentals = []
    for room in rooms:
        # 2. ค้นหาสัญญาที่เปิดใช้งาน (Active) ของแต่ละห้อง
        contract = conn.execute(
            '''SELECT c.contract_id, c.room_id, c.tenant_id,
                      c.start_date, c.end_date,
                      CAST(c.monthly_rent AS REAL) AS monthly_rent,
                      CAST(c.deposit AS REAL) AS deposit,
                      c.status, c.note,
                      t.first_name, t.last_name, t.phone, t.email
               FROM Contracts c
               JOIN Tenants t ON c.tenant_id = t.tenant_id
               WHERE c.room_id = ? AND c.status = 'Active'
               LIMIT 1''', (room['room_id'],)
        ).fetchone()
        
        # 3. แพ็ครวมข้อมูลให้อยู่ในโครงสร้างเดิมที่ index.html คุ้นเคย
        rentals.append({
            'room': room,
            'contract': contract
        })
        
    conn.close()
    # ส่งตัวแปร rentals กลับไปในรูปแบบเดิม ข้อมูลสัญญาจะไม่หลุดไปหน้าแรก และระบบไม่แครชแน่นอน
    return render_template('index.html', rentals=rentals)

# ─── Add Rental ─────────────────────────────────────────────────────────────────

@app.route('/add', methods=['GET', 'POST'])
def add_rental():
    if request.method == 'POST':
        # Rooms info
        room_number    = request.form['room_number']
        condo_name     = request.form['condo_name']
        floor          = request.form.get('floor', '')
        room_size      = request.form['room_size']
        room_image_url = request.form.get('room_image', '')

        # Tenant info
        first_name   = request.form.get('first_name', '')
        last_name    = request.form.get('last_name', '')
        phone        = request.form['tenant_phone']
        email        = request.form.get('tenant_email', '')

        # Contract info
        monthly_rent = request.form['monthly_rent']
        deposit      = request.form.get('deposit', 0)
        start_date   = request.form['start_date']
        end_date     = request.form['end_date']

        conn = get_db_connection()

        # Insert Room
        conn.execute('''
            INSERT INTO Rooms (room_number, condo_name, floor, room_size, room_image_url, monthly_rent, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Occupied')
        ''', (room_number, condo_name, floor, room_size, room_image_url, monthly_rent))
        room_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert Tenant
        conn.execute('''
            INSERT INTO Tenants (first_name, last_name, phone, email)
            VALUES (?, ?, ?, ?)
        ''', (first_name, last_name, phone, email))
        tenant_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Insert Contract
        conn.execute('''
            INSERT INTO Contracts (room_id, tenant_id, start_date, end_date, monthly_rent, deposit, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Active')
        ''', (room_id, tenant_id, start_date, end_date, monthly_rent, deposit))

        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    return render_template('add_rental.html')

# ─── Edit Rental ────────────────────────────────────────────────────────────────

@app.route('/edit/<int:room_id>', methods=['GET', 'POST'])
def edit_rental(room_id):
    conn = get_db_connection()
    room     = conn.execute('SELECT * FROM Rooms WHERE room_id = ?', (room_id,)).fetchone()
    contract = get_active_contract(conn, room_id)

    if request.method == 'POST':
        new_status = request.form.get('status', 'Available')
        
        # 1. อัปเดตข้อมูลตัวห้องพักก่อน
        conn.execute('''
            UPDATE Rooms SET room_number=?, condo_name=?, floor=?, room_size=?,
            room_image_url=?, monthly_rent=?, status=?
            WHERE room_id=?
        ''', (
            request.form['room_number'],
            request.form.get('condo_name', ''),
            request.form.get('floor', ''),
            request.form.get('room_size', ''),
            request.form.get('room_image', ''),
            request.form.get('monthly_rent', ''),
            new_status,
            room_id
        ))

        # ดึงค่าข้อมูลผู้เช่าจากฟอร์ม
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name', '').strip()
        phone      = request.form.get('phone', '')
        email      = request.form.get('tenant_email', '')
        start_date = request.form.get('start_date', '')
        end_date   = request.form.get('end_date', '')
        rent_rate       = request.form.get('monthly_rent', 0)
        security_deposit = request.form.get('security_deposit', 0)

        # 2. จัดการข้อมูลผู้เช่าและสัญญาเช่า
        if first_name: # มีการกรอกชื่อผู้เช่าเข้ามา
            if contract:
                # เคสที่ 1: มีสัญญาเดิมอยู่แล้ว ให้ทำการอัปเดตข้อมูลชุดเดิม
                conn.execute('''
                    UPDATE Tenants SET first_name=?, last_name=?, phone=?, email=?
                    WHERE tenant_id=?
                ''', (first_name, last_name, phone, email, contract['tenant_id']))
                
                conn.execute('''
                    UPDATE Contracts SET start_date=?, end_date=?, monthly_rent=?, deposit=?
                    WHERE contract_id=?
                ''', (start_date, end_date, rent_rate, security_deposit, contract['contract_id']))
            else:
                # เคสที่ 2: ห้องนี้เคยว่างอยู่/ไม่มีสัญญามาก่อน ให้ INSERT สร้างผู้เช่าและสัญญาใหม่ขึ้นมาเลย
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO Tenants (first_name, last_name, phone, email)
                    VALUES (?, ?, ?, ?)
                ''', (first_name, last_name, phone, email))
                new_tenant_id = cursor.lastrowid

                cursor.execute('''
                    INSERT INTO Contracts (room_id, tenant_id, start_date, end_date, monthly_rent, status)
                    VALUES (?, ?, ?, ?, ?, 'Active')
                ''', (room_id, new_tenant_id, start_date, end_date, rent_rate))
                
                # บังคับปรับสถานะห้องเป็น Occupied (ไม่ว่าง) ทันทีที่มีคนเช่า
                conn.execute("UPDATE Rooms SET status='Occupied' WHERE room_id=?", (room_id,))

        conn.commit()
        conn.close()
        return redirect(url_for('view_rental', room_id=room_id))

    conn.close()
    return render_template('edit.html', rental=room, contract=contract)

# ─── View Rental ────────────────────────────────────────────────────────────────

@app.route('/view/<int:room_id>')
def view_rental(room_id):
    conn = get_db_connection()
    room     = conn.execute('SELECT * FROM Rooms WHERE room_id = ?', (room_id,)).fetchone()
    contract = get_active_contract(conn, room_id)
    payments = conn.execute(
        'SELECT * FROM Payments WHERE room_id = ? ORDER BY payment_date DESC', (room_id,)
    ).fetchall()
    maintenance = conn.execute(
        'SELECT * FROM MaintenanceRequests WHERE room_id = ? ORDER BY request_date DESC', (room_id,)
    ).fetchall()
    all_contracts = conn.execute(
        '''SELECT c.contract_id, c.room_id, c.tenant_id,
                  c.start_date, c.end_date,
                  CAST(c.monthly_rent AS REAL) AS monthly_rent,
                  CAST(c.deposit AS REAL) AS deposit,
                  c.status, c.note,
                  t.first_name, t.last_name
           FROM Contracts c
           JOIN Tenants t ON c.tenant_id = t.tenant_id
           WHERE c.room_id = ? ORDER BY c.contract_id DESC''',
        (room_id,)
    ).fetchall()
    conn.close()
    return render_template('view_rental.html', rental=room, contract=contract,
                           payments=payments, maintenance=maintenance, all_contracts=all_contracts)

# ─── Delete / Reset ─────────────────────────────────────────────────────────────

@app.route('/delete/<int:room_id>', methods=['POST'])
def delete_rental(room_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM Payments WHERE room_id = ?', (room_id,))
    conn.execute('DELETE FROM MaintenanceRequests WHERE room_id = ?', (room_id,))
    conn.execute('DELETE FROM Contracts WHERE room_id = ?', (room_id,))
    conn.execute('DELETE FROM Rooms WHERE room_id = ?', (room_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/reset/<int:room_id>', methods=['POST'])
def reset_rental(room_id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE Contracts SET status='Ended' WHERE room_id=? AND status='Active'", (room_id,)
    )
    conn.execute("UPDATE Rooms SET status='Available' WHERE room_id=?", (room_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# ─── Tenants ────────────────────────────────────────────────────────────────────

@app.route('/tenants')
def tenants():
    conn = get_db_connection()
    tenants_list = conn.execute('''
        SELECT t.tenant_id, t.first_name, t.last_name, t.phone, t.email, t.id_card, t.created_at,
               r.room_number, r.condo_name,
               c.contract_id, c.start_date, c.end_date, CAST(c.monthly_rent AS REAL) AS monthly_rent, c.status as contract_status
        FROM Tenants t
        LEFT JOIN Contracts c ON t.tenant_id = c.tenant_id AND c.status = 'Active'
        LEFT JOIN Rooms r ON c.room_id = r.room_id
        ORDER BY t.tenant_id DESC
    ''').fetchall()
    conn.close()
    return render_template('tenants.html', tenants=tenants_list)

@app.route('/tenants/delete/<int:tenant_id>', methods=['POST'])
def delete_tenant(tenant_id):
    conn = get_db_connection()
    # ปิดสัญญาก่อน แล้วค่อยลบผู้เช่า (ป้องกัน FK constraint)
    rooms_affected = conn.execute(
        "SELECT DISTINCT room_id FROM Contracts WHERE tenant_id=? AND status='Active'", (tenant_id,)
    ).fetchall()
    conn.execute("UPDATE Contracts SET status='Ended' WHERE tenant_id=?", (tenant_id,))
    for r in rooms_affected:
        # เช็คว่ายังมีสัญญา Active อื่นในห้องนั้นไหม ถ้าไม่มีให้ reset เป็น Available
        still_active = conn.execute(
            "SELECT 1 FROM Contracts WHERE room_id=? AND status='Active'", (r['room_id'],)
        ).fetchone()
        if not still_active:
            conn.execute("UPDATE Rooms SET status='Available' WHERE room_id=?", (r['room_id'],))
    conn.execute("DELETE FROM Tenants WHERE tenant_id=?", (tenant_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('tenants'))

# ─── Contracts ──────────────────────────────────────────────────────────────────

@app.route('/contracts')
def contracts():
    conn = get_db_connection()
    contracts_list = conn.execute('''
        SELECT c.contract_id, c.room_id, c.tenant_id,
               c.start_date, c.end_date,
               CAST(c.monthly_rent AS REAL) AS monthly_rent,
               CAST(c.deposit AS REAL) AS deposit,
               c.status, c.note,
               r.room_number, r.condo_name,
               t.first_name, t.last_name, t.phone
        FROM Contracts c
        JOIN Rooms r    ON c.room_id    = r.room_id
        JOIN Tenants t  ON c.tenant_id  = t.tenant_id
        ORDER BY c.contract_id DESC
    ''').fetchall()
    conn.close()
    return render_template('contracts.html', contracts=contracts_list)

@app.route('/contracts/end/<int:contract_id>', methods=['POST'])
def end_contract(contract_id):
    conn = get_db_connection()
    c = conn.execute("SELECT room_id FROM Contracts WHERE contract_id=?", (contract_id,)).fetchone()
    conn.execute("UPDATE Contracts SET status='Ended' WHERE contract_id=?", (contract_id,))
    if c:
        conn.execute("UPDATE Rooms SET status='Available' WHERE room_id=?", (c['room_id'],))
    conn.commit()
    conn.close()
    return redirect(url_for('contracts'))

# ─── Payments ───────────────────────────────────────────────────────────────────

@app.route('/payments', methods=['GET', 'POST'])
def payments():
    conn = get_db_connection()
    if request.method == 'POST':
        room_id        = request.form['room_id']
        amount         = request.form['amount']
        payment_date   = request.form['payment_date']
        payment_status = request.form['payment_status']
        note           = request.form.get('note', '')
        # หา active contract
        active = conn.execute(
            "SELECT contract_id FROM Contracts WHERE room_id=? AND status='Active' LIMIT 1", (room_id,)
        ).fetchone()
        contract_id = active['contract_id'] if active else None
        conn.execute(
            "INSERT INTO Payments (room_id, contract_id, amount, payment_date, payment_status, note) VALUES (?, ?, ?, ?, ?, ?)",
            (room_id, contract_id, amount, payment_date, payment_status, note)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('payments'))

    payments_list = conn.execute('''
        SELECT p.payment_id, p.room_id, p.contract_id,
               CAST(p.amount AS REAL) AS amount,
               p.payment_date, p.payment_status, p.note,
               r.room_number, r.condo_name
        FROM Payments p LEFT JOIN Rooms r ON p.room_id = r.room_id
        ORDER BY p.payment_date DESC
    ''').fetchall()
    rooms = conn.execute("SELECT room_id, room_number, condo_name FROM Rooms").fetchall()
    conn.close()
    return render_template('payments.html', payments=payments_list, rooms=rooms)

@app.route('/payments/delete/<int:payment_id>', methods=['POST'])
def delete_payment(payment_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM Payments WHERE payment_id=?", (payment_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('payments'))

# ─── Maintenance ─────────────────────────────────────────────────────────────────

@app.route('/maintenance', methods=['GET', 'POST'])
def maintenance():
    conn = get_db_connection()
    if request.method == 'POST':
        room_id      = request.form['room_id']
        description  = request.form['description']
        request_date = request.form['request_date']
        status       = request.form['status']
        conn.execute(
            "INSERT INTO MaintenanceRequests (room_id, description, request_date, status) VALUES (?, ?, ?, ?)",
            (room_id, description, request_date, status)
        )
        conn.commit()
        conn.close()
        return redirect(url_for('maintenance'))

    requests_list = conn.execute('''
        SELECT m.*, r.room_number, r.condo_name
        FROM MaintenanceRequests m LEFT JOIN Rooms r ON m.room_id = r.room_id
        ORDER BY m.request_date DESC
    ''').fetchall()
    rooms = conn.execute("SELECT room_id, room_number, condo_name FROM Rooms").fetchall()
    conn.close()
    return render_template('maintenance.html', requests=requests_list, rooms=rooms)

@app.route('/maintenance/update/<int:request_id>/<string:status>')
def update_maintenance(request_id, status):
    conn = get_db_connection()
    conn.execute("UPDATE MaintenanceRequests SET status = ? WHERE request_id = ?", (status, request_id))
    conn.commit()
    conn.close()
    return redirect(url_for('maintenance'))

if __name__ == '__main__':
    app.run(debug=True)
