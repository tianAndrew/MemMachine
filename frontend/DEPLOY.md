# 部署 MemMachine 前端到服务器

本文说明如何把 MemMachine API + 前端一起部署到一台服务器上，供外网访问。

## 一、架构

- **MemMachine API**：提供记忆的增删改查，默认端口 8080（可改）。
- **前端服务**：提供网页 UI、代理 API 请求、上传图片与本地图片访问，默认端口 7000。
- 用户浏览器只访问**前端服务**；前端再请求 MemMachine API。上传的图片保存在服务器指定目录。

## 二、服务器准备

1. **系统**：Linux（Ubuntu / Debian / CentOS 等）。
2. **Python**：3.12+，建议用 [uv](https://github.com/astral-sh/uv) 或 pip 安装依赖。
3. **MemMachine 依赖**：若用 PostgreSQL / Neo4j，需先安装并配置好（见项目根目录 `configuration.yml` 和文档）。

## 三、部署步骤

### 1. 上传代码并安装依赖

```bash
# 在服务器上克隆或上传项目
cd /opt  # 或你希望的目录
git clone https://github.com/MemMachine/MemMachine.git
cd MemMachine

# 安装依赖（二选一）
uv sync
# 或
pip install -e .
```

### 2. 配置文件

在项目根目录放置 `configuration.yml`（可从 `sample_configs/` 复制并改），配置好数据库、embedder、LLM 等。写文章功能会从该配置里读 LLM 的 base_url 和 api_key（也可用环境变量覆盖）。

### 3. 图片存储目录（建议单独目录）

```bash
sudo mkdir -p /var/lib/memmachine-images
sudo chown "$(whoami)" /var/lib/memmachine-images
```

部署时把前端的「图片根目录」指到这里，上传的图片会存到 `/var/lib/memmachine-images/memmachine_uploads/`。

### 4. 启动 MemMachine API

```bash
cd /opt/MemMachine
export PYTHONPATH="${PWD}/src${PYTHONPATH:+:${PYTHONPATH}}"
# 若用 uv：uv run memmachine-server 或：
python -m memmachine.server.app --host 0.0.0.0 --port 8080
```

确保监听 `0.0.0.0` 以便本机其他进程（前端）能访问。若 8080 被占用可改端口，并相应设置下面的 `MEMMACHINE_BASE_URL`。

### 5. 启动前端服务

另开一个终端或后台进程：

```bash
cd /opt/MemMachine

export MEMMACHINE_BASE_URL=http://127.0.0.1:8080
export MEMMACHINE_FRONTEND_IMAGE_ROOT=/var/lib/memmachine-images
# 可选：若不用 configuration.yml 的 LLM，可设：
# export OPENAI_API_BASE=...
# export OPENAI_API_KEY=...
# export MEMMACHINE_CONFIG_PATH=/opt/MemMachine/configuration.yml

uv run python frontend/server.py
# 或：python frontend/server.py（需已安装依赖）
```

前端默认监听 `127.0.0.1:7000`。若希望本机其他网卡也能访问，可改 `frontend/server.py` 里 `uvicorn.run(..., host="0.0.0.0")`，或通过下面的 Nginx 反代对外暴露。

### 6. 用 systemd 常驻（推荐）

**MemMachine API**（`/etc/systemd/system/memmachine-api.service`）：

```ini
[Unit]
Description=MemMachine API
After=network.target postgresql.service

[Service]
Type=simple
User=memmachine
WorkingDirectory=/opt/MemMachine
Environment=PYTHONPATH=/opt/MemMachine/src
ExecStart=/opt/MemMachine/.venv/bin/python -m memmachine.server.app --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**前端**（`/etc/systemd/system/memmachine-frontend.service`）：

```ini
[Unit]
Description=MemMachine Frontend
After=network.target memmachine-api.service

[Service]
Type=simple
User=memmachine
WorkingDirectory=/opt/MemMachine
Environment=MEMMACHINE_BASE_URL=http://127.0.0.1:8080
Environment=MEMMACHINE_FRONTEND_IMAGE_ROOT=/var/lib/memmachine-images
ExecStart=/opt/MemMachine/.venv/bin/python frontend/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

注意：`ExecStart` 里的 Python 路径请按你实际环境改（如 `uv run python frontend/server.py` 需写全路径或用 wrapper 脚本）。然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable memmachine-api memmachine-frontend
sudo systemctl start memmachine-api memmachine-frontend
sudo systemctl status memmachine-api memmachine-frontend
```

### 7. 用 Nginx 做反向代理（可选，推荐用于 HTTPS）

只对外暴露 80/443，由 Nginx 把请求转到前端（再转 API）：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

配置 HTTPS 可用 `certbot` 等申请证书并改 `listen 443 ssl`。重载 Nginx 后，用户通过 `http(s)://your-domain.com` 访问即可。

## 四、环境变量汇总（前端）

| 变量 | 说明 | 默认 |
|------|------|------|
| MEMMACHINE_BASE_URL | MemMachine API 地址 | http://127.0.0.1:8080 |
| MEMMACHINE_FRONTEND_IMAGE_ROOT | 图片根目录（上传与 /local-image 读取） | 当前用户 $HOME |
| MEMMACHINE_CONFIG_PATH | configuration.yml 路径（用于读 LLM） | 自动找项目根 |
| WRITE_ARTICLE_MODEL | 写文章用的 language_models 中的模型 id | 第一个 openai-chat-completions |
| OPENAI_API_BASE / OPENAI_API_KEY / OPENAI_MODEL | 未从 config 读到 LLM 时使用 | - |

## 五、安全建议

- MemMachine API 只监听 `127.0.0.1:8080`，不直接对外。
- 前端若监听 `0.0.0.0`，前面务必用 Nginx（或其它反代）做 HTTPS 和限流。
- `MEMMACHINE_FRONTEND_IMAGE_ROOT` 不要设成 `/` 等过大目录，避免 `/local-image` 被滥用读任意文件。
- 生产环境不要在前端或 config 里写死 API Key；用环境变量或密钥管理。

## 六、数据库连接被拒 (Connection refused)

若 MemMachine 启动报错 `Connect call failed ('127.0.0.1', 5432)`：

1. **configuration.yml 里用 127.0.0.1**：Postgres 的 `host` 和 Neo4j 的 `uri` 写成 `127.0.0.1`，不要用 `localhost`（避免解析成 IPv6 `::1` 连不上）。
2. **确认容器已启动且健康**：`docker ps` 里 postgres/neo4j 为 `Up` 且 `(healthy)`。刚 `up -d` 后等十几秒再起 MemMachine。
3. **本机测端口**：`nc -zv 127.0.0.1 5432` 或 `pg_isready -h 127.0.0.1 -p 5432 -U memmachine`，能通则说明端口可达。

## 七、验证

- 浏览器访问：`http://服务器IP:7000`（或你配置的域名）。
- 在 Memories 里能列表/搜索、上传图片、看到缩略图。
- 在 Write Article 里输入主题能生成文章且文中图片能加载，即说明部署正常。
