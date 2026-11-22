# Package a standalone Cabek HTTP service; depends on its requirements file.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements-lighting.txt /app/requirements.txt
RUN pip install -r requirements.txt
COPY . .
EXPOSE 9001
CMD ["python", "-m", "lighting_api", "--port", "9001"]
