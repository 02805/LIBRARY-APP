from flask import Flask, render_template, request, redirect, url_for, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras
import csv
from io import StringIO
from datetime import date, timedelta
from functools import wraps
import os

app = Flask(__name__)
# Use an environment variable in production: os.environ["SECRET_KEY"]
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# ===================================================================
# DATABASE CONNECTION  (set DATABASE_URL in your environment)
# ===================================================================
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.uftylmfusipvipdvburd:REPLACE_ME@aws-1-eu-central-1.pooler.supabase.com:5432/postgres",
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.cursor_factory = psycopg2.extras.DictCursor
    return conn


# ---------- AUTH HELPERS ----------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'school_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'school_id' not in session or session['school_id'] != 0:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def current_sid():
    """Return the school_id for the logged-in librarian, or 999 for super admin."""
    sid = session.get('school_id', 0)
    return sid if sid != 0 else 999


# ---------- DATABASE SETUP ----------
def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS librarians (
        id SERIAL PRIMARY KEY,
        librarian_name TEXT,
        school_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        status TEXT DEFAULT 'pending'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS books (
        id SERIAL PRIMARY KEY,
        school_id INTEGER,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        isbn TEXT,
        quantity INTEGER DEFAULT 1,
        book_code TEXT,
        condition TEXT,
        category TEXT,
        book_type TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id SERIAL PRIMARY KEY,
        school_id INTEGER,
        name TEXT NOT NULL,
        class_name TEXT,
        roll_no TEXT UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id SERIAL PRIMARY KEY,
        school_id INTEGER,
        name TEXT NOT NULL,
        department TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id SERIAL PRIMARY KEY,
        school_id INTEGER,
        book_id INTEGER,
        student_id INTEGER,
        teacher_id INTEGER,
        issue_date TEXT,
        due_date TEXT,
        return_date TEXT,
        status TEXT DEFAULT 'issued'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reservations (
        id SERIAL PRIMARY KEY,
        school_id INTEGER,
        book_id INTEGER,
        student_id INTEGER,
        reserve_date TEXT,
        status TEXT DEFAULT 'pending'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT
    )''')

    # Seed default admin (hashed). Change this password after first login.
    c.execute("SELECT id FROM admins WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO admins (username, password) VALUES (%s, %s)",
                  ('admin', generate_password_hash('admin123')))

    conn.commit()
    conn.close()


# ---------- AUTHENTICATION ----------
@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        # Super admin login
        if email == 'superadmin':
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM admins WHERE username='admin'")
            admin = c.fetchone()
            conn.close()
            if admin and check_password_hash(admin['password'], password):
                session['school_id'] = 0
                session['school_name'] = "Super Admin"
                session['librarian_name'] = "Master Admin"
                return redirect(url_for('admin_dashboard'))
            return render_template('login.html', error='Invalid Master Password')

        # Librarian login
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM librarians WHERE email=%s", (email,))
        librarian = c.fetchone()
        conn.close()
        if librarian and check_password_hash(librarian['password'], password) \
                and librarian['status'] == 'approved':
            session['school_id'] = librarian['id']
            session['school_name'] = librarian['school_name']
            session['librarian_name'] = librarian['librarian_name'] or 'Librarian'
            return redirect(url_for('dashboard'))
        return render_template('login.html',
                               error='Invalid Email/Password or Pending Approval')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO librarians (librarian_name, school_name, email, password) "
                "VALUES (%s, %s, %s, %s)",
                (request.form['librarian_name'], request.form['school_name'],
                 request.form['email'], generate_password_hash(request.form['password']))
            )
            conn.commit()
            return render_template('login.html',
                                   success='Account created! Wait for approval.')
        except psycopg2.IntegrityError:
            conn.rollback()
            return render_template('register.html', error='Email already exists.')
        finally:
            conn.close()
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------- SUPER ADMIN ----------
@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM librarians WHERE status='pending'")
    pending = c.fetchall()
    c.execute("SELECT * FROM librarians WHERE status='approved'")
    approved = c.fetchall()
    conn.close()
    return render_template('admin_dashboard.html', pending=pending, approved=approved)


@app.route('/approve_school/<int:id>', methods=['POST'])
@admin_required
def approve_school(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE librarians SET status='approved' WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))


@app.route('/delete_school/<int:id>', methods=['POST'])
@admin_required
def delete_school(id):
    conn = get_db()
    c = conn.cursor()
    for table in ('librarians', 'books', 'students', 'teachers', 'loans', 'reservations'):
        c.execute(f"DELETE FROM {table} WHERE {'id' if table == 'librarians' else 'school_id'}=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))


# ---------- DASHBOARD ----------
@app.route('/dashboard')
@login_required
def dashboard():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT SUM(quantity) FROM books")
        book_count = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM students")
        student_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM teachers")
        teacher_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM loans WHERE status='issued'")
        loan_count = c.fetchone()[0]
        today_str = date.today().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM loans WHERE status='issued' AND due_date < %s", (today_str,))
        overdue_count = c.fetchone()[0]
    else:
        c.execute("SELECT SUM(quantity) FROM books WHERE school_id=%s", (sid,))
        book_count = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM students WHERE school_id=%s", (sid,))
        student_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM teachers WHERE school_id=%s", (sid,))
        teacher_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM loans WHERE school_id=%s AND status='issued'", (sid,))
        loan_count = c.fetchone()[0]
        today_str = date.today().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM loans WHERE school_id=%s AND status='issued' AND due_date < %s",
                  (sid, today_str))
        overdue_count = c.fetchone()[0]
    conn.close()
    return render_template('dashboard.html', books=book_count, students=student_count,
                           teachers=teacher_count, loans=loan_count, overdue=overdue_count)


# ---------- BOOKS ----------
@app.route('/books')
@login_required
def books():
    sid = session['school_id']
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()

    like = '%' + search_query + '%'
    if sid == 0:
        if search_query:
            c.execute("SELECT COUNT(*) FROM books WHERE title ILIKE %s OR author ILIKE %s", (like, like))
        else:
            c.execute("SELECT COUNT(*) FROM books")
    else:
        if search_query:
            c.execute("SELECT COUNT(*) FROM books WHERE school_id=%s AND (title ILIKE %s OR author ILIKE %s)",
                      (sid, like, like))
        else:
            c.execute("SELECT COUNT(*) FROM books WHERE school_id=%s", (sid,))
    total_books = c.fetchone()[0]
    total_pages = max(1, (total_books + per_page - 1) // per_page)

    if sid == 0:
        if search_query:
            c.execute("SELECT * FROM books WHERE title ILIKE %s OR author ILIKE %s "
                      "ORDER BY id DESC LIMIT %s OFFSET %s", (like, like, per_page, offset))
        else:
            c.execute("SELECT * FROM books ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
    else:
        if search_query:
            c.execute("SELECT * FROM books WHERE school_id=%s AND (title ILIKE %s OR author ILIKE %s) "
                      "ORDER BY id DESC LIMIT %s OFFSET %s", (sid, like, like, per_page, offset))
        else:
            c.execute("SELECT * FROM books WHERE school_id=%s ORDER BY id DESC LIMIT %s OFFSET %s",
                      (sid, per_page, offset))
    all_books = c.fetchall()
    conn.close()
    return render_template('books.html', books=all_books, search_query=search_query,
                           page=page, total_pages=total_pages)


@app.route('/add_book', methods=['POST'])
@login_required
def add_book():
    sid = current_sid()
    title = request.form['title']
    author = request.form['author']
    isbn = request.form['isbn']
    quantity = int(request.form['quantity'] or 1)
    category = request.form.get('category', '').strip()
    book_type = request.form.get('book_type', 'SB').strip().upper()
    prefix = title[:2].upper()

    conn = get_db()
    c = conn.cursor()
    for i in range(1, quantity + 1):
        c.execute(
            "INSERT INTO books (school_id, title, author, isbn, quantity, book_code, condition, category, book_type) "
            "VALUES (%s, %s, %s, %s, 1, %s, 'Good', %s, %s)",
            (sid, title, author, isbn, f"{prefix} {i:02d}", category, book_type))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))


@app.route('/edit_book/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_book(id):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        if sid == 0:
            c.execute("UPDATE books SET title=%s, author=%s, isbn=%s, quantity=%s, book_code=%s, "
                      "condition=%s, category=%s, book_type=%s WHERE id=%s",
                      (request.form['title'], request.form['author'], request.form['isbn'],
                       request.form['quantity'], request.form.get('book_code', ''),
                       request.form.get('condition', ''), request.form.get('category', ''),
                       request.form.get('book_type', ''), id))
        else:
            c.execute("UPDATE books SET title=%s, author=%s, isbn=%s, quantity=%s, book_code=%s, "
                      "condition=%s, category=%s, book_type=%s WHERE id=%s AND school_id=%s",
                      (request.form['title'], request.form['author'], request.form['isbn'],
                       request.form['quantity'], request.form.get('book_code', ''),
                       request.form.get('condition', ''), request.form.get('category', ''),
                       request.form.get('book_type', ''), id, sid))
        conn.commit()
        conn.close()
        return redirect(url_for('books'))
    if sid == 0:
        c.execute("SELECT * FROM books WHERE id=%s", (id,))
    else:
        c.execute("SELECT * FROM books WHERE id=%s AND school_id=%s", (id, sid))
    book = c.fetchone()
    conn.close()
    if not book:
        return redirect(url_for('books'))
    return render_template('edit_book.html', book=book)


@app.route('/delete_book/<int:id>', methods=['POST'])
@login_required
def delete_book(id):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("DELETE FROM books WHERE id=%s", (id,))
    else:
        c.execute("DELETE FROM books WHERE id=%s AND school_id=%s", (id, sid))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))


@app.route('/delete_all_books', methods=['POST'])
@login_required
def delete_all_books():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("DELETE FROM books")
    else:
        c.execute("DELETE FROM books WHERE school_id=%s", (sid,))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))


@app.route('/export_books')
@login_required
def export_books():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT * FROM books")
    else:
        c.execute("SELECT * FROM books WHERE school_id=%s", (sid,))
    books = c.fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['NO', 'Book Title', 'Book Code', 'Author', 'Condition'])
    for index, book in enumerate(books, start=1):
        cw.writerow([index, book['title'], book['book_code'] or '', book['author'],
                     book['condition'] or 'Good'])
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=library_books.csv"})


# ---------- INVENTORY REPORT ----------
def _build_inventory(sid):
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT category, book_type, quantity FROM books "
                  "WHERE category IS NOT NULL AND category != ''")
    else:
        c.execute("SELECT category, book_type, quantity FROM books "
                  "WHERE school_id=%s AND category IS NOT NULL AND category != ''", (sid,))
    books = c.fetchall()
    conn.close()

    grid_data, total_sb, total_tg = {}, 0, 0
    for b in books:
        cat = b['category'].strip().title()
        btype = (b['book_type'] or 'SB').strip().upper()
        qty = b['quantity']
        grid_data.setdefault(cat, {'SB': 0, 'TG': 0})
        if 'TG' in btype:
            grid_data[cat]['TG'] += qty
            total_tg += qty
        else:
            grid_data[cat]['SB'] += qty
            total_sb += qty
    return grid_data, total_sb, total_tg


@app.route('/inventory')
@login_required
def inventory():
    grid_data, total_sb, total_tg = _build_inventory(session['school_id'])
    return render_template('inventory.html', grid_data=grid_data,
                           total_sb=total_sb, total_tg=total_tg)


@app.route('/export_inventory')
@login_required
def export_inventory():
    grid_data, total_sb, total_tg = _build_inventory(session['school_id'])
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Subject / Category', 'Student Books (SB)', 'Teacher Guides (TG)', 'Total Copies'])
    for cat, counts in sorted(grid_data.items()):
        cw.writerow([cat, counts['SB'], counts['TG'], counts['SB'] + counts['TG']])
    cw.writerow(['GRAND TOTAL', total_sb, total_tg, total_sb + total_tg])
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=inventory_report.csv"})


# ---------- STUDENTS ----------
@app.route('/students')
@login_required
def students():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT class_name, COUNT(*) as count FROM students "
                  "GROUP BY class_name ORDER BY class_name")
    else:
        c.execute("SELECT class_name, COUNT(*) as count FROM students WHERE school_id=%s "
                  "GROUP BY class_name ORDER BY class_name", (sid,))
    classes = c.fetchall()
    conn.close()
    return render_template('students.html', classes=classes)


@app.route('/students/<class_name>')
@login_required
def class_students(class_name):
    sid = session['school_id']
    page = request.args.get('page', 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT COUNT(*) FROM students WHERE class_name=%s", (class_name,))
    else:
        c.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND class_name=%s",
                  (sid, class_name))
    total_students = c.fetchone()[0]
    total_pages = max(1, (total_students + per_page - 1) // per_page)

    if sid == 0:
        c.execute("SELECT * FROM students WHERE class_name=%s ORDER BY name LIMIT %s OFFSET %s",
                  (class_name, per_page, offset))
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status,
                            books.title, books.book_code, students.name as student_name
                     FROM loans JOIN books ON loans.book_id = books.id
                     JOIN students ON loans.student_id = students.id
                     WHERE students.class_name=%s ORDER BY loans.id DESC''', (class_name,))
    else:
        c.execute("SELECT * FROM students WHERE school_id=%s AND class_name=%s "
                  "ORDER BY name LIMIT %s OFFSET %s", (sid, class_name, per_page, offset))
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status,
                            books.title, books.book_code, students.name as student_name
                     FROM loans JOIN books ON loans.book_id = books.id
                     JOIN students ON loans.student_id = students.id
                     WHERE loans.school_id=%s AND students.class_name=%s
                     ORDER BY loans.id DESC''', (sid, class_name))
    students_list = c.fetchall()
    class_loans = c.fetchall() if False else None  # placeholder
    # Re-run loans query (kept separate for clarity)
    if sid == 0:
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status,
                            books.title, books.book_code, students.name as student_name
                     FROM loans JOIN books ON loans.book_id = books.id
                     JOIN students ON loans.student_id = students.id
                     WHERE students.class_name=%s ORDER BY loans.id DESC''', (class_name,))
    else:
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status,
                            books.title, books.book_code, students.name as student_name
                     FROM loans JOIN books ON loans.book_id = books.id
                     JOIN students ON loans.student_id = students.id
                     WHERE loans.school_id=%s AND students.class_name=%s
                     ORDER BY loans.id DESC''', (sid, class_name))
    class_loans = c.fetchall()
    conn.close()
    return render_template('class_students.html', class_name=class_name,
                           students=students_list, class_loans=class_loans,
                           page=page, total_pages=total_pages)


@app.route('/add_student/<class_name>', methods=['POST'])
@login_required
def add_student_class(class_name):
    sid = current_sid()
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO students (school_id, name, class_name, roll_no) VALUES (%s, %s, %s, %s)",
                  (sid, request.form['name'], class_name, request.form['roll_no']))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
    conn.close()
    return redirect(url_for('class_students', class_name=class_name))


@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_student(id):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        if sid == 0:
            c.execute("UPDATE students SET name=%s, class_name=%s, roll_no=%s WHERE id=%s",
                      (request.form['name'], request.form['class_name'],
                       request.form['roll_no'], id))
        else:
            c.execute("UPDATE students SET name=%s, class_name=%s, roll_no=%s "
                      "WHERE id=%s AND school_id=%s",
                      (request.form['name'], request.form['class_name'],
                       request.form['roll_no'], id, sid))
        conn.commit()
        class_name = request.form['class_name']
        conn.close()
        return redirect(url_for('class_students', class_name=class_name))
    if sid == 0:
        c.execute("SELECT * FROM students WHERE id=%s", (id,))
    else:
        c.execute("SELECT * FROM students WHERE id=%s AND school_id=%s", (id, sid))
    student = c.fetchone()
    conn.close()
    if not student:
        return redirect(url_for('students'))
    return render_template('edit_student.html', student=student)


@app.route('/delete_student/<int:id>/<class_name>', methods=['POST'])
@login_required
def delete_student(id, class_name):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM loans WHERE student_id=%s AND status='issued'", (id,))
    if not c.fetchone():
        if sid == 0:
            c.execute("DELETE FROM students WHERE id=%s", (id,))
        else:
            c.execute("DELETE FROM students WHERE id=%s AND school_id=%s", (id, sid))
        conn.commit()
    conn.close()
    return redirect(url_for('class_students', class_name=class_name))


@app.route('/delete_all_students', methods=['POST'])
@login_required
def delete_all_students():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("DELETE FROM students")
    else:
        c.execute("DELETE FROM students WHERE school_id=%s", (sid,))
    conn.commit()
    conn.close()
    return redirect(url_for('students'))


@app.route('/export_class_history/<class_name>')
@login_required
def export_class_history(class_name):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    base = '''SELECT students.name, students.roll_no, books.title, books.book_code,
                     loans.issue_date, loans.due_date, loans.status
              FROM loans JOIN books ON loans.book_id = books.id
              JOIN students ON loans.student_id = students.id
              WHERE {where} ORDER BY loans.id DESC'''
    if sid == 0:
        c.execute(base.format(where="students.class_name=%s"), (class_name,))
    else:
        c.execute(base.format(where="loans.school_id=%s AND students.class_name=%s"),
                  (sid, class_name))
    history = c.fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student Name', 'Roll No', 'Book Title', 'Book Code',
                 'Issue Date', 'Due Date', 'Status'])
    for row in history:
        cw.writerow([row['name'], row['roll_no'], row['title'], row['book_code'] or '-',
                     row['issue_date'], row['due_date'], row['status']])
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename={class_name}_history.csv"})


# ---------- TEACHERS ----------
@app.route('/teachers')
@login_required
def teachers():
    sid = session['school_id']
    search_query = request.args.get('search', '')
    like = '%' + search_query + '%'
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        if search_query:
            c.execute("SELECT * FROM teachers WHERE name ILIKE %s OR department ILIKE %s", (like, like))
        else:
            c.execute("SELECT * FROM teachers")
    else:
        if search_query:
            c.execute("SELECT * FROM teachers WHERE school_id=%s AND (name ILIKE %s OR department ILIKE %s)",
                      (sid, like, like))
        else:
            c.execute("SELECT * FROM teachers WHERE school_id=%s", (sid,))
    all_teachers = c.fetchall()
    conn.close()
    return render_template('teachers.html', teachers=all_teachers, search_query=search_query)


@app.route('/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    sid = current_sid()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO teachers (school_id, name, department) VALUES (%s, %s, %s)",
              (sid, request.form['name'], request.form['department']))
    conn.commit()
    conn.close()
    return redirect(url_for('teachers'))


@app.route('/delete_teacher/<int:id>', methods=['POST'])
@login_required
def delete_teacher(id):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM loans WHERE teacher_id=%s AND status='issued'", (id,))
    if not c.fetchone():
        if sid == 0:
            c.execute("DELETE FROM teachers WHERE id=%s", (id,))
        else:
            c.execute("DELETE FROM teachers WHERE id=%s AND school_id=%s", (id, sid))
        conn.commit()
    conn.close()
    return redirect(url_for('teachers'))


# ---------- LOANS ----------
@app.route('/loans')
@login_required
def loans():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT id, title, book_code FROM books WHERE quantity > 0")
        all_books = c.fetchall()
        c.execute("SELECT * FROM students ORDER BY name")
        all_students = c.fetchall()
        c.execute("SELECT * FROM teachers ORDER BY name")
        all_teachers = c.fetchall()
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date,
                            loans.status, books.title, books.book_code,
                            students.name as student_name, students.class_name,
                            teachers.name as teacher_name, teachers.department
                     FROM loans JOIN books ON loans.book_id = books.id
                     LEFT JOIN students ON loans.student_id = students.id
                     LEFT JOIN teachers ON loans.teacher_id = teachers.id
                     ORDER BY loans.id DESC''')
    else:
        c.execute("SELECT id, title, book_code FROM books WHERE school_id=%s AND quantity > 0", (sid,))
        all_books = c.fetchall()
        c.execute("SELECT * FROM students WHERE school_id=%s ORDER BY name", (sid,))
        all_students = c.fetchall()
        c.execute("SELECT * FROM teachers WHERE school_id=%s ORDER BY name", (sid,))
        all_teachers = c.fetchall()
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date,
                            loans.status, books.title, books.book_code,
                            students.name as student_name, students.class_name,
                            teachers.name as teacher_name, teachers.department
                     FROM loans JOIN books ON loans.book_id = books.id
                     LEFT JOIN students ON loans.student_id = students.id
                     LEFT JOIN teachers ON loans.teacher_id = teachers.id
                     WHERE loans.school_id = %s ORDER BY loans.id DESC''', (sid,))
    all_loans = c.fetchall()

    processed_active, processed_history = [], []
    today = date.today()
    for loan in all_loans:
        loan_dict = dict(loan)
        fine = days_late = 0
        if loan_dict['status'] == 'issued':
            due_date = date.fromisoformat(loan_dict['due_date'])
            if today > due_date:
                days_late = (today - due_date).days
                fine = days_late * 100
            loan_dict['fine'], loan_dict['days_late'] = fine, days_late
            processed_active.append(loan_dict)
        else:
            if loan_dict['return_date']:
                due_date = date.fromisoformat(loan_dict['due_date'])
                return_date = date.fromisoformat(loan_dict['return_date'])
                if return_date > due_date:
                    days_late = (return_date - due_date).days
                    fine = days_late * 100
            loan_dict['fine'], loan_dict['days_late'] = fine, days_late
            processed_history.append(loan_dict)

    conn.close()
    return render_template('loans.html', books=all_books, students=all_students,
                           teachers=all_teachers, active_loans=processed_active,
                           history_loans=processed_history)


@app.route('/issue_book', methods=['POST'])
@login_required
def issue_book():
    sid = current_sid()
    book_id = request.form['book_id']
    borrower_type = request.form['borrower_type']
    today = date.today()
    due = today + timedelta(days=14)

    conn = get_db()
    c = conn.cursor()
    # Check stock
    c.execute("SELECT quantity FROM books WHERE id=%s", (book_id,))
    row = c.fetchone()
    if not row or row['quantity'] <= 0:
        conn.close()
        return redirect(url_for('loans'))

    if borrower_type == 'student':
        c.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) "
                  "VALUES (%s, %s, %s, %s, %s, 'issued')",
                  (sid, book_id, request.form.get('student_id'),
                   today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
    else:
        c.execute("INSERT INTO loans (school_id, book_id, teacher_id, issue_date, due_date, status) "
                  "VALUES (%s, %s, %s, %s, %s, 'issued')",
                  (sid, book_id, request.form.get('teacher_id'),
                   today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
    c.execute("UPDATE books SET quantity = quantity - 1 WHERE id = %s", (book_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('loans'))


@app.route('/return_book/<int:id>', methods=['POST'])
@login_required
def return_book(id):
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT book_id FROM loans WHERE id=%s", (id,))
    else:
        c.execute("SELECT book_id FROM loans WHERE id=%s AND school_id=%s", (id, sid))
    loan = c.fetchone()
    if loan:
        book_id = loan['book_id']
        c.execute("UPDATE loans SET status='returned', return_date=%s WHERE id=%s",
                  (date.today().strftime("%Y-%m-%d"), id))
        c.execute("SELECT id FROM reservations WHERE book_id=%s AND status='pending' "
                  "ORDER BY id ASC LIMIT 1", (book_id,))
        reservation = c.fetchone()
        if reservation:
            c.execute("UPDATE reservations SET status='ready' WHERE id=%s", (reservation['id'],))
        c.execute("UPDATE books SET quantity = quantity + 1 WHERE id=%s", (book_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('loans'))


# ---------- RESERVATIONS ----------
@app.route('/reservations')
@login_required
def reservations():
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT * FROM students")
        all_students = c.fetchall()
        c.execute("SELECT * FROM books")
        all_books = c.fetchall()
        c.execute('''SELECT reservations.id, reservations.reserve_date, reservations.status,
                            reservations.book_id, reservations.student_id,
                            books.title, books.book_code, students.name, students.class_name
                     FROM reservations JOIN books ON reservations.book_id = books.id
                     JOIN students ON reservations.student_id = students.id
                     ORDER BY reservations.id DESC''')
    else:
        c.execute("SELECT * FROM students WHERE school_id=%s", (sid,))
        all_students = c.fetchall()
        c.execute("SELECT * FROM books WHERE school_id=%s", (sid,))
        all_books = c.fetchall()
        c.execute('''SELECT reservations.id, reservations.reserve_date, reservations.status,
                            reservations.book_id, reservations.student_id,
                            books.title, books.book_code, students.name, students.class_name
                     FROM reservations JOIN books ON reservations.book_id = books.id
                     JOIN students ON reservations.student_id = students.id
                     WHERE reservations.school_id = %s ORDER BY reservations.id DESC''', (sid,))
    all_reservations = c.fetchall()
    conn.close()
    return render_template('reservations.html', students=all_students,
                           books=all_books, reservations=all_reservations)


@app.route('/add_reservation', methods=['POST'])
@login_required
def add_reservation():
    sid = current_sid()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reservations (school_id, book_id, student_id, reserve_date, status) "
              "VALUES (%s, %s, %s, %s, 'pending')",
              (sid, request.form['book_id'], request.form['student_id'],
               date.today().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))


@app.route('/issue_reserved/<int:id>', methods=['POST'])
@login_required
def issue_reserved(id):
    sid = current_sid()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT book_id, student_id FROM reservations WHERE id=%s", (id,))
    res = c.fetchone()
    if res:
        # Stock check
        c.execute("SELECT quantity FROM books WHERE id=%s", (res['book_id'],))
        q = c.fetchone()
        if q and q['quantity'] > 0:
            today = date.today()
            due = today + timedelta(days=14)
            c.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) "
                      "VALUES (%s, %s, %s, %s, %s, 'issued')",
                      (sid, res['book_id'], res['student_id'],
                       today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
            c.execute("UPDATE books SET quantity = quantity - 1 WHERE id=%s", (res['book_id'],))
            c.execute("UPDATE reservations SET status='issued' WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))


@app.route('/cancel_reservation/<int:id>', methods=['POST'])
@login_required
def cancel_reservation(id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE reservations SET status='cancelled' WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))


# ---------- BOOT ----------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
