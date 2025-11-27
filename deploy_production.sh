#!/bin/bash
# Production Deployment Script

set -e

echo "🚀 Starting Production Deployment..."

# 1. Load production environment
export $(cat .env.production | xargs)

# 2. Run database migrations
echo "📊 Running database migrations..."
alembic upgrade head

# 3. Build and deploy with Docker
echo "🐳 Building production containers..."
docker-compose -f docker-compose.prod.yml build

echo "🚀 Starting production services..."
docker-compose -f docker-compose.prod.yml up -d

# 4. Health check
echo "🏥 Performing health check..."
sleep 10
curl -f http://localhost:8000/health || exit 1

echo "✅ Production deployment complete!"
echo "🌐 API available at: http://${DOMAIN_NAME}"