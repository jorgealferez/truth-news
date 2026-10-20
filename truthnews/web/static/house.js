// Publicidad propia de Ridelta por zona (ADR 0055). Rota las piezas del banner cada 8 s, se para al pasar el
// raton, con el foco o con el boton de pausa, y no rota si el lector pide movimiento reducido. "Usar mi
// ubicacion" pide la posicion solo al pulsarlo, busca en el navegador el municipio mas cercano de /zonas.json
// y manda a /zona/<slug>: la ubicacion nunca sale del navegador. Sin JavaScript queda la primera pieza y el
// selector de zonas, que funciona con enlaces.
(function () {
  var EVERY = 8000;
  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll("[data-house]").forEach(function (box) {
    var items = box.querySelectorAll("[data-house-item]");
    var pause = box.querySelector("[data-house-pause]");
    if (items.length > 1 && !still) {
      var i = 0, held = false, stopped = false;
      var show = function (n) { items.forEach(function (el, k) { el.hidden = k !== n; }); };
      var tick = setInterval(function () { if (!held && !stopped) { i = (i + 1) % items.length; show(i); } }, EVERY);
      ["mouseenter", "focusin"].forEach(function (ev) { box.addEventListener(ev, function () { held = true; }); });
      ["mouseleave", "focusout"].forEach(function (ev) { box.addEventListener(ev, function () { held = false; }); });
      if (pause) {
        pause.hidden = false;
        pause.addEventListener("click", function () {
          stopped = !stopped;
          pause.setAttribute("aria-pressed", stopped ? "true" : "false");
          if (stopped) clearInterval(tick);
        });
      }
    }
    var locate = box.querySelector("[data-house-locate]");
    var msg = box.querySelector("[data-house-msg]");
    if (!locate || !("geolocation" in navigator) || !window.fetch) return;
    locate.hidden = false;
    var say = function (text) { if (msg) { msg.textContent = text; msg.hidden = false; } };
    locate.addEventListener("click", function () {
      locate.disabled = true;
      navigator.geolocation.getCurrentPosition(function (pos) {
        fetch("/zonas.json", { credentials: "omit" }).then(function (r) { return r.json(); }).then(function (data) {
          var slug = nearest(pos.coords.latitude, pos.coords.longitude, data);
          var to = encodeURIComponent(locate.getAttribute("data-path") || "/");
          window.location.href = "/zona/" + (slug || "olvidar") + "?to=" + to;
        }).catch(function () { locate.disabled = false; say("—"); });
      }, function () { locate.disabled = false; say("—"); }, { maximumAge: 600000, timeout: 10000 });
    });
  });

  // Misma cuenta que house.nearest en Python: municipio mas cercano dentro del radio (haversine).
  function nearest(lat, lon, data) {
    var best = null, bestKm = data.radius_km, rad = Math.PI / 180;
    data.zones.forEach(function (z) {
      z.towns.forEach(function (t) {
        var dp = (t[1] - lat) * rad, dl = (t[2] - lon) * rad;
        var a = Math.pow(Math.sin(dp / 2), 2) + Math.cos(lat * rad) * Math.cos(t[1] * rad) * Math.pow(Math.sin(dl / 2), 2);
        var km = 6371 * 2 * Math.asin(Math.sqrt(a));
        if (km <= bestKm) { best = z.slug; bestKm = km; }
      });
    });
    return best;
  }
})();
