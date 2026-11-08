# syntax=docker/dockerfile:1
FROM python:{{ python_version }}-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT={{ port }}

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

{% if dependency_manager == 'poetry' %}
COPY pyproject.toml poetry.lock* ./
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction
{% elif dependency_manager == 'pipenv' %}
COPY Pipfile Pipfile.lock* ./
RUN pip install --no-cache-dir pipenv \
    && pipenv install --system --deploy
{% elif dependency_manager == 'pyproject' %}
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
{% elif dependency_manager == 'pip' or has_requirements_file %}
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
{% elif dependency_manager == 'setup' %}
COPY setup.py setup.cfg* ./
RUN pip install --no-cache-dir .
{% endif %}

COPY . .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE {{ port }}

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:{{ port }}{{ health_check_path }} || exit 1

CMD {{ start_command_exec }}
