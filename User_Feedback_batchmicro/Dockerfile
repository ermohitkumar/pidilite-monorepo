FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gcc \
    libpq-dev \
    curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install poetry==2.3.4

# Point Python / requests / curl at the system CA bundle so GCS HTTPS
# verifies correctly inside the Cloud Run container.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

COPY pyproject.toml poetry.lock* ./

RUN poetry install --no-root

COPY . .

# Run as non-root user for defence in depth
RUN useradd --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

CMD ["poetry", "run", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
