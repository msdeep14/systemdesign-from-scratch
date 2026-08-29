document.addEventListener('DOMContentLoaded', () => {
    // Hamburger Menu Toggle
    const hamburgerMenu = document.getElementById('hamburger-menu');
    const navbarLinks = document.getElementById('navbar-links');
    
    if (hamburgerMenu && navbarLinks) {
        hamburgerMenu.addEventListener('click', () => {
            navbarLinks.classList.toggle('active');
        });
    }

    // Auto-hide toasts after 5 seconds
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach(toast => {
        setTimeout(() => {
            toast.style.transition = 'opacity 0.5s ease';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 500);
        }, 5000);
    });

    // Tribute.js setup for @username mentions
    if (typeof Tribute !== 'undefined') {
        const tribute = new Tribute({
            trigger: '@',
            selectTemplate: function (item) {
                return '@' + item.original.username;
            },
            menuItemTemplate: function (item) {
                return `<div style="display: flex; align-items: center; gap: 8px;">
                            ${item.original.avatar ? `<img src="${item.original.avatar}" style="width:24px; height:24px; border-radius:50%; object-fit:cover;">` : `<div style="width:24px; height:24px; border-radius:50%; background:var(--primary); color:white; display:flex; align-items:center; justify-content:center; font-size:12px;">${item.original.name.charAt(0).toUpperCase()}</div>`}
                            <span style="font-weight: 500;">${item.original.username}</span>
                            <span style="color: var(--text-muted); font-size: 0.8rem;">${item.original.name}</span>
                        </div>`;
            },
            values: function (text, cb) {
                if (!text) {
                    cb([]);
                    return;
                }
                fetch(`/users/api/search/?q=${encodeURIComponent(text)}`)
                    .then(res => res.json())
                    .then(data => cb(data))
                    .catch(err => cb([]));
            },
            lookup: 'username',
            fillAttr: 'username'
        });

        const captionInput = document.getElementById('id_caption');
        if (captionInput) {
            tribute.attach(captionInput);
        }
        const commentInput = document.getElementById('comment-input');
        if (commentInput) {
            tribute.attach(commentInput);
        }
    }
});
