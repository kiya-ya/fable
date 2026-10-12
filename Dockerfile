FROM python:3.11-slim

# 中国时区（奖励窗口/每周刷新都按本地周界计算）+ opencv（ddddocr 依赖）系统库
ENV TZ=Asia/Shanghai
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY crawler/ crawler/
COPY backend/ backend/

# 数据库与 Cookie 通过卷挂载提供（勿打进镜像）
RUN mkdir -p data

EXPOSE 5000

# 容器内监听 0.0.0.0 供宿主机访问
ENV FLASK_HOST=0.0.0.0

CMD ["python", "-X", "utf8", "backend/app.py"]
