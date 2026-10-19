// Visibilidad de la publicidad: un anuncio cuenta como visto si esta al menos al 50 % en pantalla durante
// 1 s seguido. Una sola baliza por anuncio y sin cookies. Sin JavaScript no se cuenta (es lo correcto).
(function () {
  var ads = document.querySelectorAll("[data-ad-view]");
  if (!ads.length || !("IntersectionObserver" in window)) return;
  var timers = new WeakMap();
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      var el = e.target;
      if (e.isIntersecting && e.intersectionRatio >= 0.5) {
        if (timers.has(el)) return;
        timers.set(el, setTimeout(function () {
          io.unobserve(el);
          var url = el.getAttribute("data-ad-view");
          el.removeAttribute("data-ad-view");
          if (url) fetch(url, { mode: "no-cors", keepalive: true, credentials: "omit" }).catch(function () {});
        }, 1000));
      } else if (timers.has(el)) {
        clearTimeout(timers.get(el));
        timers.delete(el);
      }
    });
  }, { threshold: [0, 0.5] });
  ads.forEach(function (el) { io.observe(el); });
})();
