# 微信公众号矩阵管理系统 —— 后端镜像(api / worker / beat 共用)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 系统依赖:aiomysql/cryptography 运行期无需编译;仅装 tzdata + curl(healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# 默认启动 API;worker/beat 由 docker-compose 覆盖 command(M2+)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
