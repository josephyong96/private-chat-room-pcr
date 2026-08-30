# Private Chat Room (PCR)

A private, family-first chat room designed for supervised communication. PCR runs on your own server and is managed entirely by an admin.

## Why PCR?

PCR gives families a safe, controlled chat environment for children to learn digital communication without exposing them to public messaging apps built for adults.

## Key features

- **Admin-only membership** — only the admin can add or remove members
- **Admin-only moderation** — only the admin can delete messages or clear the chat
- **Real-time messaging** — instant delivery via WebSocket
- **Media sharing** — photos, videos, voice notes, documents
- **PWA support** — install on iPhone / Android home screen
- **Self-hosted** — runs on your own Unraid/private server

## Tech stack

- Flask + Flask-SocketIO
- SQLite
- Eventlet WebSocket server
- Progressive Web App (PWA)
- Docker on Unraid

## Quick start

### 1. Clone and deploy

```bash
git clone https://github.com/josephyong96/private-chat-room-pcr.git
cd private-chat-room-pcr
bash deploy.sh chat.yourdomain.com 8787
```

### 2. Configure Nginx Proxy Manager

| Setting | Value |
|---------|-------|
| Domain | `chat.yourdomain.com` |
| Forward Hostname/IP | Unraid host IP |
| Forward Port | `8787` |
| **Websockets** | **Enabled** |
| SSL | Request certificate |

### 3. First login

- Open `https://chat.yourdomain.com`
- Login: `admin` / `admin1234`
- Change the admin password immediately
- Go to **Admin Panel** and add family members

## Admin rules

| Action | Who can do it |
|--------|---------------|
| Add member | Admin only |
| Remove member | Admin only |
| Reset password | Admin only |
| Delete a message | Admin only |
| Clear entire chat | Admin only |
| Send messages | All members |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | random | Flask session secret |
| `DEFAULT_ADMIN_PASSWORD` | `admin1234` | Initial admin password |
| `DB_PATH` | `./chat.db` | SQLite database path |
| `UPLOAD_DIR` | `./uploads` | Uploaded files directory |
| `PORT` | `5000` | Internal port |

## License

MIT — private use only by the deploying family/organization.
