FROM python:3.11.15-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=/workspace/src/pipeline \
    TZ=UTC

WORKDIR /workspace

COPY src/pipeline/requirements-release.lock /tmp/requirements-release.lock
RUN python -m pip install \
    --only-binary=:all: \
    --require-hashes \
    --requirement /tmp/requirements-release.lock

COPY contracts/release/v1 /workspace/contracts/release/v1
COPY src/pipeline/offline_release /workspace/src/pipeline/offline_release
COPY src/pipeline/requirements-release.lock /workspace/src/pipeline/requirements-release.lock
COPY src/pipeline/searise_pipeline /workspace/src/pipeline/searise_pipeline

USER 65532:65532

ENTRYPOINT ["python", "-m", "searise_pipeline.offline_release.cli"]
