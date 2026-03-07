self.addEventListener('install', (e) => {
    self.skipWaiting();
    console.log('[PWA] Service Worker Installed');
});

self.addEventListener('fetch', (e) => {
    // 保持轉發，確保 MJPEG 影像流不被快取
});