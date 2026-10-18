FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY truthnews ./truthnews
RUN pip install -e .

# El mismo contenedor arranca la web o el worker segun TRUTHNEWS_ROLE (web | worker | all).
COPY bin/start ./bin/start
RUN chmod +x bin/start
CMD ["bin/start"]
