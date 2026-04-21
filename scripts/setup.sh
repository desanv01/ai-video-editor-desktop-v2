#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║  AI Video Editing Agent — Quick Start Setup              ║
# ║  Run this once to set up the development environment.    ║
# ╚══════════════════════════════════════════════════════════╝

set -e

echo ""
echo "🎬 AI Video Editing Agent — Quick Start"
echo "========================================"
echo ""

# ── Step 1: Check prerequisites ──
echo "[1/5] Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Install Docker Desktop: https://docker.com/products/docker-desktop"
    exit 1
fi
echo "  ✅ Docker found: $(docker --version | head -1)"

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not found."
    exit 1
fi
echo "  ✅ Docker Compose available"

# ── Step 2: Create .env from template ──
echo ""
echo "[2/5] Setting up environment..."

if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ✅ Created .env from .env.example"
    echo ""
    echo "  ⚠️  IMPORTANT: Edit .env and add your API keys:"
    echo "     - MISTRAL_API_KEY  (get from https://console.mistral.ai)"
    echo "     - DEEPSEEK_API_KEY (get from https://platform.deepseek.com)"
    echo "     - OPENAI_API_KEY   (get from https://platform.openai.com)"
    echo ""
    read -p "  Press Enter after you've added your API keys (or Ctrl+C to do it later)... "
else
    echo "  ✅ .env already exists"
fi

# ── Step 3: Create storage directories ──
echo ""
echo "[3/5] Creating storage directories..."

mkdir -p uploads
echo "  ✅ ./uploads/ created"

# ── Step 4: Start Docker services ──
echo ""
echo "[4/5] Starting Docker services..."

docker compose up -d --build

echo ""
echo "  Waiting for services to be healthy..."
sleep 10

# Check each service
echo ""
echo "  Service status:"

for service in aive-backend aive-db aive-qdrant aive-redis aive-n8n; do
    if docker ps --format '{{.Names}}' | grep -q "$service"; then
        echo "    ✅ $service — running"
    else
        echo "    ❌ $service — NOT running"
    fi
done

# ── Step 5: Run validation ──
echo ""
echo "[5/5] Running setup validation..."
echo ""

docker exec aive-backend python /app/../scripts/check_setup.py 2>/dev/null || {
    echo ""
    echo "  ⚠️  Validation script couldn't run inside container."
    echo "     You can run it manually:"
    echo "       docker exec aive-backend python scripts/check_setup.py"
}

echo ""
echo "========================================"
echo "🎬 Setup complete! Access points:"
echo ""
echo "  📡 Backend API:    http://localhost:8000/docs"
echo "  🔄 n8n Workflows:  http://localhost:5678 (admin/admin)"
echo "  🔍 Qdrant DB:      http://localhost:6333/dashboard"
echo ""
echo "  Quick test:"
echo "    curl http://localhost:8000/health"
echo ""
echo "  Upload a video:"
echo "    curl -X POST http://localhost:8000/api/v1/videos/upload -F 'file=@lecture.mp4'"
echo ""
