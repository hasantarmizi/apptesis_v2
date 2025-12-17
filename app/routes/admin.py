from flask import Blueprint, render_template, redirect, url_for, send_file, request, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import (
    User, Student, RiasecQuestion, RiasecAnswer, RiasecResult,
    ReportScore, Recommendation
)
from sqlalchemy import or_, func
from werkzeug.security import generate_password_hash
import io, csv
import math

admin_bp = Blueprint('admin', __name__)


# -----------------------
# Helper: admin-only decorator (simple)
# -----------------------
def _require_admin():
    if getattr(current_user, "role", None) != "admin":
        flash("Akses ditolak. Hanya admin yang dapat mengakses halaman ini.", "danger")
        return False
    return True


# -----------------------
# Dashboard
# -----------------------
@admin_bp.route('/admin')
@login_required
def dashboard_admin():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    # ambil query pencarian, status, dan pagination
    q = request.args.get('q', '').strip()
    status = request.args.get('status', 'semua')  # 'semua' | 'sudah' | 'belum'
    page = request.args.get('page', 1, type=int)
    per_page = 12

    # statistik keseluruhan
    total_siswa = Student.query.count()
    total_guru = User.query.filter_by(role="guru").count()
    siswa_sudah_tes = db.session.query(func.count(func.distinct(RiasecResult.id_student))).scalar() or 0

    # Statistik paket (dihitung dari semua Recommendation)
    total_rekom = Recommendation.query.count()
    paket1 = Recommendation.query.filter_by(paket_prediksi="Paket 1").count()
    paket2 = Recommendation.query.filter_by(paket_prediksi="Paket 2").count()
    paket3 = Recommendation.query.filter_by(paket_prediksi="Paket 3").count()
    paket1_pct = round(100 * paket1 / total_rekom, 1) if total_rekom else 0
    paket2_pct = round(100 * paket2 / total_rekom, 1) if total_rekom else 0
    paket3_pct = round(100 * paket3 / total_rekom, 1) if total_rekom else 0

    # Siapkan base query untuk students (terfilter jika q/status ada)
    student_query = Student.query

    if q:
        filters = [Student.nama.ilike(f'%{q}%'), Student.nisn.ilike(f'%{q}%')]
        if hasattr(Student, 'kelas'):
            filters.append(Student.kelas.ilike(f'%{q}%'))
        student_query = student_query.filter(or_(*filters))

    # apply status filter: gunakan subquery RiasecResult.id_student
    if status in ('sudah', 'belum'):
        sub = db.session.query(RiasecResult.id_student).subquery()
        if status == 'sudah':
            student_query = student_query.filter(Student.id.in_(sub))
        else:
            student_query = student_query.filter(~Student.id.in_(sub))

    student_query = student_query.order_by(Student.nama)

    pagination = student_query.paginate(page=page, per_page=per_page, error_out=False)
    students_page = pagination.items

    # Data untuk tabel siswa (hanya untuk current page) - sertakan kode_riasec & user_id
    data_siswa = []
    for s in students_page:
        result = RiasecResult.query.filter_by(id_student=s.id).first()
        kode_riasec = result.top3 if result else "-"
        status_tes = "Sudah Tes" if result else "Belum Tes"
        rekom = Recommendation.query.filter_by(id_student=s.id).first()
        paket = rekom.paket_prediksi if rekom else "-"
        user_id = getattr(s.user, "id", None) if hasattr(s, "user") else None
        data_siswa.append({
            "id": s.id,
            "nama": s.nama,
            "nisn": s.nisn,
            "kelas": getattr(s, "kelas", "") or "",
            "status_tes": status_tes,
            "paket": paket,
            "kode_riasec": kode_riasec,
            "user_id": user_id
        })

    return render_template(
        'dashboard_admin.html',
        total_siswa=total_siswa,
        total_guru=total_guru,
        siswa_sudah_tes=siswa_sudah_tes,
        data_siswa=data_siswa,
        paket1_pct=paket1_pct,
        paket2_pct=paket2_pct,
        paket3_pct=paket3_pct,
        q=q,
        status=status,
        pagination=pagination
    )


# -----------------------
# Add / Create endpoints
# -----------------------
@admin_bp.route('/admin/add-student', methods=['POST'])
@login_required
def add_student():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    nama = request.form.get('nama', '').strip()
    nisn = request.form.get('nisn', '').strip()
    kelas = request.form.get('kelas', '').strip()

    if not nama or not nisn:
        flash("Nama dan NISN wajib diisi.", "danger")
        return redirect(url_for('admin.dashboard_admin'))

    existing_student = Student.query.filter_by(nisn=nisn).first()
    if existing_student:
        flash("NISN sudah terdaftar.", "warning")
        return redirect(url_for('admin.dashboard_admin'))

    # username default = nisn
    username = nisn
    if User.query.filter_by(username=username).first():
        idx = 1
        base = username or "siswa"
        while User.query.filter_by(username=f"{base}{idx}").first():
            idx += 1
        username = f"{base}{idx}"

    default_password = "123456"
    # buat user dan set password (gunakan helper jika ada)
    user = User(username=username, role='siswa')
    if hasattr(user, 'set_password'):
        user.set_password(default_password)
    else:
        user.password = generate_password_hash(default_password)

    db.session.add(user)
    db.session.commit()  # commit dulu untuk mendapat id user

    s = Student(id_user=user.id, nama=nama, nisn=nisn)
    if hasattr(s, 'kelas'):
        setattr(s, 'kelas', kelas)
    db.session.add(s)
    db.session.commit()

    flash(f"Siswa berhasil ditambahkan. Akun siswa dibuat dengan username: {username} dan password default: {default_password}", "success")
    return redirect(url_for('admin.dashboard_admin'))


@admin_bp.route('/admin/add-guru', methods=['POST'])
@login_required
def add_guru():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash("Username dan password wajib diisi.", "danger")
        return redirect(url_for('admin.dashboard_admin'))

    if User.query.filter_by(username=username).first():
        flash("Username sudah digunakan.", "warning")
        return redirect(url_for('admin.dashboard_admin'))

    user = User(username=username, role='guru')
    if hasattr(user, 'set_password'):
        user.set_password(password)
    else:
        user.password = generate_password_hash(password)

    db.session.add(user)
    db.session.commit()

    flash("Akun guru berhasil dibuat.", "success")
    return redirect(url_for('admin.dashboard_admin'))


@admin_bp.route('/admin/create-user', methods=['POST'])
@login_required
def create_user():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'guru').strip()
    nama = request.form.get('nama', '').strip()   # optional
    nisn = request.form.get('nisn', '').strip()   # optional (for siswa)
    kelas = request.form.get('kelas', '').strip() # optional (for siswa)

    if not username or not password:
        flash("Username dan password wajib diisi.", "danger")
        return redirect(url_for('admin.dashboard_admin'))

    if User.query.filter_by(username=username).first():
        flash("Username sudah digunakan.", "warning")
        return redirect(url_for('admin.dashboard_admin'))

    user = User(username=username, role=role)
    if hasattr(user, 'set_password'):
        user.set_password(password)
    else:
        user.password = generate_password_hash(password)
    db.session.add(user)
    db.session.commit()

    # Jika membuat akun siswa lewat create_user: buat juga profile Student
    if role == 'siswa':
        if nisn:
            if Student.query.filter_by(nisn=nisn).first():
                flash("Peringatan: NISN sudah ada, akun dibuat tapi profile siswa tidak dibuat.", "warning")
            else:
                s = Student(id_user=user.id, nama=nama or username, nisn=nisn)
                if hasattr(s, 'kelas') and kelas:
                    setattr(s, 'kelas', kelas)
                db.session.add(s)
                db.session.commit()
                flash("Akun pengguna dan profile siswa berhasil dibuat.", "success")
                return redirect(url_for('admin.dashboard_admin'))
        else:
            s = Student(id_user=user.id, nama=nama or username, nisn=None)
            if hasattr(s, 'kelas') and kelas:
                setattr(s, 'kelas', kelas)
            db.session.add(s)
            db.session.commit()
            flash("Akun pengguna siswa dibuat. Profile siswa dibuat tanpa NISN.", "success")
            return redirect(url_for('admin.dashboard_admin'))

    flash("Akun pengguna berhasil dibuat.", "success")
    return redirect(url_for('admin.dashboard_admin'))


# -----------------------
# Question management (baru ditambahkan)
# -----------------------
@admin_bp.route('/admin/questions')
@login_required
def manage_questions():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    # pagination + search
    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = RiasecQuestion.query
    if q:
        query = query.filter(RiasecQuestion.pertanyaan.ilike(f'%{q}%'))
    query = query.order_by(RiasecQuestion.id.asc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    questions = pagination.items

    # optionally load a question to edit (edit_id passed as query param)
    edit_id = request.args.get('edit_id', type=int)
    edit_question = None
    if edit_id:
        edit_question = RiasecQuestion.query.get(edit_id)
        if not edit_question:
            flash("Pertanyaan untuk diedit tidak ditemukan.", "warning")
            edit_question = None

    return render_template('manage_questions.html', questions=questions, pagination=pagination, q=q, edit_question=edit_question)


# Modifikasi kecil: arahkan add_question kembali ke manage_questions (sebelumnya dashboard)
@admin_bp.route('/admin/add-question', methods=['POST'])
@login_required
def add_question():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    question_text = request.form.get('question_text', '').strip()
    code = request.form.get('code', '').strip().upper()  # R/I/A/S/E/C

    if not question_text or not code:
        flash("Teks pertanyaan dan kode (dimensi) wajib diisi.", "danger")
        # redirect kembali ke halaman manajemen pertanyaan
        return redirect(url_for('admin.manage_questions'))

    q = RiasecQuestion(pertanyaan=question_text, dimensi=code)
    db.session.add(q)
    db.session.commit()
    flash("Pertanyaan RIASEC berhasil ditambahkan.", "success")
    return redirect(url_for('admin.manage_questions'))


@admin_bp.route('/admin/questions/edit/<int:question_id>', methods=['POST'])
@login_required
def edit_question_route(question_id):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    qobj = RiasecQuestion.query.get(question_id)
    if not qobj:
        flash("Pertanyaan tidak ditemukan.", "warning")
        return redirect(url_for('admin.manage_questions'))

    question_text = request.form.get('question_text', '').strip()
    code = request.form.get('code', '').strip().upper()

    if not question_text or not code:
        flash("Teks pertanyaan dan kode (dimensi) wajib diisi.", "danger")
        return redirect(url_for('admin.manage_questions', edit_id=question_id))

    try:
        qobj.pertanyaan = question_text
        qobj.dimensi = code
        db.session.commit()
        flash("Pertanyaan berhasil diperbarui.", "success")
    except Exception as e:
        current_app.logger.error(f"Error mengupdate pertanyaan {question_id}: {e}")
        db.session.rollback()
        flash("Gagal memperbarui pertanyaan.", "danger")

    return redirect(url_for('admin.manage_questions'))


@admin_bp.route('/admin/questions/delete/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    qobj = RiasecQuestion.query.get(question_id)
    if not qobj:
        flash("Pertanyaan tidak ditemukan.", "warning")
        return redirect(url_for('admin.manage_questions'))

    try:
        db.session.delete(qobj)
        db.session.commit()
        flash("Pertanyaan berhasil dihapus.", "success")
    except Exception as e:
        current_app.logger.error(f"Error menghapus pertanyaan {question_id}: {e}")
        db.session.rollback()
        flash("Gagal menghapus pertanyaan.", "danger")

    return redirect(url_for('admin.manage_questions'))


# -----------------------
# User management: list, reset password, delete
# -----------------------
@admin_bp.route('/admin/users')
@login_required
def manage_users():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    q = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 15

    user_query = User.query
    if q:
        user_query = user_query.filter(or_(User.username.ilike(f'%{q}%'), User.role.ilike(f'%{q}%')))
    user_query = user_query.order_by(User.username)

    pagination = user_query.paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items

    return render_template('manage_users.html', users=users, pagination=pagination, q=q)


@admin_bp.route('/admin/users/reset-password/<int:user_id>', methods=['POST'])
@login_required
def reset_user_password(user_id):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    default_password = request.form.get('default_password', '123456')
    user = User.query.get(user_id)
    if not user:
        flash("Pengguna tidak ditemukan.", "warning")
        return redirect(url_for('admin.manage_users'))

    try:
        if hasattr(user, 'set_password'):
            user.set_password(default_password)
        else:
            user.password = generate_password_hash(default_password)
        db.session.commit()
        flash(f"Password pengguna {user.username} di-reset.", "success")
    except Exception as e:
        current_app.logger.error(f"Error reset password user {user_id}: {e}")
        db.session.rollback()
        flash("Gagal mereset password.", "danger")

    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user:
        flash("Pengguna tidak ditemukan.", "warning")
        return redirect(url_for('admin.manage_users'))

    try:
        if user.role == 'siswa':
            student = Student.query.filter_by(id_user=user.id).first()
            if student:
                RiasecAnswer.query.filter_by(id_student=student.id).delete(synchronize_session=False)
                RiasecResult.query.filter_by(id_student=student.id).delete(synchronize_session=False)
                ReportScore.query.filter_by(id_student=student.id).delete(synchronize_session=False)
                Recommendation.query.filter_by(id_student=student.id).delete(synchronize_session=False)
                Student.query.filter_by(id=student.id).delete(synchronize_session=False)

        User.query.filter_by(id=user.id).delete(synchronize_session=False)
        db.session.commit()
        flash("Pengguna dan data terkait berhasil dihapus.", "success")
    except Exception as e:
        current_app.logger.error(f"Error saat menghapus user {user_id}: {e}")
        db.session.rollback()
        flash("Terjadi kesalahan saat menghapus pengguna.", "danger")

    return redirect(url_for('admin.manage_users'))


# -----------------------
# CSV / Export endpoints
# -----------------------
@admin_bp.route('/admin/download-csv')
@login_required
def download_csv():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    q = request.args.get('q', '').strip()
    status = request.args.get('status', 'semua')  # honor status filter when exporting

    student_query = Student.query
    if q:
        filters = [Student.nama.ilike(f'%{q}%'), Student.nisn.ilike(f'%{q}%')]
        if hasattr(Student, 'kelas'):
            filters.append(Student.kelas.ilike(f'%{q}%'))
        student_query = student_query.filter(or_(*filters))

    # apply status filter for export as well
    if status in ('sudah', 'belum'):
        sub = db.session.query(RiasecResult.id_student).subquery()
        if status == 'sudah':
            student_query = student_query.filter(Student.id.in_(sub))
        else:
            student_query = student_query.filter(~Student.id.in_(sub))

    students = student_query.order_by(Student.nama).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['NISN', 'Nama', 'Kelas', 'Status Tes', 'Paket Rekomendasi'])
    for s in students:
        result = RiasecResult.query.filter_by(id_student=s.id).first()
        status_tes = "Sudah Tes" if result else "Belum Tes"
        rekom = Recommendation.query.filter_by(id_student=s.id).first()
        paket = rekom.paket_prediksi if rekom else "-"
        kelas = getattr(s, "kelas", "") or ""
        writer.writerow([s.nisn, s.nama, kelas, status_tes, paket])
    csv_bytes = output.getvalue().encode('utf-8-sig')  # add BOM for Excel
    output.close()

    return send_file(
        io.BytesIO(csv_bytes),
        mimetype='text/csv',
        as_attachment=True,
        download_name='data_siswa.csv'
    )


@admin_bp.route('/admin/export-siswa/<nisn>')
@login_required
def export_siswa(nisn):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    s = Student.query.filter_by(nisn=nisn).first()
    if not s:
        return redirect(url_for('admin.dashboard_admin'))

    result = RiasecResult.query.filter_by(id_student=s.id).first()
    rekom = Recommendation.query.filter_by(id_student=s.id).first()
    kode = result.top3 if result else ""
    paket = rekom.paket_prediksi if rekom else ""
    kelas = getattr(s, "kelas", "") or ""

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['NISN', 'Nama', 'Kelas', 'Kode RIASEC', 'Paket Rekomendasi'])
    writer.writerow([s.nisn, s.nama, kelas, kode, paket])
    csv_bytes = output.getvalue().encode('utf-8-sig')
    output.close()

    return send_file(
        io.BytesIO(csv_bytes),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'siswa_{s.nisn}.csv'
    )


@admin_bp.route('/admin/siswa/<nisn>')
@login_required
def siswa_detail(nisn):
    if not _require_admin():
        return redirect(url_for('auth.login'))

    s = Student.query.filter_by(nisn=nisn).first()
    if not s:
        return redirect(url_for('admin.dashboard_admin'))

    result = RiasecResult.query.filter_by(id_student=s.id).first()
    rekom = Recommendation.query.filter_by(id_student=s.id).first()

    siswa_data = {
        "id": s.id,
        "nama": getattr(s, "nama", ""),
        "nisn": getattr(s, "nisn", ""),
        "kelas": getattr(s, "kelas", "") or "",
    }

    riasec_data = {}
    if result:
        riasec_data["top3"] = getattr(result, "top3", "")
        riasec_data["detail"] = getattr(result, "scores", None) or getattr(result, "detail", None) or None

    rekom_data = {}
    if rekom:
        rekom_data["paket_prediksi"] = getattr(rekom, "paket_prediksi", "")
        rekom_data["confidence"] = getattr(rekom, "confidence", None)

    return render_template('siswa_detail.html', siswa=siswa_data, riasec=riasec_data, rekom=rekom_data)