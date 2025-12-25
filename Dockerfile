FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_HOME="/opt/poetry"

ENV PATH="$POETRY_HOME/bin:$PATH"

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    gdal-bin \
    libgdal-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Ustawiamy zmienne, aby kompilator wiedział gdzie szukać nagłówków GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app

COPY pyproject.toml ./

# --- Dodatkowa flaga -v (verbose) pomoże w debugowaniu jeśli coś znowu padnie ---
RUN poetry install --no-root --only main

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]