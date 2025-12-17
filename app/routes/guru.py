from flask import Blueprint, render_template, redirect, url_for, make_response, request
from flask_login import login_required, current_user
from app.models import Student, RiasecResult, Recommendation
from app import db
from sqlalchemy import or_
import io, csv

guru_bp = Blueprint('guru', __name__)

@guru_bp.route('/guru')
@login_required
def dashboard_guru():
    if current_user.role != 'guru':
        return redirect(url_for('auth.login'))

    # ambil query pencarian (jika ada)
    q = request.args.get('q', '').strip()

    # Ambil semua siswa untuk menghitung statistik (tidak terpengaruh filter)
    students_all = Student.query.all()

    # Ambil siswa untuk tabel: terfilter jika ada q, else semua
    if q:
        students = Student.query.filter(
            or_(
                Student.nama.ilike(f'%{q}%'),
                Student.nisn.ilike(f'%{q}%')
            )
        ).all()
    else:
        students = students_all

    # Hitung statistik dari seluruh siswa (students_all)
    distribusi = {"Paket 1": 0, "Paket 2": 0, "Paket 3": 0}
    sudah_tes = 0
    belum_tes = 0
    for s in students_all:
        result = RiasecResult.query.filter_by(id_student=s.id).first()
        rekom = Recommendation.query.filter_by(id_student=s.id).first()
        if result:
            sudah_tes += 1
        else:
            belum_tes += 1
        paket = rekom.paket_prediksi if rekom else "-"
        if paket in distribusi:
            distribusi[paket] += 1

    # Siapkan list siswa untuk tabel (dari students yang mungkin terfilter)
    siswa_list = []
    for s in students:
        result = RiasecResult.query.filter_by(id_student=s.id).first()
        rekom = Recommendation.query.filter_by(id_student=s.id).first()
        kode_riasec = result.top3 if result else "-"
        paket = rekom.paket_prediksi if rekom else "-"
        siswa_list.append({
            "nama": s.nama,
            "nisn": s.nisn,
            "kelas": getattr(s, "kelas", "") or "",
            "kode_riasec": kode_riasec,
            "paket_rekomendasi": paket,
            "id": s.id
        })

    distribusi_list = [distribusi["Paket 1"], distribusi["Paket 2"], distribusi["Paket 3"]]
    siswa_total = len(students_all)  # total siswa (untuk menampilkan "X dari Y")

    return render_template(
        "dashboard_guru.html",
        siswa_list=siswa_list,
        siswa_sudah_tes=sudah_tes,
        siswa_belum_tes=belum_tes,
        distribusi=distribusi_list,
        siswa_total=siswa_total
    )

# -----------------------
# Small helpers/endpoints used by template (minimal implementations)
# -----------------------

@guru_bp.route('/guru/download_csv')
@login_required
def download_csv():
    if current_user.role != 'guru':
        return redirect(url_for('auth.login'))

    students = Student.query.all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['NISN', 'Nama', 'Kelas', 'Kode RIASEC', 'Paket Rekomendasi'])
    for s in students:
        result = RiasecResult.query.filter_by(id_student=s.id).first()
        rekom = Recommendation.query.filter_by(id_student=s.id).first()
        kode = result.top3 if result else ""
        paket = rekom.paket_prediksi if rekom else ""
        kelas = getattr(s, "kelas", "") or ""
        cw.writerow([s.nisn, s.nama, kelas, kode, paket])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=siswa_all.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@guru_bp.route('/guru/export_siswa/<nisn>')
@login_required
def export_siswa(nisn):
    if current_user.role != 'guru':
        return redirect(url_for('auth.login'))

    s = Student.query.filter_by(nisn=nisn).first()
    if not s:
        return redirect(url_for('guru.dashboard_guru'))

    result = RiasecResult.query.filter_by(id_student=s.id).first()
    rekom = Recommendation.query.filter_by(id_student=s.id).first()
    kode = result.top3 if result else ""
    paket = rekom.paket_prediksi if rekom else ""
    kelas = getattr(s, "kelas", "") or ""

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['NISN', 'Nama', 'Kelas', 'Kode RIASEC', 'Paket Rekomendasi'])
    cw.writerow([s.nisn, s.nama, kelas, kode, paket])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=siswa_{s.nisn}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@guru_bp.route('/guru/siswa/<nisn>')
@login_required
def siswa_detail(nisn):
    if current_user.role != 'guru':
        return redirect(url_for('auth.login'))

    # Cari siswa berdasarkan NISN
    s = Student.query.filter_by(nisn=nisn).first()
    if not s:
        # bila tidak ditemukan, kembali ke dashboard
        return redirect(url_for('guru.dashboard_guru'))

    # Ambil hasil RIASEC dan rekomendasi (jika ada)
    result = RiasecResult.query.filter_by(id_student=s.id).first()
    rekom = Recommendation.query.filter_by(id_student=s.id).first()

    # Siapkan data aman untuk template (gunakan getattr bila atribut model berbeda)
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

    return render_template(
        "siswa_detail.html",
        siswa=siswa_data,
        riasec=riasec_data,
        rekom=rekom_data
    )