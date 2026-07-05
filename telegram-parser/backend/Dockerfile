FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic ./alembic
COPY alembic.ini .
COPY app ./app

CMD ["celery", "-A", "app.core.celery_app:celery_app", "worker", "--loglevel=info", "-Q", "main-queue"]
