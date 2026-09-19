FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# WITH_ML=0 — образ без нейросети (DETECTOR=mock/none), собирается за минуту
ARG WITH_ML=1
RUN if [ "$WITH_ML" = "1" ]; then \
      pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir -r requirements-ml.txt ; \
    fi

COPY . .

# Скачать веса YOLO-World и CLIP на этапе сборки, чтобы сервис стартовал без интернета
ARG PRELOAD_MODEL=1
RUN if [ "$WITH_ML" = "1" ] && [ "$PRELOAD_MODEL" = "1" ]; then python scripts/preload_model.py ; fi

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
