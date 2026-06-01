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
});
