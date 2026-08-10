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
COPY src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/build-receipt.json /workspace/src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/build-receipt.json
COPY src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/browser-trace-macos-arm64.json /workspace/src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/browser-trace-macos-arm64.json
COPY src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/candidate-binding.json /workspace/src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311/candidate-binding.json
COPY src/pipeline/evidence/ar6-regional-release/owner-promotion/checksums.txt /workspace/src/pipeline/evidence/ar6-regional-release/owner-promotion/checksums.txt
COPY src/pipeline/evidence/ar6-regional-release/owner-promotion/final-gate.json /workspace/src/pipeline/evidence/ar6-regional-release/owner-promotion/final-gate.json
COPY src/pipeline/evidence/ar6-regional-release/owner-promotion/integration-merge.json /workspace/src/pipeline/evidence/ar6-regional-release/owner-promotion/integration-merge.json
COPY src/pipeline/evidence/ar6-regional-release/owner-promotion/owner-attestation.json /workspace/src/pipeline/evidence/ar6-regional-release/owner-promotion/owner-attestation.json
COPY src/pipeline/evidence/ar6-regional-release/owner-promotion/promotion.json /workspace/src/pipeline/evidence/ar6-regional-release/owner-promotion/promotion.json
COPY src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json /workspace/src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json
COPY src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz /workspace/src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz
COPY src/pipeline/offline_release /workspace/src/pipeline/offline_release
COPY src/pipeline/requirements-release.lock /workspace/src/pipeline/requirements-release.lock
COPY src/pipeline/science/ar6-lookup-validation.json /workspace/src/pipeline/science/ar6-lookup-validation.json
COPY src/pipeline/science/ar6-regional-release.json /workspace/src/pipeline/science/ar6-regional-release.json
COPY src/pipeline/science/ar6-regional-release.schema.json /workspace/src/pipeline/science/ar6-regional-release.schema.json
COPY src/pipeline/science/evidence/ar6-lookup-goldens.json /workspace/src/pipeline/science/evidence/ar6-lookup-goldens.json
COPY src/pipeline/searise_pipeline /workspace/src/pipeline/searise_pipeline

USER 65532:65532

ENTRYPOINT ["python", "-m", "searise_pipeline.offline_release.cli"]
