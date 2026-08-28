ARG BASE_IMAGE=PYTHON_BASE_IMAGE_DIGEST_REQUIRED
FROM ${BASE_IMAGE}

ARG HARNESS_VERSION
ARG HARNESS_SOURCE_REVISION
LABEL data.harness.component="data-source-harness" \
      data.harness.version="${HARNESS_VERSION}" \
      data.harness.source-revision="${HARNESS_SOURCE_REVISION}" \
      data.harness.network-boundary="compose-internal"

WORKDIR /opt/data-source-harness
COPY dist/live-wheelhouse/ /opt/data-source-harness/wheels/
COPY dist/orchestra_data_source_harness-*.whl /opt/data-source-harness/wheels/
RUN python -m pip install --no-cache-dir --no-index \
      --find-links=/opt/data-source-harness/wheels \
      "orchestra-data-source-harness==${HARNESS_VERSION}" \
      boto3==1.43.82 \
      kafka-python-ng==2.2.3 \
      psycopg==3.2.13 \
      psycopg-binary==3.2.13 \
      python-snappy==0.7.3 \
    && python -m pip check \
    && rm -rf /opt/data-source-harness/wheels

COPY reference_labs/ /opt/data-source-harness/reference_labs/
ENV PYTHONPATH=/opt/data-source-harness \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 1001
ENTRYPOINT ["python", "-m", "reference_labs.white_goods.live.harness_probe"]
