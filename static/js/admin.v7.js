const form = document.getElementById('add-member-form');
const msgEl = document.getElementById('add-member-msg');
const tableBody = document.getElementById('members-table');
const clearBtn = document.getElementById('clear-chat-btn');

const adminContainer = document.querySelector('.admin-container');
const isSuperuser = adminContainer && adminContainer.dataset.superuser === 'true';
const currentUserId = adminContainer ? parseInt(adminContainer.dataset.userId || '0') : 0;

async function loadMembers() {
    const res = await fetch('/api/members');
    const data = await res.json();
    tableBody.innerHTML = '';
    data.members.forEach(u => {
        const tr = document.createElement('tr');
        tr.dataset.id = u.id;
        const roleCell = isSuperuser && u.id !== currentUserId
            ? `<select class="role-select" data-id="${u.id}">
                 <option value="member" ${u.role === 'member' ? 'selected' : ''}>Member</option>
                 <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
               </select>`
            : u.role;
        tr.innerHTML = `
            <td>${u.username}</td>
            <td>${u.display_name}</td>
            <td>${roleCell}</td>
            <td>
                <button class="btn btn-sm btn-warning reset-pw-btn" data-id="${u.id}">Reset PW</button>
                ${u.role !== 'admin' && u.id !== currentUserId ? `<button class="btn btn-sm btn-danger remove-btn" data-id="${u.id}">Remove</button>` : ''}
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

    document.querySelectorAll('.role-select').forEach(sel => {
        const original = sel.value;
        sel.onchange = async () => {
            if (!confirm(`Change role to ${sel.value}?`)) {
                sel.value = original;
                return;
            }
            const res = await fetch('/api/admin/change-role', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(sel.dataset.id), role: sel.value })
            });
            const data = await res.json();
            if (data.success) {
                loadMembers();
            } else {
                alert(data.error || 'Failed');
                sel.value = original;
            }
        };
    });
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('new-username').value.trim().toLowerCase();
    const displayName = document.getElementById('new-display-name').value.trim();
    const password = document.getElementById('new-password').value;
    const roleEl = document.getElementById('new-role');
    const role = roleEl ? roleEl.value : 'member';

    const res = await fetch('/api/admin/add-member', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, display_name: displayName, password, role })
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
