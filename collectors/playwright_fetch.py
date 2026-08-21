"""
playwright_fetch.py — Rendu de pages JS / contournement anti-bot léger.

Pour les sources que urllib ne peut pas récupérer (JavaScript, 403 simple) :
rend la page dans un Chromium headless et renvoie le HTML, archivé tel quel
(raw_documents). Réutilisable par n'importe quel collecteur (ex. CDG30, futures
sources immo/RH). NB : un edge anti-bot fort (Akamai/Cloudflare détectant le
headless, ex. emploi-collectivites.fr) reste bloqué → nécessiterait stealth/proxy.

Requiert playwright et son Chromium, qui ne sont PAS dans requirements.txt — ils
pèsent un navigateur entier et aucun collecteur livré n'en dépend. Dans le venv
de l'instance, sur la machine qui en a besoin :

    venv/bin/pip install playwright   puis   venv/bin/playwright install chromium

L'import est différé jusqu'à l'ouverture de la session : un moteur sans
playwright s'importe et tourne normalement, seul ce fetcher échoue si on l'ouvre.

    from .playwright_fetch import PlaywrightFetcher
    with PlaywrightFetcher() as f:
        html = f.fetch("https://www.cdg30.fr/...", source="cdg30")
"""
from .archive import archive_bytes, _BROWSER_UA
from .db import get_conn

DEFAULT_TIMEOUT = 40000


class PlaywrightFetcher:
    """Session navigateur réutilisable (ouvre Chromium une fois pour un lot d'URLs)."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def fetch(self, url: str, *, source: str, wait_until: str = "networkidle",
              wait_ms: int = 2000, timeout: int = DEFAULT_TIMEOUT,
              archive: bool = True) -> str | None:
        """Rend la page et renvoie le HTML. Archive le brut si archive=True."""
        page = self._browser.new_page(user_agent=_BROWSER_UA, locale="fr-FR")
        try:
            resp = page.goto(url, wait_until=wait_until, timeout=timeout)
            status = resp.status if resp else None
            page.wait_for_timeout(wait_ms)
            html = page.content()
        except Exception as e:
            print(f"  [playwright][erreur] {url} → {e}")
            return None
        finally:
            page.close()

        if status and status >= 400:
            print(f"  [playwright] {url} → HTTP {status} (bloqué ?)")
        if archive and html:
            conn = get_conn()
            try:
                res = archive_bytes(conn, html.encode("utf-8"), source=source,
                                    url=url, doc_type="html", http_status=status)
                conn.commit()
                flag = "déjà archivé" if res["deduped"] else f"NOUVEAU → {res['local_path']}"
                print(f"  [playwright] {url} ({len(html)} o, HTTP {status}) — {flag}")
            finally:
                conn.close()
        return html


def fetch_rendered(url: str, *, source: str, **kw) -> str | None:
    """Rendu d'une seule URL (ouvre/ferme un navigateur). Pour un lot, préférer PlaywrightFetcher."""
    with PlaywrightFetcher() as f:
        return f.fetch(url, source=source, **kw)
