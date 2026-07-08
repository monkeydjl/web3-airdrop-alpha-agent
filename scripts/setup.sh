#!/bin/bash
# ──────────────────────────────────────────────
# Setup Script — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 用法: bash scripts/setup.sh [--dev|--prod|--docker]
# 用途: 一键初始化开发/生产环境
# ──────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Web3 Airdrop Alpha Agent System — Setup"
echo "══════════════════════════════════════════"

# ── Parse arguments ──────────────────────────
MODE="${1:---dev}"

case "$MODE" in
  --dev)
    echo "📦 Mode: Development"
    ;;
  --prod)
    echo "📦 Mode: Production"
    ;;
  --docker)
    echo "📦 Mode: Docker"
    ;;
  *)
    echo "❌ Unknown mode: $MODE"
    echo "Usage: bash scripts/setup.sh [--dev|--prod|--docker]"
    exit 1
    ;;
esac

# ── Docker mode ──────────────────────────────
if [ "$MODE" = "--docker" ]; then
    echo ""
    echo "🐳 Starting Docker environment..."
    if [ -f docker-compose.yml ]; then
        docker compose up -d --build
    elif [ -f docker-compose.prod.yml ]; then
        docker compose -f docker-compose.prod.yml up -d --build
    else
        echo "❌ No docker-compose file found"
        exit 1
    fi
    echo ""
    echo "✅ Service started"
    echo "   Dashboard: http://localhost"
    echo "   API:       http://localhost/api/v1"
    echo "   Health:    http://localhost/health"
    exit 0
fi

# ── Local mode ───────────────────────────────
echo ""
echo "📋 Step 1/5: Check Python version"
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "❌ Python not found. Install Python 3.11+"
    exit 1
fi
PYTHON_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
echo "   Found Python $PYTHON_VERSION"
if [ "$MODE" = "--prod" ] && [ "$(echo "$PYTHON_VERSION < 3.11" | bc -l)" -eq 1 ]; then
    echo "❌ Production requires Python 3.11+"
    exit 1
fi

echo ""
echo "📋 Step 2/5: Create virtual environment"
if [ ! -d .venv ]; then
    $PYTHON -m venv .venv
    echo "   ✅ Created .venv/"
else
    echo "   ◻️ .venv/ already exists"
fi

# Activate
if [ -f .venv/Scripts/activate ]; then
    source .venv/Scripts/activate  # Windows
else
    source .venv/bin/activate       # Unix
fi
echo "   ✅ Virtual environment activated"

echo ""
echo "📋 Step 3/5: Install dependencies"
if [ -f backend/requirements.txt ]; then
    pip install --quiet --upgrade pip
    pip install --quiet -r backend/requirements.txt
    echo "   ✅ Dependencies installed"
else
    echo "   ⚠️ No backend/requirements.txt found"
fi

echo ""
echo "📋 Step 4/5: Setup environment"
if [ ! -f .env ] && [ -f .env.example ]; then
    cp .env.example .env
    echo "   ✅ Created .env from .env.example"
    echo "   ⚠️  Please edit .env with your configuration"
elif [ -f .env ]; then
    echo "   ◻️ .env already exists"
else
    echo "   ⚠️ No .env.example found, skipping"
fi

echo ""
echo "📋 Step 5/5: Create data directories"
mkdir -p data/cache backups logs
echo "   ✅ Data directories ready"

echo ""
echo "══════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""
echo "   Next steps:"
echo "   1. Edit .env with your API keys"
echo "   2. Run: python backend/run.py"
echo "   3. Open: http://localhost:8000"
echo ""
echo "   Or use Docker:"
echo "   bash scripts/setup.sh --docker"
echo "══════════════════════════════════════════"
