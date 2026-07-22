# Serving image for src/electricity_demand/serving/app.py - the live-request
# serving API, and the serving_container_image_uri register_model needs.
# Deliberately smaller than the root Dockerfile: no dbt, just what app.py
# needs to load a model, query BigQuery for the /series /history /forecast
# routes, and serve predictions.
#
# Build (from the repo root, since this needs pyproject.toml/src as build context):
#   docker build -f docker/serving.Dockerfile \
#     -t <region>-docker.pkg.dev/<project>/electricity-demand/serving:latest .
#   docker push <region>-docker.pkg.dev/<project>/electricity-demand/serving:latest

FROM python:3.11-slim

WORKDIR /app

# libgomp1: LightGBM's compiled library dlopen()s libgomp.so.1 (OpenMP) at
# import time - python:3.11-slim doesn't include it, so `import lightgbm`
# fails with "libgomp.so.1: cannot open shared object file" without this.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[ml,serving,gcp]"

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "electricity_demand.serving.app:app", "--host", "0.0.0.0", "--port", "8080"]
