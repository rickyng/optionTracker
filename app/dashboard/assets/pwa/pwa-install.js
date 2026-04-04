// ─── IBKR Options Analyzer — PWA Install Prompt ─────────────────────────────
// Handles the browser's "add to home screen" prompt and provides an
// install button for Android Chrome + an iOS Safari instruction banner.

(function () {
  'use strict';

  let deferredPrompt = null;

  // ── Detect iOS Safari (no beforeinstallprompt support) ──────────────────
  const isIOS =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isStandalone =
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;

  // ── Inject CSS for install UI ───────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    .pwa-install-btn {
      position: fixed;
      bottom: 1.25rem;
      right: 1.25rem;
      z-index: 9999;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.7rem 1.2rem;
      background: #64ffda;
      color: #0f0f1a;
      border: none;
      border-radius: 50px;
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 20px rgba(100, 255, 218, 0.3);
      transition: opacity 0.3s, transform 0.3s;
      animation: pwa-slide-up 0.4s ease-out;
    }
    .pwa-install-btn:hover { transform: scale(1.03); }
    .pwa-install-btn:active { transform: scale(0.97); }
    .pwa-install-btn svg { width: 18px; height: 18px; fill: #0f0f1a; }
    .pwa-install-btn.pwa-hidden { display: none; }

    .pwa-dismiss-btn {
      position: fixed;
      bottom: 1.25rem;
      right: 1.25rem;
      z-index: 9998;
      background: #2a2a4a;
      color: #8892b0;
      border: none;
      border-radius: 50%;
      width: 28px;
      height: 28px;
      font-size: 14px;
      line-height: 1;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      animation: pwa-slide-up 0.4s ease-out;
    }
    .pwa-dismiss-btn.pwa-hidden { display: none; }

    .pwa-ios-banner {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      z-index: 9999;
      background: #1a1a2e;
      border-top: 1px solid #2a2a4a;
      padding: 1rem 1.25rem;
      padding-bottom: calc(1rem + env(safe-area-inset-bottom, 0px));
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      animation: pwa-slide-up 0.4s ease-out;
    }
    .pwa-ios-banner.pwa-hidden { display: none; }
    .pwa-ios-banner p {
      color: #e0e0e0;
      font-size: 0.85rem;
      margin-bottom: 0.5rem;
      line-height: 1.4;
    }
    .pwa-ios-banner .ios-steps {
      color: #8892b0;
      font-size: 0.8rem;
    }
    .pwa-ios-banner .ios-steps strong { color: #64ffda; }
    .pwa-ios-banner .ios-close {
      position: absolute;
      top: 0.5rem;
      right: 0.75rem;
      background: none;
      border: none;
      color: #8892b0;
      font-size: 1.1rem;
      cursor: pointer;
      padding: 0.25rem;
    }

    @keyframes pwa-slide-up {
      from { transform: translateY(100%); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
  `;
  document.head.appendChild(style);

  // Don't show anything if already installed as standalone
  if (isStandalone) return;

  // ── Android Chrome: beforeinstallprompt ──────────────────────────────────
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;

    // Check if user previously dismissed
    if (sessionStorage.getItem('pwa-install-dismissed')) return;

    const btn = document.createElement('button');
    btn.className = 'pwa-install-btn';
    btn.innerHTML = `
      <svg viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
      Install App
    `;

    const dismiss = document.createElement('button');
    dismiss.className = 'pwa-dismiss-btn';
    dismiss.innerHTML = '&times;';
    dismiss.title = 'Dismiss';
    dismiss.style.bottom = '4.5rem';

    btn.addEventListener('click', async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      console.log('[PWA] Install outcome:', outcome);
      deferredPrompt = null;
      btn.remove();
      dismiss.remove();
    });

    dismiss.addEventListener('click', () => {
      btn.remove();
      dismiss.remove();
      sessionStorage.setItem('pwa-install-dismissed', '1');
    });

    document.body.appendChild(btn);
    document.body.appendChild(dismiss);
  });

  window.addEventListener('appinstalled', () => {
    console.log('[PWA] App installed');
    document.querySelectorAll('.pwa-install-btn, .pwa-dismiss-btn').forEach((el) => el.remove());
  });

  // ── iOS Safari: show instruction banner ──────────────────────────────────
  if (isIOS && !isStandalone) {
    // Wait for DOM ready
    const showIOSBanner = () => {
      if (localStorage.getItem('pwa-ios-dismissed')) return;

      const banner = document.createElement('div');
      banner.className = 'pwa-ios-banner';
      banner.innerHTML = `
        <button class="ios-close">&times;</button>
        <p><strong>Install IBKR Analyzer</strong></p>
        <p class="ios-steps">
          Tap <strong>Share</strong>
          <svg style="display:inline;vertical-align:middle;width:16px;height:16px;fill:#64ffda" viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z"/></svg>
          then <strong>"Add to Home Screen"</strong>
        </p>
      `;

      banner.querySelector('.ios-close').addEventListener('click', () => {
        banner.remove();
        localStorage.setItem('pwa-ios-dismissed', '1');
      });

      document.body.appendChild(banner);
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', showIOSBanner);
    } else {
      showIOSBanner();
    }
  }
})();
