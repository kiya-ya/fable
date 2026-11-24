FROM docker.m.daocloud.io/library/python:3.11-slim

# 中国时区（奖励窗口/每周刷新都按本地周界计算）+ opencv（ddddocr 依赖）系统库
ENV TZ=Asia/Shanghai
# 国内镜像源加速（默认源在国内拉取极慢）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends tzdata libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY .wheelhouse /wheelhouse
RUN --mount=type=cache,target=/root/.cache/pip sh -c '\
    if [ -f /wheelhouse/ddddocr-1.6.1-py3-none-any.whl ]; then \
        pip install --no-index --no-deps --find-links=/wheelhouse ddddocr==1.6.1 numpy==2.4.6 onnxruntime==1.32.0 opencv-python-headless==5.1.0.95; \
    fi; \
    pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/'

COPY crawler/ crawler/
COPY backend/ backend/

# 数据库与 Cookie 通过卷挂载提供（勿打进镜像）
RUN mkdir -p data

EXPOSE 5000

# 容器内监听 0.0.0.0 供宿主机访问
ENV FLASK_HOST=0.0.0.0

CMD ["python", "-X", "utf8", "backend/app.py"]
