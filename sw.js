/* Guarda os arquivos do app para abrir sem internet. A previsão é salva pela própria página. */
const VERSAO = "firmamento-3";
const FONTES = "firmamento-fontes";
const ARQUIVOS = ["./", "manifest.webmanifest", "icones/icone-192.png", "icones/icone-512.png",
  "icones/icone-mascara-512.png", "icones/icone-apple-180.png", "icones/favicon-32.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO && n !== FONTES).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

// Arquivos do app: tenta a versão nova, mas com sinal fraco não deixa a abertura esperando
async function arquivoDoApp(e) {
  const cache = await caches.open(VERSAO);
  const chave = e.request.mode === "navigate" ? "./" : e.request;
  const salvo = await cache.match(chave, { ignoreSearch: true });
  const rede = fetch(e.request).then(async (r) => {
    if (r.ok) await cache.put(chave, r.clone());
    return r;
  });
  e.waitUntil(rede.catch(() => {}));
  if (!salvo) return rede;
  const espera = new Promise((ok) => setTimeout(ok, 4000, salvo));
  return Promise.race([rede.then((r) => (r.ok ? r : salvo), () => salvo), espera]);
}

// Fontes não mudam: uma vez baixadas, vêm sempre do aparelho
async function fonte(req) {
  const cache = await caches.open(FONTES);
  const salvo = await cache.match(req);
  if (salvo) return salvo;
  const r = await fetch(req);
  if (r.ok || r.type === "opaque") await cache.put(req, r.clone());
  return r;
}

// Alertas de tempestade, enviados pela tarefa em alertas/verificar.py
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch { /* sem conteúdo: mostra o aviso genérico */ }
  e.waitUntil(self.registration.showNotification(d.titulo || "Nuvem", {
    body: d.corpo || "Abra o app para ver a previsão.", icon: "icones/icone-192.png", tag: d.tag, data: { url: d.url || "./" } }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((abertas) => {
    const janela = abertas.find((c) => "focus" in c);
    return janela ? janela.focus() : self.clients.openWindow(new URL(e.notification.data?.url || "./", self.registration.scope).href);
  }));
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin === location.origin) e.respondWith(arquivoDoApp(e));
  else if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") e.respondWith(fonte(e.request));
});
