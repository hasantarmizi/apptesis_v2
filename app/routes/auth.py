from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app import db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/', methods=['GET'])
def home():
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()
        valid = False
        if user:
            # Prefer method on model (uses werkzeug hashing)
            if hasattr(user, 'check_password') and callable(getattr(user, 'check_password')):
                try:
                    valid = user.check_password(password)
                except Exception:
                    valid = False
            else:
                # Fallbacks: try werkzeug check_password_hash if available, then plain compare
                try:
                    from werkzeug.security import check_password_hash
                    valid = check_password_hash(user.password, password)
                except Exception:
                    # last resort: plain equality (only for legacy/temporary use)
                    valid = (user.password == password)

        if user and valid:
            login_user(user)
            if user.role == "admin":
                return redirect(url_for('admin.dashboard_admin'))
            elif user.role == "guru":
                return redirect(url_for('guru.dashboard_guru'))
            else:
                return redirect(url_for('siswa.dashboard_siswa'))
        else:
            flash("Login gagal. Cek username/password!", "danger")
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))  