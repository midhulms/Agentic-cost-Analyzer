# Author: Cryzal & Midhul
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY dashboard.py .
COPY static ./static

EXPOSE 8000
# Shell form (not exec-array) so ${PORT} actually expands. Falls back to
# 8000 locally; picks up whatever port a host like Render assigns via $PORT.
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
