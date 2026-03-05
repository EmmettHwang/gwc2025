// Service Worker for BH2025 Education Management System PWA
// Version: 1.0.0

const CACHE_NAME = 'bh2025-v1.0.0';
const RUNTIME_CACHE = 'bh2025-runtime-v1';

// 오프라인에서도 사용 가능한 정적 파일들
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/login.html',
  '/app.js',
  '/favicon.ico',
  // CDN 리소스는 온라인에서만 사용
];

// API 요청 캐싱 전략 (네트워크 우선, 실패시 캐시 사용)
const API_CACHE_URLS = [
  '/api/auth/login',
  '/api/students',
  '/api/instructors',
  '/api/courses',
  '/api/counselings',
  '/api/training-logs',
  '/api/timetables',
  '/api/projects'
];

// ==================== Install Event ====================
self.addEventListener('install', (event) => {
  console.log('[Service Worker] Installing...');
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[Service Worker] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => {
        console.log('[Service Worker] Installation complete');
        return self.skipWaiting(); // 즉시 활성화
      })
      .catch((error) => {
        console.error('[Service Worker] Installation failed:', error);
      })
  );
});

// ==================== Activate Event ====================
self.addEventListener('activate', (event) => {
  console.log('[Service Worker] Activating...');
  
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            // 오래된 캐시 삭제
            if (cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE) {
              console.log('[Service Worker] Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      })
      .then(() => {
        console.log('[Service Worker] Activation complete');
        return self.clients.claim(); // 모든 클라이언트에 즉시 적용
      })
  );
});

// ==================== Fetch Event ====================
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  
  // API 요청 처리 (Network First 전략)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstStrategy(request));
    return;
  }
  
  // 정적 파일 처리 (Cache First 전략)
  event.respondWith(cacheFirstStrategy(request));
});

// ==================== Caching Strategies ====================

// Network First: 네트워크 우선, 실패시 캐시 사용 (API 요청용)
async function networkFirstStrategy(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  
  try {
    // 네트워크 요청 시도
    const response = await fetch(request);
    
    // 성공하면 캐시에 저장
    if (response && response.status === 200) {
      cache.put(request, response.clone());
    }
    
    return response;
  } catch (error) {
    // 네트워크 실패 시 캐시에서 가져오기
    console.log('[Service Worker] Network failed, trying cache:', request.url);
    const cachedResponse = await cache.match(request);
    
    if (cachedResponse) {
      return cachedResponse;
    }
    
    // 캐시도 없으면 오프라인 응답 반환
    return new Response(
      JSON.stringify({
        error: 'offline',
        message: '오프라인 상태입니다. 인터넷 연결을 확인해주세요.'
      }),
      {
        status: 503,
        statusText: 'Service Unavailable',
        headers: new Headers({
          'Content-Type': 'application/json'
        })
      }
    );
  }
}

// Cache First: 캐시 우선, 없으면 네트워크 (정적 파일용)
async function cacheFirstStrategy(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request);
  
  if (cachedResponse) {
    return cachedResponse;
  }
  
  try {
    const response = await fetch(request);
    
    // 성공하면 캐시에 저장
    if (response && response.status === 200) {
      cache.put(request, response.clone());
    }
    
    return response;
  } catch (error) {
    console.error('[Service Worker] Fetch failed:', error);
    
    // 오프라인 페이지 반환 (선택사항)
    return new Response('오프라인 상태입니다', {
      status: 503,
      statusText: 'Service Unavailable'
    });
  }
}

// ==================== Background Sync (미래 확장용) ====================
self.addEventListener('sync', (event) => {
  console.log('[Service Worker] Background sync:', event.tag);
  
  if (event.tag === 'sync-data') {
    event.waitUntil(syncData());
  }
});

async function syncData() {
  // 오프라인에서 저장된 데이터를 서버와 동기화
  console.log('[Service Worker] Syncing offline data...');
  // 구현 예정
}

// ==================== Push Notifications (미래 확장용) ====================
self.addEventListener('push', (event) => {
  console.log('[Service Worker] Push notification received');
  
  const data = event.data ? event.data.json() : {};
  const title = data.title || '교육관리시스템';
  const options = {
    body: data.body || '새로운 알림이 있습니다',
    icon: '/icon-192x192.png',
    badge: '/badge-72x72.png',
    vibrate: [200, 100, 200],
    data: data
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  console.log('[Service Worker] Notification clicked');
  event.notification.close();
  
  // 앱 열기
  event.waitUntil(
    clients.openWindow('/')
  );
});

console.log('[Service Worker] Loaded successfully');
