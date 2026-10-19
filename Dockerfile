FROM python:3.11-slim

# Gunicorn binds on 0.0.0.0 inside the container so published ports work.
# Anyone who can reach that port can generate and run Python as the container user.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5050

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir . gunicorn

EXPOSE 5050

CMD ["gunicorn", "--workers", "2", "--timeout", "180", "--bind", "0.0.0.0:5050", "workflowmvp.app:app"]
