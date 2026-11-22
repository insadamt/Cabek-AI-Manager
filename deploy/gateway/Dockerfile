# Run Manager-owned HTTP admission control; depends only on Manager requirements.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /manager
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY manager ./manager
EXPOSE 8008
CMD ["uvicorn", "manager.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8008", "--workers", "1"]
