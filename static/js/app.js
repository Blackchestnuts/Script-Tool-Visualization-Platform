/**
 * 测试效能平台 TEP V1.0 - 全局 JavaScript 工具库
 */

// ============================================================
// Toast 通知系统
// ============================================================

function showToast(title, message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-title">${escapeHtml(title)}</div>
        ${message ? `<div class="toast-message">${escapeHtml(message)}</div>` : ''}
    `;

    container.appendChild(toast);

    // 3秒后自动移除
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================================
// HTML 转义
// ============================================================

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================
// 状态徽章生成
// ============================================================

function getStatusBadge(status) {
    const statusMap = {
        PENDING: { class: 'badge-warning', text: '等待中' },
        RUNNING: { class: 'badge-info', text: '执行中' },
        FINISHED: { class: 'badge-success', text: '已完成' },
        ERROR: { class: 'badge-danger', text: '执行出错' },
    };
    const info = statusMap[status] || { class: 'badge-warning', text: status };
    return `<span class="badge ${info.class}">${info.text}</span>`;
}

// ============================================================
// 格式化工具
// ============================================================

function formatDuration(seconds) {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}

function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    return dateStr;
}
