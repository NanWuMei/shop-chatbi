# ChatBI api 镜像（FR-23 / B28）：python:3.12-slim 单阶段；构建上下文为仓库根，同装 api/ 与 algorithm/。
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 先拷 requirements 利用层缓存
COPY algorithm/requirements.txt /app/algorithm/requirements.txt
COPY backend_service/requirements.txt /app/backend_service/requirements.txt
RUN pip install -r /app/backend_service/requirements.txt

COPY algorithm/ /app/algorithm/
COPY backend_service/ /app/backend_service/

EXPOSE 8000
# uvicorn 单 worker（NFR-4 单进程假设：turn 注册表/事件缓冲/checkpointer 均进程内存）
# 端口取 $PORT（Render 等 PaaS 注入，默认 10000），本地/Compose 未注入时回落 8000
CMD ["sh", "-c", "uvicorn backend_service.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
