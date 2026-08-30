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
let currentAudio = null;
let currentVoiceNote = null;

function formatTime(iso) {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatDuration(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem.toString().padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function buildWaveform(bars = 20) {
    let html = '';
    for (let i = 0; i < bars; i++) {
        // deterministic pseudo-random heights
        const h = 30 + Math.abs(Math.sin(i * 1.7) * 70);
        html += `<div class="bar" style="height:${h.toFixed(1)}%"></div>`;
    }
    return html;
}

function setupVoiceNotePlayer(container) {
    const audio = container.querySelector('audio');
    const playBtn = container.querySelector('.play-btn');
    const bars = container.querySelectorAll('.bar');
    const timeEl = container.querySelector('.time');

    audio.addEventListener('loadedmetadata', () => {
        timeEl.textContent = formatDuration(audio.duration);
    });

    // Some browsers don't fire loadedmetadata on short blobs; use canplaythrough fallback
    audio.addEventListener('canplay', () => {
        if (!isFinite(audio.duration) || audio.duration === 0) return;
        timeEl.textContent = formatDuration(audio.duration);
    });

    audio.addEventListener('timeupdate', () => {
        if (!isFinite(audio.duration) || audio.duration === 0) return;
        const progress = audio.currentTime / audio.duration;
        const idx = Math.floor(progress * bars.length);
        bars.forEach((b, i) => {
            b.classList.toggle('played', i < idx);
        });
        timeEl.textContent = formatDuration(audio.duration - audio.currentTime);
    });

    audio.addEventListener('ended', () => {
        playBtn.classList.remove('playing');
        playBtn.classList.add('paused');
        bars.forEach(b => b.classList.remove('played'));
        timeEl.textContent = formatDuration(audio.duration);
    });

    playBtn.addEventListener('click', () => {
        // Stop any other playing voice note
        if (currentAudio && currentAudio !== audio && !currentAudio.paused) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            if (currentVoiceNote) {
                currentVoiceNote.querySelector('.play-btn').classList.remove('playing');
                currentVoiceNote.querySelector('.play-btn').classList.add('paused');
                currentVoiceNote.querySelectorAll('.bar').forEach(b => b.classList.remove('played'));
            }
        }
        currentAudio = audio;
        currentVoiceNote = container;

        if (audio.paused) {
            audio.play();
            playBtn.classList.remove('paused');
            playBtn.classList.add('playing');
        } else {
            audio.pause();
            playBtn.classList.remove('playing');
            playBtn.classList.add('paused');
        }
    });
}

function getAvatarHtml(msg) {
    const name = msg.sender_name || '?';
    const initial = name.charAt(0).toUpperCase();
    if (msg.profile_picture) {
        return `<img src="/uploads/${encodeURIComponent(msg.profile_picture)}" alt="${escapeHtml(name)}" class="message-avatar">`;
    }
    return `<div class="message-avatar avatar-initial">${escapeHtml(initial)}</div>`;
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
            mediaHtml = `
                <div class="voice-note">
                    <button class="play-btn paused" type="button" aria-label="Play"></button>
                    <div class="waveform">${buildWaveform()}</div>
                    <span class="time">0:00</span>
                    <audio src="${url}" preload="metadata"></audio>
                </div>
            `;
        } else {
            mediaHtml = `<a class="file-link" href="${url}" target="_blank" download>📎 ${escapeHtml(msg.file_name)}</a>`;
        }
    }

    let deleteBtn = '';
    if (isAdmin) {
        deleteBtn = `<button class="delete-btn" title="Delete message">×</button>`;
    }

    const avatarHtml = getAvatarHtml(msg);

    div.innerHTML = `
        ${isOwn ? '' : avatarHtml}
        <div class="message-bubble">
            <div class="meta">
                <span>${escapeHtml(msg.sender_name)}</span>
                <span>${formatTime(msg.created_at)}</span>
            </div>
            <div class="text">${escapeHtml(msg.content || '')}</div>
            ${mediaHtml}
            ${deleteBtn}
        </div>
        ${isOwn ? avatarHtml : ''}
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

    const voiceNote = div.querySelector('.voice-note');
    if (voiceNote) setupVoiceNotePlayer(voiceNote);

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

async function registerPush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
    try {
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') return;
        const res = await fetch('/api/vapid-public-key');
        const keyData = await res.json();
        const publicKey = keyData.public_key;
        if (!publicKey) return;
        const reg = await navigator.serviceWorker.ready;
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlBase64ToUint8Array(publicKey)
            });
        }
        await fetch('/api/push-subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription: sub.toJSON() })
        });
    } catch (e) {
        console.log('Push registration failed:', e);
    }
}

function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

registerPush();
