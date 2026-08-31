FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install poetry==2.3.4

ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

COPY pyproject.toml poetry.lock* ./

RUN poetry install --no-root

COPY . .

# Run as non-root user for defence in depth
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

CMD ["poetry", "run", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]