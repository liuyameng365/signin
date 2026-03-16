# 微信扫码签到系统（Flask）

这是一个使用 Python + Flask 实现的签到系统示例，支持：

- 访问签到页面生成二维码。
- 微信扫码（演示中使用 `mock_scan` 模拟微信身份回调）并展示身份信息。
- 首次扫码时，用户可在手机端自行填写姓名、身份证号、所属工区。
- 用户点击确认签到后，将签到信息写入数据库（默认 PostgreSQL）。
- 后台管理页按姓名 / 身份证号 / 工区查询签到记录。
- 后台支持登录认证、角色权限控制和管理员账号管理。
- 支持导出 Excel。

> 说明：真实微信身份获取需要接入微信 OAuth/企业微信 API。本项目中 `GET /wechat/mock_scan` 是演示接口。

## 运行方式

### 1) 准备 PostgreSQL 数据库（默认）

```sql
CREATE DATABASE signin;
```

设置环境变量（推荐）：

```bash
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=你的密码
export POSTGRES_DB=signin
export SECRET_KEY=请替换为随机字符串
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=请替换为后台初始密码
```

> 也可以直接设置 `DATABASE_URL`：
>
> `postgresql+psycopg2://user:password@host:5432/signin`

### 2) 使用 `.env.example` 生成本地配置

```bash
cp .env.example .env
# 按你的环境修改 .env，至少要改 POSTGRES_PASSWORD 和 SECRET_KEY
```

应用启动时会自动读取项目根目录下的 `.env`。

如果你不想使用 `.env`，也可以在启动前手动加载环境变量（任选一种方式）：

方式 A（推荐，一次性加载当前终端）：

```bash
set -a
source .env
set +a
```

方式 B（单命令启动时注入）：

```bash
env $(grep -v '^#' .env | xargs) python app.py
```

### 3) 启动应用

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```


打开浏览器访问：

- 扫码页：`http://127.0.0.1:5000/`
- 后台页：`http://127.0.0.1:5000/admin`

## API/页面说明

- `/`：生成一次扫码会话并显示二维码。
- `/qr/<token>.png`：返回二维码图片。
- `/wechat/mock_scan?token=xxx&openid=wx_openid_zhangsan`：模拟微信扫码回调。
- `/profile/<token>`：填写用户个人信息。
- `POST /checkin/<token>`：确认签到。
- `/admin/login`：后台登录。
- `/admin`：后台查询。
- `/admin/export`：导出 Excel。
- `/admin/accounts`：管理员账号管理。

## 数据库表

- `users`：用户身份信息（姓名、身份证号、工区、累计签到天数）。
- `scan_sessions`：扫码会话信息。
- `checkins`：签到明细（用户+签到时间）。
- `admin_users`：后台账号信息（角色、密码散列、启停状态）。
