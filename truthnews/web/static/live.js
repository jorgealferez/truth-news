/* Ultimo minuto (peticion del usuario 2026-10-19): recalca lo nuevo sin molestar.
   - Marca "Nuevo" lo publicado desde la ultima visita (solo en este navegador; sin cookies ni rastreo).
   - Cada 2 min pregunta a /ahora.json y, si hay algo nuevo, muestra un boton discreto: nunca recarga sola.
   Sin JS la franja se ve igual, solo sin estas marcas. */
(function () {
  var band = document.querySelector(".breaking");
  if (!band) return;
  var KEY = "nm_last_visit";
  var last = 0;
  try { last = parseInt(localStorage.getItem(KEY) || "0", 10) || 0; } catch (e) { last = 0; }
  if (last) {
    var n = 0;
    band.querySelectorAll("li[data-ts]").forEach(function (li) {
      if (parseInt(li.getAttribute("data-ts"), 10) > last) {
        li.classList.add("is-new");
        var pill = li.querySelector(".bk-new");
        if (pill) pill.hidden = false;
        n++;
      }
    });
    var count = band.querySelector(".bk-newcount");
    if (n && count) { count.textContent = " · " + count.getAttribute("data-tpl").replace("{n}", n); count.hidden = false; }
  }
  try { localStorage.setItem(KEY, String(Date.now())); } catch (e) { /* modo privado: sin marcas */ }

  var latest = parseInt(band.getAttribute("data-latest") || "0", 10) || 0;
  var fresh = band.querySelector(".bk-fresh");
  if (!fresh || !window.fetch) return;
  fresh.addEventListener("click", function () { location.reload(); });
  function check() {
    if (document.hidden) return;
    fetch("/ahora.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (d && d.latest > latest) fresh.hidden = false;
    }).catch(function () {});
  }
  setInterval(check, 120000);
  document.addEventListener("visibilitychange", check);
})();
