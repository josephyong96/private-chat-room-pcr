#!/bin/bash
set -e

APP_DIR="/opt/data/private-chat-room-pcr"
DATA_DIR="/mnt/user/appdata/private-chat-room-pcr"
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

set -a
source "$DATA_DIR/.env"
set +a

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
    -e DB_PATH=/data/chat.db \
    -e UPLOAD_DIR=/app/uploads \
    -e PORT=5000 \
    private-chat-room-pcr:latest

echo "PCR deployed at http://$DOMAIN (port $PORT internally mapped)"
echo "Default login: admin / $DEFAULT_ADMIN_PASSWORD"
echo "Make sure Nginx Proxy Manager forwards $DOMAIN to this Unraid host on port $PORT with Websockets enabled."
