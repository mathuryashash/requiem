# Demo shop (FastAPI + Flagsmith SDK + OpenTelemetry).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements-shop.txt deploy/requirements-shop.txt
RUN pip install -r deploy/requirements-shop.txt
COPY shop shop
COPY deploy/with-env.sh deploy/with-env.sh
RUN useradd --uid 10001 --create-home shop && sed -i 's/\r$//' deploy/with-env.sh && chmod +x deploy/with-env.sh
USER shop
EXPOSE 8090
ENTRYPOINT ["/app/deploy/with-env.sh"]
CMD ["uvicorn", "shop.app:app", "--host", "0.0.0.0", "--port", "8090"]
