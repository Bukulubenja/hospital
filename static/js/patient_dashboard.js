// ---------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------
const themeToggle = document.getElementById('theme-toggle');
const body = document.body;

function applyTheme(isDark) {
    body.classList.toggle('dark-mode', isDark);
    const icon = themeToggle.querySelector('i');
    icon.classList.toggle('fa-sun', isDark);
    icon.classList.toggle('fa-moon', !isDark);
    themeToggle.setAttribute('aria-pressed', String(isDark));
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

themeToggle.addEventListener('click', () => {
    applyTheme(!body.classList.contains('dark-mode'));
});

applyTheme(localStorage.getItem('theme') === 'dark');

// ---------------------------------------------------------------------
// Mobile sidebar toggle — below the 1024px breakpoint the sidebar is
// off-canvas (see patient_dashboard.css); this is the only way to open it.
// ---------------------------------------------------------------------
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');

function closeSidebar() {
    sidebar?.classList.remove('active');
    sidebarBackdrop?.classList.remove('active');
    sidebarToggle?.setAttribute('aria-expanded', 'false');
}

function openSidebar() {
    sidebar?.classList.add('active');
    sidebarBackdrop?.classList.add('active');
    sidebarToggle?.setAttribute('aria-expanded', 'true');
}

sidebarToggle?.addEventListener('click', () => {
    if (sidebar?.classList.contains('active')) {
        closeSidebar();
    } else {
        openSidebar();
    }
});

sidebarBackdrop?.addEventListener('click', closeSidebar);

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar?.classList.contains('active')) {
        closeSidebar();
    }
});

// ---------------------------------------------------------------------
// Sidebar navigation active state
// ---------------------------------------------------------------------
document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () => {
        document.querySelectorAll('.nav-link').forEach((l) => l.classList.remove('active'));
        link.classList.add('active');
        closeSidebar();
    });
});

document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener('click', function (e) {
        const targetId = this.getAttribute('href');
        const target = targetId.length > 1 ? document.querySelector(targetId) : null;
        if (target) {
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth' });
        }
    });
});

// ---------------------------------------------------------------------
// Modal helpers (shared by any .modal on the page)
// ---------------------------------------------------------------------
let lastFocusedElement = null;

function getFocusableElements(container) {
    return container.querySelectorAll(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
    );
}

function openModal(modalId, trigger) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    lastFocusedElement = trigger || document.activeElement;
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    body.style.overflow = 'hidden';

    const focusable = getFocusableElements(modal);
    if (focusable.length) focusable[0].focus();
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;

    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    body.style.overflow = 'auto';

    if (lastFocusedElement) {
        lastFocusedElement.focus();
        lastFocusedElement = null;
    }
}

// Close on outside click
document.querySelectorAll('.modal').forEach((modal) => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal(modal.id);
    });
});

// Close on Escape, and trap Tab focus inside the open modal
document.addEventListener('keydown', (e) => {
    const openModalEl = document.querySelector('.modal.active');
    if (!openModalEl) return;

    if (e.key === 'Escape') {
        closeModal(openModalEl.id);
        return;
    }

    if (e.key === 'Tab') {
        const focusable = Array.from(getFocusableElements(openModalEl));
        if (!focusable.length) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }
});

// Wire up every [data-close-modal] and [data-open-modal] button declaratively
// instead of inline onclick="" attributes, so this file is the single place
// that owns modal behavior (and so a strict CSP with no 'unsafe-inline' works).
document.querySelectorAll('[data-close-modal]').forEach((btn) => {
    btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
});

document.querySelectorAll('[data-open-modal]').forEach((btn) => {
    btn.addEventListener('click', () => openModal(btn.dataset.openModal, btn));
});

// ---------------------------------------------------------------------
// Emergency alert
// ---------------------------------------------------------------------
function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

const emergencyForm = {
    status: document.getElementById('emergency-status'),
    submitBtn: document.getElementById('emergency-submit'),
};

function setEmergencyStatus(message, type) {
    if (!emergencyForm.status) return;
    emergencyForm.status.textContent = message;
    emergencyForm.status.className = `emergency-status ${type}`;
}

// Resolves to {latitude, longitude} or null — never rejects, so a denied/
// unavailable permission doesn't block sending the alert itself.
function getLocation() {
    return new Promise((resolve) => {
        if (!navigator.geolocation) {
            resolve(null);
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
            () => resolve(null),
            { timeout: 8000 }
        );
    });
}

async function sendEmergencyAlert() {
    const alertUrl = document.body.dataset.emergencyAlertUrl;
    const severity = document.querySelector('input[name="severity"]:checked')?.value;
    const shareLocation = document.getElementById('share-location')?.checked ?? false;
    const details = document.getElementById('emergency-details')?.value ?? '';

    if (!severity) {
        setEmergencyStatus('Please select a severity level.', 'error');
        return;
    }

    emergencyForm.submitBtn?.setAttribute('disabled', 'true');
    setEmergencyStatus('Sending alert…', '');

    const location = shareLocation ? await getLocation() : null;

    try {
        const response = await fetch(alertUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
                severity,
                share_location: shareLocation,
                details,
                latitude: location?.latitude ?? null,
                longitude: location?.longitude ?? null,
            }),
        });

        if (!response.ok) throw new Error(`Server responded with ${response.status}`);

        setEmergencyStatus('Front desk notified. Stay on this page.', 'success');
        setTimeout(() => closeModal('emergency-modal'), 1500);
    } catch (err) {
        setEmergencyStatus(
            'Could not reach the hospital. If this is life-threatening, call emergency services now.',
            'error'
        );
    } finally {
        emergencyForm.submitBtn?.removeAttribute('disabled');
    }
}

document.getElementById('emergency-submit')?.addEventListener('click', sendEmergencyAlert);

// ---------------------------------------------------------------------
// Confirm before a destructive POST (e.g. cancelling an appointment) —
// declarative like the modal wiring above, so no inline onsubmit="" is
// needed on the form itself.
// ---------------------------------------------------------------------
document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (e) => {
        if (!window.confirm(form.dataset.confirm)) {
            e.preventDefault();
        }
    });
});

// ---------------------------------------------------------------------
// Live client-side filtering: search box (upcoming appointments + medical
// history) and the medical-history department dropdown. Both only hide/show
// already-rendered rows — no extra request, since everything shown is
// already the patient's own data.
// ---------------------------------------------------------------------
const searchInput = document.getElementById('dashboard-search');
const departmentFilter = document.getElementById('history-department-filter');

function applyFilters() {
    const query = (searchInput?.value ?? '').trim().toLowerCase();

    document.querySelectorAll('.appointment-item').forEach((item) => {
        item.style.display = !query || item.textContent.toLowerCase().includes(query) ? '' : 'none';
    });

    const department = departmentFilter?.value ?? '';
    document.querySelectorAll('.timeline-item').forEach((item) => {
        const matchesQuery = !query || item.textContent.toLowerCase().includes(query);
        const matchesDepartment = !department || item.dataset.department === department;
        item.style.display = matchesQuery && matchesDepartment ? '' : 'none';
    });
}

searchInput?.addEventListener('input', applyFilters);
departmentFilter?.addEventListener('change', applyFilters);