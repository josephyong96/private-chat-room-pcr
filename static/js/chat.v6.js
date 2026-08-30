const socket = io();
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const attachBtn = document.getElementById('attach-btn');
const fileInput = document.getElementById('file-input');
const previewEl = document.getElementById('file-preview');
const voiceBtn = document.getElementById('voice-btn');
const statusEl = document.getElementById('connection-status');

let pendingFile = null;
let mediaRecorder = null;
let audioChunks = [];

function formatTime(iso) {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderMessage(msg) {
    const isOwn = msg.sender_id === currentUserId;
    const div = document.createElement('div');
    div.className = `message ${isOwn ? 'own' : ''}`;
    div.dataset.id = msg.id;

    let mediaHtml = '';
    if (msg.file_url || (msg.file_name && msg.media_type)) {
        const url = msg.file_url || '/uploads/' + encodeURIComponent(msg.file_name);
        if (msg.media_type === 'image') {
            mediaHtml = `<img src="${url}" alt="image" loading="lazy">`;
        } else if (msg.media_type === 'video') {
            mediaHtml = `<video src="${url}" controls preload="metadata"></video>`;
        } else if (msg.media_type === 'audio') {
            mediaHtml = `<audio src="${url}" controls></audio>`;
        } else {
            mediaHtml = `<a class="file-link" href="${url}" target="_blank" download>📎 ${escapeHtml(msg.file_name)}</a>`;
        }
    }

    let deleteBtn = '';
    if (isAdmin) {
        deleteBtn = `<button class="delete-btn" title="Delete message">×</button>`;
    }

    div.innerHTML = `
        <div class="meta">
            <span>${escapeHtml(msg.sender_name)}</span>
            <span>${formatTime(msg.created_at)}</span>
        </div>
        <div class="text">${escapeHtml(msg.content || '')}</div>
        ${mediaHtml}
        ${deleteBtn}
    `;

    if (isAdmin) {
        div.querySelector('.delete-btn').addEventListener('click', async () => {
            if (!confirm('Delete this message?')) return;
            const res = await fetch('/api/admin/delete-message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message_id: msg.id })
            });
            if (!res.ok) alert('Failed to delete message.');
        });
    }

    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function loadHistory() {
    const res = await fetch('/api/messages');
    const data = await res.json();
    messagesEl.innerHTML = '';
    data.messages.forEach(renderMessage);
}

socket.on('connect', () => { statusEl.textContent = 'Connected'; statusEl.style.color = '#86efac'; });
socket.on('disconnect', () => { statusEl.textContent = 'Disconnected'; statusEl.style.color = '#fca5a5'; });

socket.on('new_message', (msg) => {
    renderMessage(msg);
});

socket.on('message_deleted', (data) => {
    const el = messagesEl.querySelector(`[data-id="${data.message_id}"]`);
    if (el) el.remove();
});

socket.on('chat_cleared', () => {
    messagesEl.innerHTML = '';
});

async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text && !pendingFile) return;

    let fileInfo = {};
    if (pendingFile) {
        const formData = new FormData();
        formData.append('file', pendingFile.file);
        try {
            const res = await fetch('/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.success) {
                fileInfo = data;
            } else {
                alert(data.error || 'Upload failed');
                return;
            }
        } catch (e) {
            alert('Upload error: ' + e.message);
            return;
        }
    }

    socket.emit('send_message', { content: text, file: fileInfo });
    inputEl.value = '';
    pendingFile = null;
    previewEl.textContent = '';
}

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendMessage(); });

attachBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
        pendingFile = { file: fileInput.files[0] };
        previewEl.textContent = 'Attached: ' + pendingFile.file.name;
    }
});

voiceBtn.addEventListener('click', async () => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        return;
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/mp4';
        mediaRecorder = new MediaRecorder(stream, { mimeType });
        audioChunks = [];
        mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: mimeType });
            const ext = mimeType.includes('webm') ? 'webm' : 'mp4';
            const file = new File([blob], `voice-note.${ext}`, { type: mimeType });
            pendingFile = { file };
            previewEl.textContent = 'Voice note ready';
            stream.getTracks().forEach(t => t.stop());
            voiceBtn.textContent = '🎤';
        };
        mediaRecorder.onerror = () => {
            stream.getTracks().forEach(t => t.stop());
            voiceBtn.textContent = '🎤';
            alert('Recording failed.');
        };
        mediaRecorder.start();
        voiceBtn.textContent = '⏹';
    } catch (e) {
        voiceBtn.textContent = '🎤';
        alert('Microphone access denied or not supported.');
    }
});

loadHistory();
