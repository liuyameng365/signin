# 微信扫码签到系统（Flask）

这是一个使用 Python + Flask 实现的签到系统示例，支持：

- 访问签到页面生成二维码。
- 微信扫码（演示中使用 `mock_scan` 模拟微信身份回调）并展示身份信息。
- 用户点击确认签到后，将签到信息写入数据库（默认 MySQL，可切换 SQLite）。
- 后台管理页按姓名 / 身份证号 / 工区查询签到记录。
- 支持导出 Excel。

> 说明：真实微信身份获取需要接入微信 OAuth/企业微信 API。本项目中 `GET /wechat/mock_scan` 是演示接口。

## 运行方式

### 1) 准备 MySQL 数据库（默认）

```sql
CREATE DATABASE IF NOT EXISTS signin DEFAULT CHARACTER SET utf8mb4;
```

设置环境变量（推荐）：

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_USER=root
export MYSQL_PASSWORD=你的密码
export MYSQL_DB=signin
export SECRET_KEY=请替换为随机字符串
```

> 也可以直接设置 `DATABASE_URL`：
>
> `mysql+pymysql://user:password@host:3306/signin?charset=utf8mb4`

### 2) 启动应用

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### 3) 开发模式切回 SQLite（可选）

```bash
export USE_SQLITE=1
```

打开浏览器访问：

- 扫码页：`http://127.0.0.1:5000/`
- 后台页：`http://127.0.0.1:5000/admin`

## API/页面说明

- `/`：生成一次扫码会话并显示二维码。
- `/qr/<token>.png`：返回二维码图片。
- `/wechat/mock_scan?token=xxx&openid=wx_openid_zhangsan`：模拟微信扫码回调。
- `POST /checkin/<token>`：确认签到。
- `/admin`：后台查询。
- `/admin/export`：导出 Excel。

## 数据库表

- `users`：用户身份信息（姓名、身份证号、工区、累计签到天数）。
- `scan_sessions`：扫码会话信息。
- `checkins`：签到明细（用户+签到时间）。
