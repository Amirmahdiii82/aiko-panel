FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Tehran HOST=0.0.0.0 PORT=8020 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --home /app aiko && mkdir -p /app/data && chown aiko:aiko /app/data
USER aiko
VOLUME ["/app/data"]
EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8020/healthz')"
# one worker on purpose: SQLite + in-process scheduler and live events (see app/core/jobs.py)
CMD ["python", "-m", "app", "serve"]
