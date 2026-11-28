# Requiem service, bootstrap and load generator share this image (all need only httpx + pyyaml).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements-requiem.txt deploy/requirements-requiem.txt
RUN pip install -r deploy/requirements-requiem.txt
COPY requiem requiem
COPY demo demo
COPY loadgen loadgen
COPY deploy/bootstrap.py deploy/with-env.sh deploy/
COPY requiem.yaml requiem.yaml
RUN useradd --uid 10001 --create-home requiem \
    && mkdir -p /app/incidents /shared \
    && sed -i 's/\r$//' deploy/with-env.sh && chmod +x deploy/with-env.sh \
    && chown -R requiem /app /shared
USER requiem
CMD ["python", "-m", "requiem.service", "run"]
