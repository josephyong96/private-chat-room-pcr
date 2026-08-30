#!/bin/bash
set -e

APP_DIR="/opt/data/private-chat-room-pcr"

# Preserve existing PCR data if this is a redeploy of the older family-chat container
if [ -d "/opt/data/family-chat-data" ]; then
    DATA_DIR="/opt/data/family-chat-data"
elif [ -d "/mnt/user/appdata" ]; then
    DATA_DIR="/mnt/user/appdata/private-chat-room-pcr"
else
    DATA_DIR="$APP_DIR/data"
fi

DOMAIN="${1:-chat.example.com}"
PORT="${2:-8787}"

echo "Deploying Private Chat Room (PCR) to Unraid..."

mkdir -p "$DATA_DIR/uploads"

if [ ! -f "$DATA_DIR/.env" ]; then
    SECRET=$(openssl rand -hex 32)
    cat > "$DATA_DIR/.env" <<EOF
SECRET_KEY=$SECRET
DEFAULT_ADMIN_PASSWORD=admin1234
EOF
    echo "Created default .env file. Please change DEFAULT_ADMIN_PASSWORD after first login."
fi

# Read only the safe variables we need from .env (do not source multi-line VAPID keys)
SECRET_KEY=$(grep "^SECRET_KEY=" "$DATA_DIR/.env" | head -1 | cut -d= -f2-)
DEFAULT_ADMIN_PASSWORD=$(grep "^DEFAULT_ADMIN_PASSWORD=" "$DATA_DIR/.env" | head -1 | cut -d= -f2-)

# Preserve older family_chat.db database filename if migrating from the family-chat container
if [ -f "$DATA_DIR/family_chat.db" ]; then
    DB_PATH_IN_CONTAINER=/data/family_chat.db
else
    DB_PATH_IN_CONTAINER=/data/chat.db
fi

cd "$APP_DIR"
docker build -t private-chat-room-pcr:latest .
docker rm -f private-chat-room-pcr 2>/dev/null || true
docker run -d \
    --name private-chat-room-pcr \
    --restart unless-stopped \
    -p "$PORT:5000" \
    -v "$DATA_DIR:/data" \
    -v "$DATA_DIR/uploads:/app/uploads" \
    -e SECRET_KEY="$SECRET_KEY" \
    -e DEFAULT_ADMIN_PASSWORD="$DEFAULT_ADMIN_PASSWORD" \
    -e DB_PATH="$DB_PATH_IN_CONTAINER" \
    -e UPLOAD_DIR=/data/uploads \
    -e PORT=5000 \
    private-chat-room-pcr:latest

echo "PCR deployed at http://$DOMAIN (port $PORT internally mapped)"
echo "Default login: admin / $DEFAULT_ADMIN_PASSWORD"
echo "Make sure Nginx Proxy Manager forwards $DOMAIN to this Unraid host on port $PORT with Websockets enabled."
