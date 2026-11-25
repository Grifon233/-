FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/courier-dashboard

RUN groupadd --system courier \
    && useradd --system --gid courier --no-create-home courier \
    && install -d -o courier -g courier -m 0750 /data

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/app ./backend/app
COPY miniapp/index.html ./miniapp/index.html
COPY miniapp/css/ ./miniapp/css/
COPY miniapp/js/ ./miniapp/js/
COPY miniapp/vendor/ ./miniapp/vendor/

USER courier
WORKDIR /srv/courier-dashboard/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
