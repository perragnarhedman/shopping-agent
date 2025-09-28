#!/bin/bash
set -euo pipefail

echo "🐳 Setting up Shopping Agent (local)"

if ! command -v docker &>/dev/null; then
  echo "Docker is required. Please install Docker Desktop." >&2
  exit 1
fi

mkdir -p logs data

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Fill in OPENAI_API_KEY if needed."
  else
    cat > .env << 'EOF'
OPENAI_API_KEY=
ENVIRONMENT=development
LOG_LEVEL=INFO
DEFAULT_STORE=coop_se
MEMORY_BACKEND=local
REDIS_URL=redis://redis:6379/0
EOF
    echo "Created .env with defaults. Fill in OPENAI_API_KEY if needed."
  fi
fi

docker compose up --build -d | cat

echo "Waiting 5s for containers to initialize..."
sleep 5

docker compose ps | cat

echo "Attempting health check (http://localhost:8000/health)"
set +e
curl -sf http://localhost:8000/health && echo "\n✅ Health OK" || echo "\n⚠️ Health endpoint not responding yet"
set -e

echo "Done. View logs with: docker compose logs -f shopping-agent"


