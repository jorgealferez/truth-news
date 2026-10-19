"""IGAE: extracto real de ejecucion del Presupuesto del Estado hasta el 31 de agosto de 2026."""

from pathlib import Path

import httpx

from truthnews.data import igae

XLSX = (Path(__file__).parent / "fixtures" / "igae_extracto_2026_08.xlsx").read_bytes()


def test_parse_real_extract_matches_igae_ratios():
    ex = igae.parse(XLSX, "https://igae/x.xlsx")
    assert ex.periodo == "2026-08" and ex.hasta == "31 de agosto de 2026" and ex.url == "https://igae/x.xlsx"
    # Los porcentajes se calculan aqui y coinciden con las columnas 3/1 y 3/7 que publica la IGAE.
    assert ex.total_gastos.creditos == 462162489 and ex.total_gastos.ejecucion == 60.7
    assert ex.total_gastos.variacion == 12.7
    assert ex.total_inversiones.ejecucion == 27.1 and ex.total_inversiones.variacion == 8.9
    defensa = next(p for p in ex.inversiones if p.nombre == "DEFENSA")
    assert defensa.ejecucion == 22.0 and defensa.variacion == 14.5
    assert len(ex.gastos) == 37 and all(p.nombre != "TOTALES" for p in ex.gastos)
    irpf = next(p for p in ex.ingresos if p.nombre.startswith("Impuesto sobre la renta de las"))
    assert irpf.creditos == 51629206 and irpf.pagos == 57002140
    assert ex.total_ingresos.obligaciones == 304411154


def test_partida_edge_cases():
    p = igae.Partida("Fondo de contingencia", 512019, 0, 0, 0)
    assert p.ejecucion == 0.0 and p.variacion is None
    assert igae.Partida("x", 0, 5, 5, 5).ejecucion is None
    assert igae._num("-") == 0.0 and igae._period("sin fecha", "2026") == ("", "")
    assert igae._period("HASTA EL 31 DE BRUMARIO", "2026") == ("", "")


def test_parse_rejects_other_files():
    assert igae.parse(b"no es un excel") is None


def test_latest_follows_first_xlsx_link_and_fails_closed():
    page = (
        '<a href="/sitios/igae/Documents/EXTRACTO%2008-26.pdf">pdf</a>'
        '<a href="/sitios/igae/Documents/EXTRACTO%20AGOSTO%202026%20%28EXCEL%29.xlsx">xlsx</a>'
        '<a href="/sitios/igae/Documents/EXTRACTO%20JULIO%202026%20%28EXCEL%29.xlsx">xlsx</a>'
    )
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.endswith(".aspx"):
            return httpx.Response(200, text=page)
        return httpx.Response(200, content=XLSX)

    ex = igae.latest(httpx.MockTransport(handler))
    assert ex.periodo == "2026-08" and "AGOSTO" in ex.url and seen[0] == igae.PAGE
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    assert igae.latest(down) is None and igae.latest_url(down) == ""
    nolink = httpx.MockTransport(lambda r: httpx.Response(200, text="<p>sin enlaces</p>"))
    assert igae.latest(nolink) is None

    def broken(request):
        if request.url.path.endswith(".aspx"):
            return httpx.Response(200, text=page)
        return httpx.Response(404)

    assert igae.latest(httpx.MockTransport(broken)) is None
