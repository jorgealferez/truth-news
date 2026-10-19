/* Politica de cookies (ADR 0039): borra lo que el sitio guarda en este navegador (inventario en
   truthnews/web/legal.py). Sin JS el boton no hace nada; el navegador sigue pudiendo borrarlo. */
(function () {
  var btn = document.querySelector("[data-legal-clear]");
  if (!btn) return;
  btn.addEventListener("click", function () {
    document.cookie = "lang=; Max-Age=0; path=/; SameSite=Lax";
    try { localStorage.removeItem("nm_last_visit"); } catch (e) { /* modo privado: nada guardado */ }
    var ok = document.querySelector("[data-legal-cleared]");
    if (ok) ok.hidden = false;
  });
})();
