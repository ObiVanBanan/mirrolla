FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /sandbox

RUN useradd --create-home --uid 10001 worker

COPY deploy/analysis-sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

USER worker

CMD ["python", "--version"]
