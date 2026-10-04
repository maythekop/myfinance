/* sw.js — เก็บไฟล์ของแอปห่อไว้ในเครื่อง ให้เปิดหน้าปลดล็อกได้เร็ว
   ไม่เก็บอะไรของ Apps Script (ข้อมูลจริงโหลดใหม่ทุกครั้ง) */
var CACHE = 'mf-shell-v1';
var SHELL = ['./', 'index.html', 'config.js', 'manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
// ไฟล์ของแอปห่อ: ใช้ของใหม่จากเน็ตก่อน ถ้าออฟไลน์ใช้ของในเครื่อง · คำขออื่นปล่อยผ่าน
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(fetch(req).then(function (res) {
    var copy = res.clone();
    caches.open(CACHE).then(function (c) { c.put(req, copy); });
    return res;
  }).catch(function () { return caches.match(req).then(function (m) { return m || caches.match('index.html'); }); }));
});
