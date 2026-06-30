#!/bin/bash

# Docker setup script for EduAssist

echo "Setting up EduAssist with Docker..."

# Stop any running containers
docker-compose down

# Build and start services
echo "Building and starting services..."
docker-compose up -d --build

# Wait for database to be ready
echo "Waiting for database to be ready..."
sleep 10

# Create tables + run migrations + seeds
echo "Creating database tables..."
docker-compose exec api python -m database_compare.run_local_migration

echo "Setup complete! Services running:"
echo "- API: http://localhost:8000"
echo "- Database: localhost:5432"
echo "- Redis: localhost:6379"

echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"