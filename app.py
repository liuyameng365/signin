from __future__ import annotations

import io
import os
import secrets
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
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from openpyxl import Workbook
from sqlalchemy import and_

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

    session = ScanSession.query.filter_by(token=token).first()
    if not session:
        return "二维码已失效或不存在", 404

    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(
            openid=openid,
            name=request.args.get("name", "新用户"),
            id_card=request.args.get("id_card", f"ID{secrets.randbelow(10**8):08d}"),
            work_area=request.args.get("work_area", "未知工区"),
            signed_days=0,
        )
        db.session.add(user)
        db.session.commit()

    session.user_id = user.id
    session.scanned_at = beijing_now()
    db.session.commit()

    return render_template("confirm.html", session=session, user=user)


@app.post("/checkin/<token>")
def do_checkin(token: str):
    session = ScanSession.query.filter_by(token=token).first()
    if not session or not session.user_id:
        flash("无效扫码会话，请重新扫码。", "error")
        return redirect(url_for("index"))

    user = User.query.get(session.user_id)
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
        session.checked_in = True
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


@app.route("/admin")
def admin_page() -> str:
    filters = {
        "name": request.args.get("name", "").strip(),
        "id_card": request.args.get("id_card", "").strip(),
        "work_area": request.args.get("work_area", "").strip(),
    }
    rows = query_checkins(**filters)
    return render_template("admin.html", rows=rows, filters=filters)


@app.route("/admin/export")
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


if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_demo_users()
    app.run(host="0.0.0.0", port=5000, debug=True)
