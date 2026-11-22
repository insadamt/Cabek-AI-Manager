# Run the real Cabek API and inference worker; depends on CPU PyTorch and packaged models.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 YOLO_CONFIG_DIR=/tmp/ultralytics MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY --from=deployment backend/requirements-api.txt backend/requirements-scan.txt ./
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements-scan.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "api", "--port", "8000"]
