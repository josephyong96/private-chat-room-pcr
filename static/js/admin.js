const form = document.getElementById('add-member-form');
const msgEl = document.getElementById('add-member-msg');
const tableBody = document.getElementById('members-table');
const clearBtn = document.getElementById('clear-chat-btn');

async function loadMembers() {
    const res = await fetch('/api/members');
    const data = await res.json();
    tableBody.innerHTML = '';
    data.members.forEach(u => {
        const tr = document.createElement('tr');
        tr.dataset.id = u.id;
        tr.innerHTML = `
            <td>${u.username}</td>
            <td>${u.display_name}</td>
            <td>${u.role}</td>
            <td>
                <button class="btn btn-sm btn-warning reset-pw-btn" data-id="${u.id}">Reset PW</button>
                ${u.role !== 'admin' ? `<button class="btn btn-sm btn-danger remove-btn" data-id="${u.id}">Remove</button>` : ''}
            </td>
        `;
        tableBody.appendChild(tr);
    });
    bindActions();
}

function bindActions() {
    document.querySelectorAll('.reset-pw-btn').forEach(btn => {
        btn.onclick = async () => {
            const newPw = prompt('Enter new password (min 4 chars):');
            if (!newPw || newPw.length < 4) return alert('Password too short');
            const res = await fetch('/api/admin/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(btn.dataset.id), new_password: newPw })
            });
            const data = await res.json();
            alert(data.success ? 'Password reset.' : (data.error || 'Failed'));
        };
    });

    document.querySelectorAll('.remove-btn').forEach(btn => {
        btn.onclick = async () => {
            if (!confirm('Remove this member?')) return;
            const res = await fetch('/api/admin/remove-member', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(btn.dataset.id) })
            });
            const data = await res.json();
            if (data.success) loadMembers();
            else alert(data.error || 'Failed');
        };
    });
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('new-username').value.trim().toLowerCase();
    const displayName = document.getElementById('new-display-name').value.trim();
    const password = document.getElementById('new-password').value;

    const res = await fetch('/api/admin/add-member', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, display_name: displayName, password })
    });
    const data = await res.json();
    msgEl.textContent = data.success ? 'Member added.' : (data.error || 'Failed');
    msgEl.className = 'form-msg ' + (data.success ? 'alert-success' : 'alert-error');
    if (data.success) {
        form.reset();
        loadMembers();
    }
});

clearBtn.addEventListener('click', async () => {
    if (!confirm('Clear entire chat history? This cannot be undone.')) return;
    const res = await fetch('/api/admin/clear-chat', { method: 'POST' });
    const data = await res.json();
    alert(data.success ? 'Chat cleared.' : (data.error || 'Failed'));
});

loadMembers();
