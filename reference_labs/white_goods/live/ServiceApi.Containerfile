ARG BASE_IMAGE=PYTHON_BASE_IMAGE_REQUIRED
FROM ${BASE_IMAGE}

WORKDIR /opt/white-goods-service-api
COPY reference_labs/white_goods/live/service_api.py ./service_api.py
COPY reference_labs/white_goods/data/api/service-api-fixtures.json ./fixtures.json

USER 65532
ENTRYPOINT ["python", "/opt/white-goods-service-api/service_api.py"]
