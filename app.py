from __future__ import annotations

import io
import os
import secrets
from functools import wraps
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import qrcode
from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from openpyxl import Workbook
from sqlalchemy import and_
from werkzeug.security import check_password_hash, generate_password_hash

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
BASE_DIR = Path(__file__).resolve().parent


def load_local_env() -> None:
    """从项目根目录加载 .env，已存在的环境变量不覆盖。"""

    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


def beijing_now() -> datetime:
    """返回北京时间的 naive datetime，用于与当前数据库字段保持一致。"""

    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def beijing_today() -> date:
    return datetime.now(BEIJING_TZ).date()


def build_database_uri() -> str:
    """仅支持 PostgreSQL。"""

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    pg_host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    raw_password = os.getenv("POSTGRES_PASSWORD", "")
    pg_db = os.getenv("POSTGRES_DB", "signin")

    if not raw_password:
        raise RuntimeError(
            "未配置 POSTGRES_PASSWORD。请在环境变量或项目根目录 .env 中设置它，"
            "或者直接设置 DATABASE_URL。"
        )

    pg_password = quote_plus(raw_password)

    return (
        f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/"
        f"{pg_db}"
    )


load_local_env()
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-change-me")

db = SQLAlchemy(app)

ADMIN_ROLES = {
    "viewer": {"label": "查看员", "permissions": {"dashboard:view"}},
    "manager": {
        "label": "管理员",
        "permissions": {"dashboard:view", "dashboard:export", "admin_users:manage"},
    },
}


def has_permission(permission: str) -> bool:
    admin = getattr(g, "admin_user", None)
    if not admin or not admin.is_active:
        return False

    role = ADMIN_ROLES.get(admin.role, {})
    return permission in role.get("permissions", set())


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not getattr(g, "admin_user", None):
            flash("请先登录后台。", "warning")
            return redirect(url_for("admin_login", next=request.url))
        return view(*args, **kwargs)

    return wrapped_view


def permission_required(permission: str):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not getattr(g, "admin_user", None):
                flash("请先登录后台。", "warning")
                return redirect(url_for("admin_login", next=request.url))
            if not has_permission(permission):
                flash("当前账号没有访问该功能的权限。", "error")
                return redirect(url_for("admin_page"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    openid = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    id_card = db.Column(db.String(30), unique=True, nullable=False)
    work_area = db.Column(db.String(100), nullable=False)
    signed_days = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=beijing_now, nullable=False)


class ScanSession(db.Model):
    __tablename__ = "scan_sessions"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    scanned_at = db.Column(db.DateTime, nullable=True)
    checked_in = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=beijing_now, nullable=False)


class Checkin(db.Model):
    __tablename__ = "checkins"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_token = db.Column(db.String(64), nullable=False)
    checkin_time = db.Column(db.DateTime, default=beijing_now, nullable=False)


class AdminUser(db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="viewer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=beijing_now, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


def init_db() -> None:
    db.create_all()


def seed_demo_users() -> None:
    demo_users = [
        {
            "openid": "wx_openid_zhangsan",
            "name": "张三",
            "id_card": "110101199001010011",
            "work_area": "一工区",
        },
        {
            "openid": "wx_openid_lisi",
            "name": "李四",
            "id_card": "110101199202023344",
            "work_area": "二工区",
        },
        {
            "openid": "wx_openid_wangwu",
            "name": "王五",
            "id_card": "110101198812129876",
            "work_area": "三工区",
        },
    ]
    for user_data in demo_users:
        exists = User.query.filter_by(openid=user_data["openid"]).first()
        if not exists:
            db.session.add(User(**user_data))
    db.session.commit()


def seed_admin_user() -> None:
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin123456")
    display_name = os.getenv("ADMIN_DISPLAY_NAME", "系统管理员")
    role = os.getenv("ADMIN_ROLE", "manager")
    if role not in ADMIN_ROLES:
        role = "manager"

    exists = AdminUser.query.filter_by(username=username).first()
    if exists:
        return

    admin = AdminUser(
        username=username,
        display_name=display_name,
        role=role,
        is_active=True,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


def get_or_create_scan_session(token: str) -> Optional[ScanSession]:
    return ScanSession.query.filter_by(token=token).first()


def sanitize_openid(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned:
        return cleaned
    return f"guest_{secrets.token_hex(8)}"


@app.before_request
def load_admin_user() -> None:
    admin_id = session.get("admin_user_id")
    g.admin_user = db.session.get(AdminUser, admin_id) if admin_id else None
    g.admin_permissions = (
        ADMIN_ROLES.get(g.admin_user.role, {}).get("permissions", set())
        if g.admin_user and g.admin_user.is_active
        else set()
    )


@app.route("/")
def index() -> str:
    token = secrets.token_urlsafe(16)
    session = ScanSession(token=token)
    db.session.add(session)
    db.session.commit()
    return render_template("index.html", token=token)


@app.route("/qr/<token>.png")
def qr_image(token: str) -> Response:
    scan_url = url_for("wechat_scan", token=token, _external=True)
    image = qrcode.make(scan_url)
    img_io = io.BytesIO()
    image.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png")


@app.route("/wechat/mock_scan")
def wechat_scan() -> str:
    """模拟微信扫码获取身份信息。

    真实项目中需要替换成微信 OAuth / 企业微信身份接口。
    """

    token = request.args.get("token", "")
    openid = request.args.get("openid", "wx_openid_zhangsan")

    scan_session = get_or_create_scan_session(token)
    if not scan_session:
        return "二维码已失效或不存在", 404

    user = User.query.filter_by(openid=openid).first()
    if not user:
        session["pending_openid"] = sanitize_openid(openid)
        return redirect(url_for("user_profile_form", token=token))

    scan_session.user_id = user.id
    scan_session.scanned_at = beijing_now()
    db.session.commit()

    return render_template("confirm.html", session=scan_session, user=user)


@app.route("/profile/<token>", methods=["GET", "POST"])
def user_profile_form(token: str) -> str:
    scan_session = get_or_create_scan_session(token)
    if not scan_session:
        return "二维码已失效或不存在", 404

    form_data = {
        "name": request.form.get("name", "").strip(),
        "id_card": request.form.get("id_card", "").strip(),
        "work_area": request.form.get("work_area", "").strip(),
        "openid": request.form.get("openid", session.get("pending_openid", "")).strip(),
    }

    if request.method == "POST":
        if not all([form_data["name"], form_data["id_card"], form_data["work_area"]]):
            flash("请完整填写姓名、身份证号和所属工区。", "warning")
        else:
            existing_by_card = User.query.filter_by(id_card=form_data["id_card"]).first()
            if existing_by_card and existing_by_card.openid != form_data["openid"]:
                flash("该身份证号已存在，不能重复登记。", "error")
            else:
                user = User.query.filter_by(openid=form_data["openid"]).first()
                if not user:
                    user = User(
                        openid=sanitize_openid(form_data["openid"]),
                        signed_days=0,
                        name=form_data["name"],
                        id_card=form_data["id_card"],
                        work_area=form_data["work_area"],
                    )
                    db.session.add(user)
                else:
                    user.name = form_data["name"]
                    user.id_card = form_data["id_card"]
                    user.work_area = form_data["work_area"]

                db.session.flush()
                scan_session.user_id = user.id
                scan_session.scanned_at = beijing_now()
                db.session.commit()
                session.pop("pending_openid", None)
                flash("信息已保存，请确认签到。", "success")
                return render_template("confirm.html", session=scan_session, user=user)

    return render_template("profile.html", token=token, form_data=form_data)


@app.post("/checkin/<token>")
def do_checkin(token: str):
    scan_session = ScanSession.query.filter_by(token=token).first()
    if not scan_session or not scan_session.user_id:
        flash("无效扫码会话，请重新扫码。", "error")
        return redirect(url_for("index"))

    user = db.session.get(User, scan_session.user_id)
    today = beijing_today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    exists_today = Checkin.query.filter(
        and_(
            Checkin.user_id == user.id,
            Checkin.checkin_time >= today_start,
            Checkin.checkin_time <= today_end,
        )
    ).first()

    if exists_today:
        flash("今天已经签到过，无需重复签到。", "warning")
    else:
        checkin = Checkin(user_id=user.id, session_token=token)
        db.session.add(checkin)
        user.signed_days += 1
        scan_session.checked_in = True
        db.session.commit()
        flash("签到成功！", "success")

    return render_template("success.html", user=user)


def query_checkins(
    name: Optional[str] = None,
    id_card: Optional[str] = None,
    work_area: Optional[str] = None,
):
    q = (
        db.session.query(Checkin, User)
        .join(User, Checkin.user_id == User.id)
        .order_by(Checkin.checkin_time.desc())
    )

    if name:
        q = q.filter(User.name.like(f"%{name}%"))
    if id_card:
        q = q.filter(User.id_card.like(f"%{id_card}%"))
    if work_area:
        q = q.filter(User.work_area.like(f"%{work_area}%"))

    return q.all()


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if g.admin_user:
        return redirect(url_for("admin_page"))

    next_url = request.args.get("next") or request.form.get("next") or url_for("admin_page")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = AdminUser.query.filter_by(username=username).first()
        if not admin or not admin.is_active or not admin.check_password(password):
            flash("用户名或密码错误。", "error")
        else:
            session["admin_user_id"] = admin.id
            flash("登录成功。", "success")
            return redirect(next_url)

    return render_template("admin_login.html", next_url=next_url)


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    session.pop("admin_user_id", None)
    flash("已退出登录。", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@permission_required("dashboard:view")
def admin_page() -> str:
    filters = {
        "name": request.args.get("name", "").strip(),
        "id_card": request.args.get("id_card", "").strip(),
        "work_area": request.args.get("work_area", "").strip(),
    }
    rows = query_checkins(**filters)
    return render_template("admin.html", rows=rows, filters=filters)


@app.route("/admin/export")
@permission_required("dashboard:export")
def export_excel():
    filters = {
        "name": request.args.get("name", "").strip(),
        "id_card": request.args.get("id_card", "").strip(),
        "work_area": request.args.get("work_area", "").strip(),
    }
    rows = query_checkins(**filters)

    wb = Workbook()
    ws = wb.active
    ws.title = "签到记录"
    ws.append(["姓名", "身份证号", "所属工区", "累计签到天数", "签到时间"])

    for checkin, user in rows:
        ws.append(
            [
                user.name,
                user.id_card,
                user.work_area,
                user.signed_days,
                checkin.checkin_time.strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"签到记录_{beijing_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/admin/accounts", methods=["GET", "POST"])
@permission_required("admin_users:manage")
def admin_accounts():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "viewer").strip()

        if not username or not display_name or not password:
            flash("请完整填写账号、姓名和密码。", "warning")
        elif role not in ADMIN_ROLES:
            flash("角色配置无效。", "error")
        elif AdminUser.query.filter_by(username=username).first():
            flash("该后台账号已存在。", "warning")
        else:
            admin = AdminUser(
                username=username,
                display_name=display_name,
                role=role,
                is_active=True,
            )
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            flash("后台账号创建成功。", "success")
            return redirect(url_for("admin_accounts"))

    admins = AdminUser.query.order_by(AdminUser.created_at.desc()).all()
    return render_template("admin_accounts.html", admins=admins, role_options=ADMIN_ROLES)


@app.post("/admin/accounts/<int:admin_id>/toggle")
@permission_required("admin_users:manage")
def toggle_admin_account(admin_id: int):
    admin = db.session.get(AdminUser, admin_id)
    if not admin:
        flash("管理员账号不存在。", "error")
        return redirect(url_for("admin_accounts"))
    if admin.id == g.admin_user.id:
        flash("不能禁用当前登录账号。", "warning")
        return redirect(url_for("admin_accounts"))

    admin.is_active = not admin.is_active
    db.session.commit()
    flash("账号状态已更新。", "success")
    return redirect(url_for("admin_accounts"))


if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_demo_users()
        seed_admin_user()
    app.run(host="0.0.0.0", port=5000, debug=True)
