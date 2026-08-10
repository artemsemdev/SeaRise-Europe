FROM python:3.11.15-bookworm@sha256:a8f8fbe1a0edc9e4dddafa64ba73f7e04be7be5ebc23f332362e779e0a2e4e52

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
