from __future__ import annotations

import io
import os
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

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

def build_database_uri() -> str:
    """仅支持 MySQL。"""

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    mysql_host = os.getenv("MYSQL_HOST", "127.0.0.1")
    mysql_port = os.getenv("MYSQL_PORT", "3306")
    mysql_user = os.getenv("MYSQL_USER", "root")
    mysql_password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
    mysql_db = os.getenv("MYSQL_DB", "signin")
    mysql_charset = os.getenv("MYSQL_CHARSET", "utf8mb4")

    return (
        f"mysql+pymysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/"
        f"{mysql_db}?charset={mysql_charset}"
    )


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ScanSession(db.Model):
    __tablename__ = "scan_sessions"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    scanned_at = db.Column(db.DateTime, nullable=True)
    checked_in = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Checkin(db.Model):
    __tablename__ = "checkins"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    session_token = db.Column(db.String(64), nullable=False)
    checkin_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


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
    session.scanned_at = datetime.utcnow()
    db.session.commit()

    return render_template("confirm.html", session=session, user=user)


@app.post("/checkin/<token>")
def do_checkin(token: str):
    session = ScanSession.query.filter_by(token=token).first()
    if not session or not session.user_id:
        flash("无效扫码会话，请重新扫码。", "error")
        return redirect(url_for("index"))

    user = User.query.get(session.user_id)
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

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

    filename = f"签到记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
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
