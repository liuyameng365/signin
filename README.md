# 微信扫码签到系统（Flask）

这是一个使用 Python + Flask 实现的签到系统示例，支持：

- 访问签到页面生成二维码。
- 微信扫码（演示中使用 `mock_scan` 模拟微信身份回调）并展示身份信息。
- 用户点击确认签到后，将签到信息写入数据库（默认 PostgreSQL）。
- 后台管理页按姓名 / 身份证号 / 工区查询签到记录。
- 支持导出 Excel。

> 说明：真实微信身份获取需要接入微信 OAuth/企业微信 API。本项目中 `GET /wechat/mock_scan` 是演示接口。

## 运行方式

### 1) 准备 PostgreSQL 数据库（默认）

先用 `postgres` 超级用户登录：

```bash
psql -U postgres -h 127.0.0.1 -p 5432
```

在 `psql` 里执行（创建专用用户 + 数据库 + 授权）：

```sql
CREATE USER signin_user WITH PASSWORD 'your_strong_password';
CREATE DATABASE signin OWNER signin_user;
GRANT ALL PRIVILEGES ON DATABASE signin TO signin_user;
```

退出：

```sql
\q
```

如果你更习惯单行命令（不进 `psql` 交互），也可以：

```bash
psql -U postgres -h 127.0.0.1 -p 5432 -c "CREATE USER signin_user WITH PASSWORD 'your_strong_password';"
psql -U postgres -h 127.0.0.1 -p 5432 -c "CREATE DATABASE signin OWNER signin_user;"
psql -U postgres -h 127.0.0.1 -p 5432 -c "GRANT ALL PRIVILEGES ON DATABASE signin TO signin_user;"
```

设置环境变量（推荐）：

```bash
export POSTGRES_HOST=127.0.0.1
export POSTGRES_PORT=5432
export POSTGRES_USER=signin_user
export POSTGRES_PASSWORD=your_strong_password
# 或者使用 PGPASSWORD=your_strong_password
export POSTGRES_DB=signin
export SECRET_KEY=请替换为随机字符串
```

> 也可以直接设置 `DATABASE_URL`：
>
> `postgresql+psycopg2://signin_user:your_strong_password@127.0.0.1:5432/signin`

首次启动时，应用会自动执行 `db.create_all()` 创建 `users` / `scan_sessions` / `checkins` 三张表。

### 2) 使用 `.env.example` 生成本地配置

```bash
cp .env.example .env
# 按你的环境修改 .env，至少要改 POSTGRES_PASSWORD 和 SECRET_KEY
```

你可以在启动前加载环境变量（任选一种方式）：

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

### 4) 使用 Nginx 反向代理（部署测试）

建议先让 Flask 应用监听本机回环地址（例如 `127.0.0.1:5000`），再由 Nginx 对外暴露 80/443 端口。

`/etc/nginx/conf.d/signin.conf` 示例：

```nginx
upstream signin_app {
    server 127.0.0.1:5000;
    keepalive 32;
}

server {
    listen 80;
    server_name your-domain.com;  # 本地测试可改为服务器IP或 _

    client_max_body_size 20m;

    location / {
        proxy_pass http://signin_app;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

应用配置并重载 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

如果你希望应用作为后台服务运行，可用 `gunicorn + systemd`：

```bash
# 安装 gunicorn
pip install gunicorn

# 启动示例（在项目根目录）
gunicorn -w 2 -b 127.0.0.1:5000 app:app
```

`/etc/systemd/system/signin.service` 示例：

```ini
[Unit]
Description=Signin Flask Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/workspace/signin
EnvironmentFile=/workspace/signin/.env
ExecStart=/workspace/signin/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now signin
sudo systemctl status signin
```

> 如需 HTTPS，可使用 certbot 自动签发证书：
>
> `sudo certbot --nginx -d your-domain.com`

### 5) 常见启动报错排查

如果报错：

```text
psycopg2.OperationalError: ... fe_sendauth: no password supplied
```

通常是应用进程没有拿到数据库密码。按下面顺序检查：

1. 确认环境变量是否存在（至少其一）：

```bash
echo "$POSTGRES_PASSWORD"
echo "$PGPASSWORD"
```

2. 若使用 `.env`，确认已加载到当前 shell：

```bash
set -a
source .env
set +a
```

3. 若使用 systemd，确认服务文件包含并可读取环境文件：

```ini
EnvironmentFile=/workspace/signin/.env
```

并重启服务：

```bash
sudo systemctl daemon-reload
sudo systemctl restart signin
sudo systemctl status signin
```

4. 直接用 `psql` 验证账号密码是否正确：

```bash
psql -h 127.0.0.1 -p 5432 -U signin_user -d signin -W
```

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
