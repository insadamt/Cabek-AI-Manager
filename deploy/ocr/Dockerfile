# Run CPU OCR independently of the inspection API; depends on persistent model/output mounts.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt
COPY . .
EXPOSE 8002
CMD ["uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8002", "--workers", "1"]
