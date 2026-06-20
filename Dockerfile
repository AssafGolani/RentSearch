FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persisted SQLite lives here; mount a volume to keep data across restarts.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "main.py"]
