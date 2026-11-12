from flask import Flask, render_template, request, redirect, url_for, session, Response
import sqlite3
import csv
from io import TextIOWrapper, StringIO
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = 'school_library_secret_key'

# ---------- DATABASE SETUP ----------
def init_db():
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS librarians (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        librarian_name TEXT,
        school_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        status TEXT DEFAULT 'pending'
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        isbn TEXT,
        quantity INTEGER DEFAULT 1,
        book_code TEXT,
        condition TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        name TEXT NOT NULL,
        class_name TEXT,
        roll_no TEXT UNIQUE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        name TEXT NOT NULL,
        department TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER,
        book_id INTEGER,
        student_id INTEGER,
        reserve_date TEXT,
        status TEXT DEFAULT 'pending'
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO admins (username, password) VALUES ('admin', 'admin123')")
    
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect('library.db')
    conn.row_factory = sqlite3.Row
    return conn

# ---------- AUTHENTICATION ----------

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        if email == 'superadmin':
            conn = get_db()
            admin = conn.execute("SELECT * FROM admins WHERE username='admin' AND password=?", (password,)).fetchone()
            conn.close()
            if admin:
                session['school_id'] = 0
                session['school_name'] = "Super Admin"
                session['librarian_name'] = "Master Admin"
                return redirect(url_for('admin_dashboard'))
            return render_template('login.html', error='Invalid Master Password')
            
        conn = get_db()
        librarian = conn.execute("SELECT * FROM librarians WHERE email=? AND password=?", (email, password)).fetchone()
        conn.close()
        
        if librarian:
            if librarian['status'] == 'approved':
                session['school_id'] = librarian['id']
                session['school_name'] = librarian['school_name']
                session['librarian_name'] = librarian['librarian_name'] or 'Librarian'
                return redirect(url_for('dashboard'))
            else:
                return render_template('login.html', error='Your account is pending approval by the Super Admin.')
        else:
            return render_template('login.html', error='Invalid Email or Password')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        librarian_name = request.form['librarian_name']
        school_name = request.form['school_name']
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db()
        try:
            conn.execute("INSERT INTO librarians (librarian_name, school_name, email, password) VALUES (?, ?, ?, ?)", 
                         (librarian_name, school_name, email, password))
            conn.commit()
            return render_template('login.html', success='Account created! Please wait for the Super Admin to approve you.')
        except sqlite3.IntegrityError:
            return render_template('register.html', error='Email already exists.')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------- SUPER ADMIN DASHBOARD ----------
@app.route('/admin_dashboard')
def admin_dashboard():
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    conn = get_db()
    pending = conn.execute("SELECT * FROM librarians WHERE status='pending'").fetchall()
    approved = conn.execute("SELECT * FROM librarians WHERE status='approved'").fetchall()
    conn.close()
    return render_template('admin_dashboard.html', pending=pending, approved=approved)

@app.route('/approve_school/<int:id>')
def approve_school(id):
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    conn = get_db()
    conn.execute("UPDATE librarians SET status='approved' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_school/<int:id>')
def delete_school(id):
    if 'school_id' not in session or session['school_id'] != 0: return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute("DELETE FROM librarians WHERE id=?", (id,))
    conn.execute("DELETE FROM books WHERE school_id=?", (id,))
    conn.execute("DELETE FROM students WHERE school_id=?", (id,))
    conn.execute("DELETE FROM teachers WHERE school_id=?", (id,))
    conn.execute("DELETE FROM loans WHERE school_id=?", (id,))
    conn.execute("DELETE FROM reservations WHERE school_id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_dashboard'))

# ---------- DASHBOARD ----------
@app.route('/dashboard')
def dashboard():
    if 'school_id' not in session: return redirect(url_for('login'))
        
    sid = session['school_id']
    conn = get_db()
    
    if sid == 0:
        book_count = conn.execute("SELECT SUM(quantity) FROM books").fetchone()[0] or 0
        student_count = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        teacher_count = conn.execute("SELECT COUNT(*) FROM teachers").fetchone()[0]
        loan_count = conn.execute("SELECT COUNT(*) FROM loans WHERE status='issued'").fetchone()[0]
        today_str = date.today().strftime("%Y-%m-%d")
        overdue_count = conn.execute("SELECT COUNT(*) FROM loans WHERE status='issued' AND due_date < ?", (today_str,)).fetchone()[0]
    else:
        book_count = conn.execute("SELECT SUM(quantity) FROM books WHERE school_id=?", (sid,)).fetchone()[0] or 0
        student_count = conn.execute("SELECT COUNT(*) FROM students WHERE school_id=?", (sid,)).fetchone()[0]
        teacher_count = conn.execute("SELECT COUNT(*) FROM teachers WHERE school_id=?", (sid,)).fetchone()[0]
        loan_count = conn.execute("SELECT COUNT(*) FROM loans WHERE school_id=? AND status='issued'", (sid,)).fetchone()[0]
        today_str = date.today().strftime("%Y-%m-%d")
        overdue_count = conn.execute("SELECT COUNT(*) FROM loans WHERE school_id=? AND status='issued' AND due_date < ?", (sid, today_str)).fetchone()[0]
    
    conn.close()
    return render_template('dashboard.html', books=book_count, students=student_count, teachers=teacher_count, loans=loan_count, overdue=overdue_count)

# ---------- BOOKS ----------
@app.route('/books')
def books():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    search_query = request.args.get('search', '')
    
    conn = get_db()
    if sid == 0:
        if search_query:
            all_books = conn.execute("SELECT * FROM books WHERE title LIKE ? OR author LIKE ?", ('%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_books = conn.execute("SELECT * FROM books").fetchall()
    else:
        if search_query:
            all_books = conn.execute("SELECT * FROM books WHERE school_id=? AND (title LIKE ? OR author LIKE ?)", (sid, '%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_books = conn.execute("SELECT * FROM books WHERE school_id=?", (sid,)).fetchall()
    conn.close()
    return render_template('books.html', books=all_books, search_query=search_query)

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
        book_code = f"{prefix} {i:02d}"
        c.execute("INSERT INTO books (school_id, title, author, isbn, quantity, book_code, condition) VALUES (?, ?, ?, ?, 1, ?, 'Good')",
                  (sid, title, author, isbn, book_code))
                  
    conn.commit()
    conn.close()
    return redirect(url_for('books'))

@app.route('/edit_book/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    
    if request.method == 'POST':
        conn.execute("UPDATE books SET title=?, author=?, isbn=?, quantity=?, book_code=?, condition=? WHERE id=?",
                     (request.form['title'], request.form['author'], request.form['isbn'], request.form['quantity'], 
                      request.form.get('book_code', ''), request.form.get('condition', ''), id))
        conn.commit()
        conn.close()
        return redirect(url_for('books'))
        
    book = conn.execute("SELECT * FROM books WHERE id=?", (id,)).fetchone()
    conn.close()
    return render_template('edit_book.html', book=book)

@app.route('/delete_book/<int:id>')
def delete_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    conn.execute("DELETE FROM books WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('books'))

@app.route('/export_books')
def export_books():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    
    if sid == 0:
        books = conn.execute("SELECT * FROM books").fetchall()
    else:
        books = conn.execute("SELECT * FROM books WHERE school_id=?", (sid,)).fetchall()
    conn.close()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['NO', 'Book Title', 'Book Code', 'Author', 'Condition'])
    for index, book in enumerate(books, start=1):
        cw.writerow([index, book['title'], book['book_code'] or '', book['author'], book['condition'] or 'Good'])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=library_books.csv"})

# ---------- STUDENTS ----------
@app.route('/students')
def students():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    search_query = request.args.get('search', '')
    
    conn = get_db()
    if sid == 0:
        if search_query:
            all_students = conn.execute("SELECT * FROM students WHERE name LIKE ? OR roll_no LIKE ?", ('%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_students = conn.execute("SELECT * FROM students").fetchall()
    else:
        if search_query:
            all_students = conn.execute("SELECT * FROM students WHERE school_id=? AND (name LIKE ? OR roll_no LIKE ?)", (sid, '%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_students = conn.execute("SELECT * FROM students WHERE school_id=?", (sid,)).fetchall()
    conn.close()
    return render_template('students.html', students=all_students, search_query=search_query)

@app.route('/add_student', methods=['POST'])
def add_student():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    try:
        conn.execute("INSERT INTO students (school_id, name, class_name, roll_no) VALUES (?, ?, ?, ?)",
                     (sid, request.form['name'], request.form['class_name'], request.form['roll_no']))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(url_for('students'))

@app.route('/delete_student/<int:id>')
def delete_student(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    active_loan = conn.execute("SELECT id FROM loans WHERE student_id=? AND status='issued'", (id,)).fetchone()
    if not active_loan:
        conn.execute("DELETE FROM students WHERE id=?", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('students'))

# ---------- TEACHERS ----------
@app.route('/teachers')
def teachers():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    search_query = request.args.get('search', '')
    
    conn = get_db()
    if sid == 0:
        if search_query:
            all_teachers = conn.execute("SELECT * FROM teachers WHERE name LIKE ? OR department LIKE ?", ('%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_teachers = conn.execute("SELECT * FROM teachers").fetchall()
    else:
        if search_query:
            all_teachers = conn.execute("SELECT * FROM teachers WHERE school_id=? AND (name LIKE ? OR department LIKE ?)", (sid, '%' + search_query + '%', '%' + search_query + '%')).fetchall()
        else:
            all_teachers = conn.execute("SELECT * FROM teachers WHERE school_id=?", (sid,)).fetchall()
    conn.close()
    return render_template('teachers.html', teachers=all_teachers, search_query=search_query)

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    conn.execute("INSERT INTO teachers (school_id, name, department) VALUES (?, ?, ?)", 
                 (sid, request.form['name'], request.form['department']))
    conn.commit()
    conn.close()
    return redirect(url_for('teachers'))

@app.route('/delete_teacher/<int:id>')
def delete_teacher(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    active_loan = conn.execute("SELECT id FROM loans WHERE teacher_id=? AND status='issued'", (id,)).fetchone()
    if not active_loan:
        conn.execute("DELETE FROM teachers WHERE id=?", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('teachers'))

# ---------- LOANS ----------
@app.route('/loans')
def loans():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    
    if sid == 0:
        all_books = conn.execute("SELECT id, title, book_code FROM books WHERE quantity > 0").fetchall()
        all_students = conn.execute("SELECT * FROM students").fetchall()
        all_teachers = conn.execute("SELECT * FROM teachers").fetchall()
        all_loans = conn.execute('''
            SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date, loans.status, 
                   books.title, books.book_code, 
                   students.name as student_name, students.class_name,
                   teachers.name as teacher_name, teachers.department
            FROM loans 
            JOIN books ON loans.book_id = books.id 
            LEFT JOIN students ON loans.student_id = students.id
            LEFT JOIN teachers ON loans.teacher_id = teachers.id
            ORDER BY loans.id DESC
        ''').fetchall()
    else:
        all_books = conn.execute("SELECT id, title, book_code FROM books WHERE school_id=? AND quantity > 0", (sid,)).fetchall()
        all_students = conn.execute("SELECT * FROM students WHERE school_id=?", (sid,)).fetchall()
        all_teachers = conn.execute("SELECT * FROM teachers WHERE school_id=?", (sid,)).fetchall()
        all_loans = conn.execute('''
            SELECT loans.id, loans.issue_date, loans.due_date, loans.return_date, loans.status, 
                   books.title, books.book_code, 
                   students.name as student_name, students.class_name,
                   teachers.name as teacher_name, teachers.department
            FROM loans 
            JOIN books ON loans.book_id = books.id 
            LEFT JOIN students ON loans.student_id = students.id
            LEFT JOIN teachers ON loans.teacher_id = teachers.id
            WHERE loans.school_id = ?
            ORDER BY loans.id DESC
        ''', (sid,)).fetchall()
        
    # Calculate fine for each loan
    processed_loans = []
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
        else:
            if loan_dict['return_date']:
                due_date = date.fromisoformat(loan_dict['due_date'])
                return_date = date.fromisoformat(loan_dict['return_date'])
                if return_date > due_date:
                    days_late = (return_date - due_date).days
                    fine = days_late * 100
                    
        loan_dict['fine'] = fine
        loan_dict['days_late'] = days_late
        processed_loans.append(loan_dict)
        
    conn.close()
    return render_template('loans.html', books=all_books, students=all_students, teachers=all_teachers, loans=processed_loans)

@app.route('/issue_book', methods=['POST'])
def issue_book():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    book_id = request.form['book_id']
    borrower_type = request.form['borrower_type']
    today = date.today()
    due = today + timedelta(days=14)
    
    conn = get_db()
    if borrower_type == 'student':
        conn.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) VALUES (?, ?, ?, ?, ?, 'issued')",
                     (sid, book_id, request.form.get('student_id'), today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
    else:
        conn.execute("INSERT INTO loans (school_id, book_id, teacher_id, issue_date, due_date, status) VALUES (?, ?, ?, ?, ?, 'issued')",
                     (sid, book_id, request.form.get('teacher_id'), today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
                     
    conn.execute("UPDATE books SET quantity = quantity - 1 WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('loans'))

@app.route('/return_book/<int:id>')
def return_book(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    loan = conn.execute("SELECT book_id FROM loans WHERE id=?", (id,)).fetchone()
    
    if loan:
        book_id = loan['book_id']
        conn.execute("UPDATE loans SET status='returned', return_date=? WHERE id=?", (date.today().strftime("%Y-%m-%d"), id))
        reservation = conn.execute("SELECT id FROM reservations WHERE book_id=? AND status='pending' ORDER BY id ASC LIMIT 1", (book_id,)).fetchone()
        if reservation:
            conn.execute("UPDATE reservations SET status='ready' WHERE id=?", (reservation['id'],))
        conn.execute("UPDATE books SET quantity = quantity + 1 WHERE id=?", (book_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('loans'))

# ---------- RESERVATIONS ----------
@app.route('/reservations')
def reservations():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    
    if sid == 0:
        all_students = conn.execute("SELECT * FROM students").fetchall()
        all_books = conn.execute("SELECT * FROM books").fetchall()
        all_reservations = conn.execute('''
            SELECT reservations.id, reservations.reserve_date, reservations.status, reservations.book_id, reservations.student_id,
                   books.title, books.book_code, students.name, students.class_name
            FROM reservations
            JOIN books ON reservations.book_id = books.id
            JOIN students ON reservations.student_id = students.id
            ORDER BY reservations.id DESC
        ''').fetchall()
    else:
        all_students = conn.execute("SELECT * FROM students WHERE school_id=?", (sid,)).fetchall()
        all_books = conn.execute("SELECT * FROM books WHERE school_id=?", (sid,)).fetchall()
        all_reservations = conn.execute('''
            SELECT reservations.id, reservations.reserve_date, reservations.status, reservations.book_id, reservations.student_id,
                   books.title, books.book_code, students.name, students.class_name
            FROM reservations
            JOIN books ON reservations.book_id = books.id
            JOIN students ON reservations.student_id = students.id
            WHERE reservations.school_id = ?
            ORDER BY reservations.id DESC
        ''', (sid,)).fetchall()
        
    conn.close()
    return render_template('reservations.html', students=all_students, books=all_books, reservations=all_reservations)

@app.route('/add_reservation', methods=['POST'])
def add_reservation():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    conn.execute("INSERT INTO reservations (school_id, book_id, student_id, reserve_date, status) VALUES (?, ?, ?, ?, 'pending')",
                 (sid, request.form['book_id'], request.form['student_id'], date.today().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))

@app.route('/issue_reserved/<int:id>')
def issue_reserved(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
    conn = get_db()
    res = conn.execute("SELECT book_id, student_id FROM reservations WHERE id=?", (id,)).fetchone()
    
    if res:
        today = date.today()
        due = today + timedelta(days=14)
        conn.execute("INSERT INTO loans (school_id, book_id, student_id, issue_date, due_date, status) VALUES (?, ?, ?, ?, ?, 'issued')",
                     (sid, res['book_id'], res['student_id'], today.strftime("%Y-%m-%d"), due.strftime("%Y-%m-%d")))
        conn.execute("UPDATE books SET quantity = quantity - 1 WHERE id=?", (res['book_id'],))
        conn.execute("DELETE FROM reservations WHERE id=?", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for('loans'))

@app.route('/cancel_reservation/<int:id>')
def cancel_reservation(id):
    if 'school_id' not in session: return redirect(url_for('login'))
    conn = get_db()
    conn.execute("DELETE FROM reservations WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('reservations'))

# ---------- BULK IMPORT ----------
@app.route('/import_data', methods=['GET', 'POST'])
def import_data():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
        
    if request.method == 'POST':
        file = request.files['file']
        import_type = request.form['import_type']
        
        if file and file.filename.endswith('.csv'):
            csv_file = TextIOWrapper(file, encoding='utf-8')
            reader = csv.reader(csv_file)
            next(reader) 
            conn = get_db()
            c = conn.cursor()
            
            if import_type == 'books':
                for row in reader:
                    if len(row) >= 4: 
                        c.execute("INSERT INTO books (school_id, title, author, isbn, quantity) VALUES (?, ?, ?, ?, ?)",
                                  (sid, row[0], row[1], row[2], row[3]))
            elif import_type == 'students':
                for row in reader:
                    if len(row) >= 3:
                        try:
                            c.execute("INSERT INTO students (school_id, name, class_name, roll_no) VALUES (?, ?, ?, ?)",
                                      (sid, row[0], row[1], row[2]))
                        except sqlite3.IntegrityError:
                            pass 
            conn.commit()
            conn.close()
            return redirect(url_for('import_data', success='true'))
    return render_template('import.html')

@app.route('/import_generate_codes', methods=['POST'])
def import_generate_codes():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id'] if session['school_id'] != 0 else 999
        
    file = request.files['file']
    if file and file.filename.endswith('.csv'):
        csv_file = TextIOWrapper(file, encoding='utf-8')
        reader = csv.reader(csv_file)
        next(reader) 
        conn = get_db()
        c = conn.cursor()
        
        for row in reader:
            if len(row) >= 4:
                title, author, isbn = row[0], row[1], row[2]
                try: quantity = int(row[3])
                except ValueError: quantity = 0
                prefix = title[:2].upper() 
                for i in range(1, quantity + 1):
                    book_code = f"{prefix} {i:02d}"
                    c.execute("INSERT INTO books (school_id, title, author, isbn, quantity, book_code, condition) VALUES (?, ?, ?, ?, 1, ?, 'Good')",
                              (sid, title, author, isbn, book_code))
        conn.commit()
        conn.close()
        return redirect(url_for('import_data', success='true'))
    return redirect(url_for('import_data'))

# ---------- REPORTS ----------
@app.route('/reports')
def reports():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    today_str = date.today().strftime("%Y-%m-%d")
    current_month = date.today().strftime("%Y-%m")

    where_clause = "" if sid == 0 else "WHERE loans.school_id = ?"
    params = () if sid == 0 else (sid,)

    overdue_books_raw = conn.execute(f'''
        SELECT loans.id, loans.due_date, books.title, 
               students.name as student_name, students.class_name,
               teachers.name as teacher_name
        FROM loans 
        JOIN books ON loans.book_id = books.id 
        LEFT JOIN students ON loans.student_id = students.id
        LEFT JOIN teachers ON loans.teacher_id = teachers.id
        {where_clause} {'AND' if sid != 0 else 'WHERE'} loans.status = 'issued' AND loans.due_date < ?
    ''', (*params, today_str)).fetchall()

    overdue_books = []
    today = date.today()
    for row in overdue_books_raw:
        row_dict = dict(row)
        due_date_obj = date.fromisoformat(row_dict['due_date'])
        days_late = (today - due_date_obj).days
        row_dict['days_late'] = days_late
        row_dict['fine'] = days_late * 100
        overdue_books.append(row_dict)

    monthly_issued = conn.execute(f"SELECT COUNT(*) FROM loans {where_clause} {'AND' if sid != 0 else 'WHERE'} issue_date LIKE ?", (*params, f"{current_month}%")).fetchone()[0]

    most_borrowed_book = conn.execute(f"SELECT books.title, COUNT(loans.id) as borrow_count FROM loans JOIN books ON loans.book_id = books.id {where_clause} GROUP BY books.title ORDER BY borrow_count DESC LIMIT 1", params).fetchone()
    most_active_class = conn.execute(f"SELECT students.class_name, COUNT(loans.id) as borrow_count FROM loans JOIN students ON loans.student_id = students.id {where_clause} GROUP BY students.class_name ORDER BY borrow_count DESC LIMIT 1", params).fetchone()
    top_student = conn.execute(f"SELECT students.name, students.class_name, COUNT(loans.id) as borrow_count FROM loans JOIN students ON loans.student_id = students.id {where_clause} GROUP BY students.id ORDER BY borrow_count DESC LIMIT 1", params).fetchone()
    top_teacher = conn.execute(f"SELECT teachers.name, teachers.department, COUNT(loans.id) as borrow_count FROM loans JOIN teachers ON loans.teacher_id = teachers.id {where_clause} GROUP BY teachers.id ORDER BY borrow_count DESC LIMIT 1", params).fetchone()

    conn.close()
    return render_template('reports.html', overdue=overdue_books, monthly_count=monthly_issued,
                           most_borrowed=most_borrowed_book, active_class=most_active_class,
                           top_student=top_student, top_teacher=top_teacher)

# --- EXPORT ROUTES ---
@app.route('/export_overdue')
def export_overdue():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    today_str = date.today().strftime("%Y-%m-%d")
    overdue_books = conn.execute("SELECT books.title, students.name as student_name, students.class_name, loans.due_date, teachers.name as teacher_name FROM loans JOIN books ON loans.book_id = books.id LEFT JOIN students ON loans.student_id = students.id LEFT JOIN teachers ON loans.teacher_id = teachers.id WHERE loans.school_id=? AND loans.status = 'issued' AND loans.due_date < ?", (sid, today_str)).fetchall()
    conn.close()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Book Title', 'Borrower Name', 'Class/Dept', 'Due Date', 'Days Overdue', 'Fine (RWF)'])
    for row in overdue_books:
        borrower = row['student_name'] if row['student_name'] else row['teacher_name']
        detail = row['class_name'] if row['class_name'] else 'Teacher'
        due_date_obj = date.fromisoformat(row['due_date'])
        days_late = (date.today() - due_date_obj).days
        fine = days_late * 100
        cw.writerow([row['title'], borrower, detail, row['due_date'], days_late, fine])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=overdue_books.csv"})

@app.route('/export_monthly')
def export_monthly():
    if 'school_id' not in session: return redirect(url_for('login'))
    sid = session['school_id']
    conn = get_db()
    current_month = date.today().strftime("%Y-%m")
    monthly_loans = conn.execute("SELECT loans.issue_date, books.title, books.book_code, students.name as student_name, students.class_name, teachers.name as teacher_name, teachers.department FROM loans JOIN books ON loans.book_id = books.id LEFT JOIN students ON loans.student_id = students.id LEFT JOIN teachers ON loans.teacher_id = teachers.id WHERE loans.school_id=? AND loans.issue_date LIKE ? ORDER BY loans.issue_date DESC", (sid, f"{current_month}%")).fetchall()
    conn.close()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Issue Date', 'Book Title', 'Book Code', 'Borrower Name', 'Borrower Details'])
    for row in monthly_loans:
        borrower = row['student_name'] if row['student_name'] else row['teacher_name']
        detail = f"Class {row['class_name']}" if row['class_name'] else f"Teacher ({row['department']})"
        cw.writerow([row['issue_date'], row['title'], row['book_code'] or '-', borrower, detail])
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=monthly_report.csv"})

# ---------- PROFILE ----------
@app.route('/profile')
def profile():
    if 'school_id' not in session: return redirect(url_for('login'))
    if session['school_id'] == 0: return redirect(url_for('admin_dashboard'))
    
    sid = session['school_id']
    conn = get_db()
    user = conn.execute("SELECT librarian_name, school_name, email, password FROM librarians WHERE id=?", (sid,)).fetchone()
    conn.close()
    
    return render_template('profile.html', user=user)

@app.route('/update_password', methods=['POST'])
def update_password():
    if 'school_id' not in session or session['school_id'] == 0: return redirect(url_for('login'))
    
    new_password = request.form['new_password']
    sid = session['school_id']
    
    conn = get_db()
    conn.execute("UPDATE librarians SET password=? WHERE id=?", (new_password, sid))
    conn.commit()
    conn.close()
    
    return redirect(url_for('profile'))

# ---------- RUN ----------
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)