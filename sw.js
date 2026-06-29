const CACHE='kd-v1';
self.addEventListener('install',function(e){
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(function(c){return c.add('/data/kd-articles.json');}).catch(function(){}));
});
self.addEventListener('activate',function(e){e.waitUntil(clients.claim());});
self.addEventListener('fetch',function(e){
  if(!e.request.url.includes('kd-articles.json'))return;
  e.respondWith(caches.open(CACHE).then(function(cache){
    return cache.match(e.request).then(function(cached){
      var fresh=fetch(e.request).then(function(r){if(r.ok)cache.put(e.request,r.clone());return r;}).catch(function(){return cached;});
      return cached||fresh;
    });
  }));
});
