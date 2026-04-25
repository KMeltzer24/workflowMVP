FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=127.0.0.1 \
    PORT=5050

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

EXPOSE 5050

CMD ["gunicorn", "--workers", "2", "--timeout", "180", "--bind", "127.0.0.1:5050", "workflowmvp.app:app"]
