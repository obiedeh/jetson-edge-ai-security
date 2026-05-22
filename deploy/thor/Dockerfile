# Edge IDS — Jetson AGX Thor deployment image
#
# Build context: repo root
# Target: NVIDIA Jetson AGX Thor (aarch64, JetPack 6.x, TensorRT 10.x)
#
# Build:
#   docker build -f deploy/thor/Dockerfile -t edge-ids:latest .
#
# Run (with GPU access):
#   docker run --rm --runtime nvidia -p 8080:8080 edge-ids:latest
#
# The image bundles:
#   - Python runtime + FastAPI backend
#   - Trained ONNX models (gbm_detector.onnx, ar_forecaster.onnx)
#   - Web dashboard static build (web/dist/)
#   - TensorRT engine builder (run once on first boot)

FROM nvcr.io/nvidia/l4t-tensorrt:r10.3-aarch64 AS base

# ──────────────────────────────────────────────────────────────────────────────
# System packages
# ──────────────────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ──────────────────────────────────────────────────────────────────────────────
# Python dependencies (CPU-only onnxruntime for x86 dev; CUDA for Thor)
# ──────────────────────────────────────────────────────────────────────────────
COPY pyproject.toml ./
RUN pip3 install --no-cache-dir \
    "pydantic>=2.7" \
    "typer>=0.12" \
    "rich>=13.7" \
    "PyYAML>=6.0" \
    "numpy>=1.24" \
    "pandas>=2.0" \
    "onnx>=1.15" \
    "onnxruntime-gpu>=1.17" \
    "dpkt>=1.9" \
    "fastapi>=0.111" \
    "uvicorn[standard]>=0.29" \
    "sse-starlette>=2.1" \
    "aiosqlite>=0.20" \
    "scikit-learn>=1.4"

# ──────────────────────────────────────────────────────────────────────────────
# Application source
# ──────────────────────────────────────────────────────────────────────────────
COPY src/ ./src/
COPY configs/ ./configs/
COPY models/exports/ ./models/exports/
COPY reports/ ./reports/

# Web dashboard static build (from CI)
COPY web/dist/ ./web/dist/

# Deployment scripts
COPY deploy/thor/ ./deploy/thor/

# ──────────────────────────────────────────────────────────────────────────────
# Install package
# ──────────────────────────────────────────────────────────────────────────────
RUN pip3 install --no-cache-dir -e .

# ──────────────────────────────────────────────────────────────────────────────
# Environment
# ──────────────────────────────────────────────────────────────────────────────
ENV EDGE_IDS_DATA_DIR=/app/data \
    EDGE_IDS_REPORTS_DIR=/app/reports \
    EDGE_IDS_ARTIFACTS_DIR=/app/artifacts \
    EDGE_IDS_MODELS_DIR=/app/models/exports \
    EDGE_IDS_CONFIG=/app/configs/default.yaml \
    PYTHONPATH=/app/src

VOLUME ["/app/data", "/app/artifacts"]

EXPOSE 8080

# ──────────────────────────────────────────────────────────────────────────────
# Entry point — FastAPI backend serving both API and static web assets
# ──────────────────────────────────────────────────────────────────────────────
CMD ["uvicorn", "jetson_edge_ai_security.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
