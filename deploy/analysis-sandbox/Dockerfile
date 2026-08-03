FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /workspace

RUN useradd --create-home --uid 10001 sandbox

COPY deploy/analysis-sandbox/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

USER sandbox

CMD ["python", "--version"]
