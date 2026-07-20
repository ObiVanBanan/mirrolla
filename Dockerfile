FROM python:3.12-slim

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код проекта
COPY agent/ ./agent/
COPY api/ ./api/
COPY client/ ./client/
COPY helpers/ ./helpers/
COPY reports/ ./reports/
COPY ui/ ./ui/
# data/ монтируется через volume в compose.yaml.
# Создаём только директории — без пустых файлов-заглушек.
RUN mkdir -p ./data/prepared ./data/charts

# ENV
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health', timeout=3)" || exit 1

# Non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Запуск API
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]