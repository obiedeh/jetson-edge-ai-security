#!/usr/bin/env bash
# Edge IDS — Jetson AGX Thor install / upgrade script
#
# Usage:
#   sudo bash deploy/thor/install.sh [--upgrade]
#
# What it does:
#   1. Creates the edge-ids system user and directories
#   2. Copies application files to /opt/edge-ids
#   3. Creates a Python virtualenv and installs dependencies
#   4. Installs and enables the systemd service
#   5. Optionally builds TensorRT engines
#
# Requirements:
#   - JetPack 6.x (aarch64)
#   - Python 3.10+
#   - Git (for determining install source)

set -euo pipefail

INSTALL_DIR=/opt/edge-ids
DATA_DIR=/var/lib/edge-ids
SERVICE_NAME=edge-security
SERVICE_FILE=deploy/thor/edge-security.service
UPGRADE=${1:-""}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

log() { echo "[edge-ids install] $*"; }
error() { echo "[edge-ids install] ERROR: $*" >&2; exit 1; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (sudo)."
    fi
}

require_root

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

log "Install directory: $INSTALL_DIR"
log "Data directory:    $DATA_DIR"
log "Repo source:       $REPO_DIR"

# ──────────────────────────────────────────────────────────────────────────────
# 1. System user
# ──────────────────────────────────────────────────────────────────────────────

if ! id -u edge-ids &>/dev/null; then
    log "Creating system user 'edge-ids'"
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --groups video,render edge-ids
else
    log "User 'edge-ids' already exists"
fi

# ──────────────────────────────────────────────────────────────────────────────
# 2. Directories
# ──────────────────────────────────────────────────────────────────────────────

for d in "$DATA_DIR/data" "$DATA_DIR/reports" "$DATA_DIR/artifacts"; do
    mkdir -p "$d"
    chown edge-ids:edge-ids "$d"
done

# ──────────────────────────────────────────────────────────────────────────────
# 3. Copy application files
# ──────────────────────────────────────────────────────────────────────────────

log "Copying application to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

rsync -a --delete \
    "$REPO_DIR/src/" "$INSTALL_DIR/src/" \
    --exclude "__pycache__" --exclude "*.pyc"

rsync -a \
    "$REPO_DIR/configs/" "$INSTALL_DIR/configs/" \
    "$REPO_DIR/models/exports/" "$INSTALL_DIR/models/exports/" \
    "$REPO_DIR/reports/" "$INSTALL_DIR/reports/"

# Web dashboard static build
if [[ -d "$REPO_DIR/web/dist" ]]; then
    rsync -a "$REPO_DIR/web/dist/" "$INSTALL_DIR/web/dist/"
    log "Web dashboard installed."
else
    log "WARNING: web/dist not found — run 'pnpm build' in web/ first."
fi

# pyproject.toml for pip install
cp "$REPO_DIR/pyproject.toml" "$INSTALL_DIR/"

chown -R edge-ids:edge-ids "$INSTALL_DIR"

# ──────────────────────────────────────────────────────────────────────────────
# 4. Python virtualenv
# ──────────────────────────────────────────────────────────────────────────────

VENV="$INSTALL_DIR/.venv"
PYTHON="$(which python3)"

if [[ ! -d "$VENV" ]] || [[ "$UPGRADE" == "--upgrade" ]]; then
    log "Creating Python virtualenv at $VENV"
    "$PYTHON" -m venv "$VENV"
fi

log "Installing Python dependencies"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet \
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

"$VENV/bin/pip" install --quiet -e "$INSTALL_DIR"

chown -R edge-ids:edge-ids "$VENV"

# ──────────────────────────────────────────────────────────────────────────────
# 5. Systemd service
# ──────────────────────────────────────────────────────────────────────────────

log "Installing systemd service"
cp "$REPO_DIR/$SERVICE_FILE" "/etc/systemd/system/$SERVICE_NAME.service"
chmod 644 "/etc/systemd/system/$SERVICE_NAME.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

log "Service status:"
systemctl status "$SERVICE_NAME" --no-pager --lines=5 || true

# ──────────────────────────────────────────────────────────────────────────────
# 6. Optional: TensorRT engine build
# ──────────────────────────────────────────────────────────────────────────────

if "$VENV/bin/python3" -c "import tensorrt" 2>/dev/null; then
    log "TensorRT available — building engines"
    "$VENV/bin/python3" "$REPO_DIR/deploy/thor/build_tensorrt_engines.py" \
        --models-dir "$INSTALL_DIR/models/exports" \
        --fp16
else
    log "TensorRT not available — skipping engine build."
    log "Run 'pip install tensorrt' and re-run install.sh to build engines."
fi

log ""
log "Installation complete."
log "  Dashboard: http://localhost:8080"
log "  Logs:      journalctl -fu $SERVICE_NAME"
log "  Benchmark: python3 deploy/thor/run_benchmark.py"
