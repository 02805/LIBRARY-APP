from flask import Flask, render_template, request, redirect, url_for, session, Response
import psycopg2
import psycopg2.extras
import csv
from io import StringIO
from datetime import date, timedelta
import os

app = Flask(__name__)
app.secret_key = 'school_library_secret_key'

# ===================================================================
# DATABASE CONNECTION
# ===================================================================
DATABASE_URL = "postgresql://postgres.uftylmfusipvipdvburd:Gasange2026@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"
# ===================================================================

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.cursor_factory = psycopg2.extras.DictCursor
    return conn

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
    
    c.execute("INSERT INTO admins (username, password) VALUES ('admin', 'admin123') ON CONFLICT (username) DO NOTHING")
    
    conn.commit()
    conn.close()

# ---------- AUTHENTICATION ----------
@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email == 'superadmin':
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM admins WHERE username='admin' AND password=%s", (password,))
            admin = c.fetchone()
            conn.close()
            if admin:
                session['school_id'] = 0
                session['school_name'] = "Super Admin"
                session['librarian_name'] = "Master Admin"
                return redirect(url_for('admin_dashboard'))
            return render_template('login.html', error='Invalid Master Password')
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM librarians WHERE email=%s AND password=%s", (email, password))
        librarian = c.fetchone()
        conn.close()
        if librarian and librarian['status'] == 'approved':
            session['school_id'] = librarian['id']
            session['school_name'] = librarian['school_name']
            session['librarian_name'] = librarian['librarian_name'] or 'Librarian'
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid Email/Password or Pending Approval')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO librarians (librarian_name, school_name, email, password) VALUES (%s, %s, %s, %s)", 
                         (request.form['librarian_name'], request.form['school_name'], request.form['email'], request.form['password']))
            conn.commit()
            return render_template('login.html', success='Account created! Wait for approval.')
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
def admin_dashboard():
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM librarians WHERE status='pending'")
    pending = c.fetchall()
    c.execute("SELECT * FROM librarians WHERE status='approved'")
    approved = c.fetchall()
    conn.close()
    return render_template('admin_dashboard.html', pending=pending, approved=approved)

@app.route('/approve_school/<int:id>')
def approve_school(id):
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE librarians SET status='approved' WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_school/<int:id>')
def delete_school(id):
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM librarians WHERE id=%s", (id,))
    c.execute("DELETE FROM books WHERE school_id=%s", (id,))
    c.execute("DELETE FROM students WHERE school_id=%s", (id,))
    c.execute("DELETE FROM teachers WHERE school_id=%s", (id,))
    c.execute("DELETE FROM loans WHERE school_id=%s", (id,))
    c.execute("DELETE FROM reservations WHERE school_id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

# ---------- DASHBOARD ----------
@app.route('/dashboard')
def dashboard():
    if 'school_id' not in session: return redirect(url_for('login'))
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
        c.execute("SELECT COUNT(*) FROM loans WHERE school_id=%s AND status='issued' AND due_date < %s", (sid, today_str))
        overdue_count = c.fetchone()[0]
    conn.close()
    return render_template('dashboard.html', books=book_count, students=student_count, teachers=teacher_count, loans=loan_count, overdue=overdue_count)

# ---------- BOOKS ----------
@app.route('/books')
def books():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()
    
    if sid == 0:
        if search_query: c.execute("SELECT COUNT(*) FROM books WHERE title ILIKE %s OR author ILIKE %s", ('%' + search_query + '%', '%' + search_query + '%'))
        else: c.execute("SELECT COUNT(*) FROM books")
    else:
        if search_query: c.execute("SELECT COUNT(*) FROM books WHERE school_id=%s AND (title ILIKE %s OR author ILIKE %s)", (sid, '%' + search_query + '%', '%' + search_query + '%'))
        else: c.execute("SELECT COUNT(*) FROM books WHERE school_id=%s", (sid,))
    total_books = c.fetchone()[0]
    total_pages = (total_books + per_page - 1) // per_page

    if sid == 0:
        if search_query: c.execute("SELECT * FROM books WHERE title ILIKE %s OR author ILIKE %s ORDER BY id DESC LIMIT %s OFFSET %s", ('%' + search_query + '%', '%' + search_query + '%', per_page, offset))
        else: c.execute("SELECT * FROM books ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
    else:
        if search_query: c.execute("SELECT * FROM books WHERE school_id=%s AND (title ILIKE %s OR author ILIKE %s) ORDER BY id DESC LIMIT %s OFFSET %s", (sid, '%' + search_query + '%', '%' + search_query + '%', per_page, offset))
        else: c.execute("SELECT * FROM books WHERE school_id=%s ORDER BY id DESC LIMIT %s OFFSET %s", (sid, per_page, offset))
    all_books = c.fetchall()
    conn.close()
    return render_template('books.html', books=all_books, search_query=search_query, page=page, total_pages=total_pages)

@app.route('/add_book', methods=['POST'])
def add_book():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    title = request.form['title']
    author = request.form['author']
    isbn = request.form['isbn']
    quantity = int(request.form['quantity'])
    prefix = title[:2].upper()
    conn = get_db()
    c = conn.cursor()
    for i in range(1, quantity + 1):
        c.execute("INSERT INTO books (school_id, title, author, isbn, quantity, book_code, condition) VALUES (%s, %s, %s, %s, 1, %s, 'Good')",
                  (sid, title, author, isbn, f"{prefix} {i:02d}"))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))

@app.route('/edit_book/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        c.execute("UPDATE books SET title=%s, author=%s, isbn=%s, quantity=%s, book_code=%s, condition=%s WHERE id=%s",
                     (request.form['title'], request.form['author'], request.form['isbn'], request.form['quantity'], request.form.get('book_code', ''), request.form.get('condition', ''), id))
        conn.commit()
        conn.close()
        return redirect(url_for('books'))
    c.execute("SELECT * FROM books WHERE id=%s", (id,))
    book = c.fetchone()
    conn.close()
    return render_template('edit_book.html', book=book)

@app.route('/delete_book/<int:id>')
def delete_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM books WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))

@app.route('/delete_all_books')
def delete_all_books():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0: c.execute("DELETE FROM books")
    else: c.execute("DELETE FROM books WHERE school_id=%s", (sid,))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))

@app.route('/export_books')
def export_books():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0: c.execute("SELECT * FROM books")
    else: c.execute("SELECT * FROM books WHERE school_id=%s", (sid,))
    books = c.fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['NO', 'Book Title', 'Book Code', 'Author', 'Condition'])
    for index, book in enumerate(books, start=1):
        cw.writerow([index, book['title'], book['book_code'] or '', book['author'], book['condition'] or 'Good'])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=library_books.csv"})

# ---------- INVENTORY REPORT ----------
@app.route('/inventory')
def inventory():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    
    if sid == 0:
        c.execute("SELECT category, book_type, quantity FROM books WHERE category IS NOT NULL AND category != ''")
    else:
        c.execute("SELECT category, book_type, quantity FROM books WHERE school_id=%s AND category IS NOT NULL AND category != ''", (sid,))
    books = c.fetchall()
    conn.close()
    
    grid_data = {}
    total_sb = 0
    total_tg = 0
    
    for b in books:
        cat = b['category'].strip().title()
        btype = b['book_type'].strip().upper() if b['book_type'] else 'SB'
        qty = b['quantity']
        
        if cat not in grid_data:
            grid_data[cat] = {'SB': 0, 'TG': 0}
            
        if 'TG' in btype:
            grid_data[cat]['TG'] += qty
            total_tg += qty
        else:
            grid_data[cat]['SB'] += qty
            total_sb += qty

    return render_template('inventory.html', grid_data=grid_data, total_sb=total_sb, total_tg=total_tg)

@app.route('/export_inventory')
def export_inventory():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT category, book_type, quantity FROM books WHERE category IS NOT NULL AND category != ''")
    else:
        c.execute("SELECT category, book_type, quantity FROM books WHERE school_id=%s AND category IS NOT NULL AND category != ''", (sid,))
    books = c.fetchall()
    conn.close()
    
    grid_data = {}
    total_sb = 0
    total_tg = 0
    for b in books:
        cat = b['category'].strip().title()
        btype = b['book_type'].strip().upper() if b['book_type'] else 'SB'
        qty = b['quantity']
        if cat not in grid_data:
            grid_data[cat] = {'SB': 0, 'TG': 0}
        if 'TG' in btype:
            grid_data[cat]['TG'] += qty
            total_tg += qty
        else:
            grid_data[cat]['SB'] += qty
            total_sb += qty

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Subject / Category', 'Student Books (SB)', 'Teacher Guides (TG)', 'Total Copies'])
    
    for cat, counts in sorted(grid_data.items()):
        cw.writerow([cat, counts['SB'], counts['TG'], counts['SB'] + counts['TG']])
    
    cw.writerow(['GRAND TOTAL', total_sb, total_tg, total_sb + total_tg])
        
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=inventory_report.csv"})

# ---------- STUDENTS (Class List) ----------
@app.route('/students')
def students():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0: c.execute("SELECT class_name, COUNT(*) as count FROM students GROUP BY class_name ORDER BY class_name")
    else: c.execute("SELECT class_name, COUNT(*) as count FROM students WHERE school_id=%s GROUP BY class_name ORDER BY class_name", (sid,))
    classes = c.fetchall()
    conn.close()
    return render_template('students.html', classes=classes)

# ---------- SPECIFIC CLASS PAGE ----------
@app.route('/students/<class_name>')
def class_students(class_name):
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    page = request.args.get('page', 1, type=int)
    per_page = 15
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()
    
    if sid == 0: c.execute("SELECT COUNT(*) FROM students WHERE class_name=%s", (class_name,))
    else: c.execute("SELECT COUNT(*) FROM students WHERE school_id=%s AND class_name=%s", (sid, class_name))
    total_students = c.fetchone()[0]
    total_pages = (total_students + per_page - 1) // per_page

    if sid == 0: c.execute("SELECT * FROM students WHERE class_name=%s ORDER BY name LIMIT %s OFFSET %s", (class_name, per_page, offset))
    else: c.execute("SELECT * FROM students WHERE school_id=%s AND class_name=%s ORDER BY name LIMIT %s OFFSET %s", (sid, class_name, per_page, offset))
    students_list = c.fetchall()
    
    if sid == 0:
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status, books.title, books.book_code, students.name as student_name
            FROM loans JOIN books ON loans.book_id = books.id JOIN students ON loans.student_id = students.id
            WHERE students.class_name=%s ORDER BY loans.id DESC''', (class_name,))
    else:
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.status, books.title, books.book_code, students.name as student_name
            FROM loans JOIN books ON loans.book_id = books.id JOIN students ON loans.student_id = students.id
            WHERE loans.school_id=%s AND students.class_name=%s ORDER BY loans.id DESC''', (sid, class_name))
    class_loans = c.fetchall()
    
    conn.close()
    return render_template('class_students.html', class_name=class_name, students=students_list, class_loans=class_loans, page=page, total_pages=total_pages)

@app.route('/add_student/<class_name>', methods=['POST'])
def add_student_class(class_name):
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
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
def edit_student(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        c.execute("UPDATE students SET name=%s, class_name=%s, roll_no=%s WHERE id=%s",
                     (request.form['name'], request.form['class_name'], request.form['roll_no'], id))
        conn.commit()
        class_name = request.form['class_name']
        conn.close()
        return redirect(url_for('class_students', class_name=class_name))
    c.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = c.fetchone()
    conn.close()
    return render_template('edit_student.html', student=student)

@app.route('/delete_student/<int:id>/<class_name>')
def delete_student(id, class_name):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM loans WHERE student_id=%s AND status='issued'", (id,))
    active_loan = c.fetchone()
    if not active_loan:
        c.execute("DELETE FROM students WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('class_students', class_name=class_name))

@app.route('/delete_all_students')
def delete_all_students():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0: c.execute("DELETE FROM students")
    else: c.execute("DELETE FROM students WHERE school_id=%s", (sid,))
    conn.commit()
    conn.close()
    return redirect(url_for('students'))

@app.route('/export_class_history/<class_name>')
def export_class_history(class_name):
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute('''SELECT students.name, students.roll_no, books.title, books.book_code, loans.issue_date, loans.due_date, loans.status 
                     FROM loans JOIN books ON loans.book_id = books.id JOIN students ON loans.student_id = students.id 
                     WHERE students.class_name=%s ORDER BY loans.id DESC''', (class_name,))
    else:
        c.execute('''SELECT students.name, students.roll_no, books.title, books.book_code, loans.issue_date, loans.due_date, loans.status 
                     FROM loans JOIN books ON loans.book_id = books.id JOIN students ON loans.student_id = students.id 
                     WHERE loans.school_id=%s AND students.class_name=%s ORDER BY loans.id DESC''', (sid, class_name))
    history = c.fetchall()
    conn.close()
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student Name', 'Roll No', 'Book Title', 'Book Code', 'Issue Date', 'Due Date', 'Status'])
    for row in history:
        cw.writerow([row['name'], row['roll_no'], row['title'], row['book_code'] or '-', row['issue_date'], row['due_date'], row['status']])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment;filename={class_name}_history.csv"})

# ---------- TEACHERS ----------
@app.route('/teachers')
def teachers():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    search_query = request.args.get('search', '')
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        if search_query: c.execute("SELECT * FROM teachers WHERE name ILIKE %s OR department ILIKE %s", ('%' + search_query + '%', '%' + search_query + '%'))
        else: c.execute("SELECT * FROM teachers")
    else:
        if search_query: c.execute("SELECT * FROM teachers WHERE school_id=%s AND (name ILIKE %s OR department ILIKE %s)", (sid, '%' + search_query + '%', '%' + search_query + '%'))
        else: c.execute("SELECT * FROM teachers WHERE school_id=%s", (sid,))
    all_teachers = c.fetchall()
    conn.close()
    return render_template('teachers.html', teachers=all_teachers, search_query=search_query)

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO teachers (school_id, name, department) VALUES (%s, %s, %s)", (sid, request.form['name'], request.form['department']))
    conn.commit()
    conn.close()
    return redirect(url_for('teachers'))

@app.route('/delete_teacher/<int:id>')
def delete_teacher(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM loans WHERE teacher_id=%s AND status='issued'", (id,))
    if not c.fetchone():
        c.execute("DELETE FROM teachers WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('teachers'))

# ---------- LOANS ----------
@app.route('/loans')
def loans():
    if 'school_id' not in session: return redirect(url_for('login'))
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
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date, loans.status, books.title, books.book_code, students.name as student_name, students.class_name, teachers.name as teacher_name, teachers.department
            FROM loans JOIN books ON loans.book_id = books.id LEFT JOIN students ON loans.student_id = students.id LEFT JOIN teachers ON loans.teacher_id = teachers.id ORDER BY loans.id DESC''')
    else:
        c.execute("SELECT id, title, book_code FROM books WHERE school_id=%s AND quantity > 0", (sid,))
        all_books = c.fetchall()
        c.execute("SELECT * FROM students WHERE school_id=%s ORDER BY name", (sid,))
        all_students = c.fetchall()
        c.execute("SELECT * FROM teachers WHERE school_id=%s ORDER BY name", (sid,))
        all_teachers = c.fetchall()
        c.execute('''SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date, loans.status, books.title, books.book_code, students.name as student_name, students.class_name, teachers.name as teacher_name, teachers.department
            FROM loans JOIN books ON loans.book_id = books.id LEFT JOIN students ON loans.student_id = students.id LEFT JOIN teachers ON loans.teacher_id = teachers.id WHERE loans.school_id = %s ORDER BY loans.id DESC''', (sid,))
    all_loans = c.fetchall()
    
    processed_active = []
    processed_history = []
    today = date.today()
    
    for loan in all_loans:
        loan_dict = dict(loan)
        fine = 0
        days_late = 0
        if loan_dict['status'] == 'issued':
            due_date = date.fromisoformat(loan_dict['due_date'])
            if today > due_date:
                days_late = (today - due_date).days
                fine = days_late * 100
            loan_dict['fine'] = fine
            loan_dict['days_late'] = days_late
            processed_active.append(loan_dict)
        else:
            if loan_dict['return_date']:
                due_date = date.fromisoformat(loan_dict['due_date'])
                return_date = date.fromisoformat(loan_dict['return_date'])
                if return_date > due_date:
                    days_late = (return_date - due_date).days
                    fine = days_late * 100
            loan_dict['fine'] = fine
            loan_dict['days_late'] = days_late
            processed_history.append(loan_dict)
            
    conn.close()
    return render_template('loans.html', books=all_books, students=all_students, teachers=all_teachers, active_loans=processed_active, history_loans=processed_history)

@app.route('/issue_book', methods=['POST'])
def issue_book():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    book_id = request.form['book_id']
    borrower_type = request.form['borrower_type']
    today = date.today()
    due = today + timedelta(days=14)
    conn = get_db()
    c = conn.cursor()
    if borrower_type == 'student':
        c.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) VALUES (%s, %s, %s, %s, %s, 'issued')",
                     (sid, book_id, request.form.get('student_id'), today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
    else:
        c.execute("INSERT INTO loans (school_id, book_id, teacher_id, issue_date, due_date, status) VALUES (%s, %s, %s, %s, %s, 'issued')",
                     (sid, book_id, request.form.get('teacher_id'), today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
    c.execute("UPDATE books SET quantity = quantity - 1 WHERE id = %s", (book_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('loans'))

@app.route('/return_book/<int:id>')
def return_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT book_id FROM loans WHERE id=%s", (id,))
    loan = c.fetchone()
    if loan:
        book_id = loan['book_id']
        c.execute("UPDATE loans SET status='returned', return_date=%s WHERE id=%s", (date.today().strftime("%Y-%m-%d"), id))
        c.execute("SELECT id FROM reservations WHERE book_id=%s AND status='pending' ORDER BY id ASC LIMIT 1", (book_id,))
        reservation = c.fetchone()
        if reservation: c.execute("UPDATE reservations SET status='ready' WHERE id=%s", (reservation['id'],))
        c.execute("UPDATE books SET quantity = quantity + 1 WHERE id=%s", (book_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('loans'))

# ---------- RESERVATIONS ----------
@app.route('/reservations')
def reservations():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    c = conn.cursor()
    if sid == 0:
        c.execute("SELECT * FROM students")
        all_students = c.fetchall()
        c.execute("SELECT * FROM books")
        all_books = c.fetchall()
        c.execute('''SELECT reservations.id, reservations.reserve_date, reservations.status, reservations.book_id, reservations.student_id, books.title, books.book_code, students.name, students.class_name
            FROM reservations JOIN books ON reservations.book_id = books.id JOIN students ON reservations.student_id = students.id ORDER BY reservations.id DESC''')
    else:
        c.execute("SELECT * FROM students WHERE school_id=%s", (sid,))
        all_students = c.fetchall()
        c.execute("SELECT * FROM books WHERE school_id=%s", (sid,))
        all_books = c.fetchall()
        c.execute('''SELECT reservations.id, reservations.reserve_date, reservations.status, reservations.book_id, reservations.student_id, books.title, books.book_code, students.name, students.class_name
            FROM reservations JOIN books ON reservations.book_id = books.id JOIN students ON reservations.student_id = students.id WHERE reservations.school_id = %s ORDER BY reservations.id DESC''', (sid,))
    all_reservations = c.fetchall()
    conn.close()
    return render_template('reservations.html', students=all_students, books=all_books, reservations=all_reservations)

@app.route('/add_reservation', methods=['POST'])
def add_reservation():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reservations (school_id, book_id, student_id, reserve_date, status) VALUES (%s, %s, %s, %s, 'pending')",
                 (sid, request.form['book_id'], request.form['student_id'], date.today().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))

@app.route('/issue_reserved/<int:id>')
def issue_reserved(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT book_id, student_id FROM reservations WHERE id=%s", (id,))
    res = c.fetchone()
    if res:
        today = date.today()
        due = today + timedelta(days=14)
        c.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) VALUES (%s, %s, %s, %s, %s, 'issued')",
                     (sid, res['book_id'], res['student_id'], today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
        c.execute("UPDATE books SET quantity = quantity - 1 WHERE id=%s", (res        c.execute("UPDATE books SET quantity = quantity - 1 WHERE id=%s", (res['book_id'],))
        c.execute("UPDATE reservations SET status='issued' WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('reservations'))


@app.route('/cancel_reservation/<int:id>')
def cancel_reservation(id):
    if 'school_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE reservations SET status='cancelled' WHERE id=%s", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))


# ---------- APP BOOTSTRAP ----------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
