"""
Persistent Playwright Browser Session for KON Assistant.
Runs in a dedicated thread with its own asyncio.ProactorEventLoop (Windows),
maintains persistent state/cookies in data/browser_profile (never touching user Chrome profile),
and executes semantic browser actions without moving physical mouse or stealing keyboard focus.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional

from playwright.async_api import async_playwright, Playwright, BrowserContext, Page, Locator
from backend.core.logger import kon_logger


def normalize_text(text: str) -> str:
    """Removes accents, normalizes whitespace, and lowercases text."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ASCII", "ignore").decode("utf-8")
    return " ".join(ascii_text.lower().split())


class BrowserSession:
    """
    Thread-safe persistent Playwright browser session for KON.
    """

    def __init__(
        self,
        profile_dir: Optional[str] = None,
        headless: Optional[bool] = None,
    ) -> None:
        if profile_dir is None:
            base_dir = Path(__file__).resolve().parent.parent.parent
            self._profile_dir = base_dir / "data" / "browser_profile"
        else:
            self._profile_dir = Path(profile_dir)

        self._profile_dir.mkdir(parents=True, exist_ok=True)

        if headless is None:
            env_headless = os.getenv("KON_BROWSER_HEADLESS", "").lower().strip()
            self._headless = env_headless in ("1", "true", "yes")
        else:
            self._headless = headless

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._last_snapshot_elements: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        self._start_worker_thread()

    def _start_worker_thread(self) -> None:
        """Starts dedicated thread with ProactorEventLoop."""
        ready_evt = threading.Event()

        def _thread_target():
            self._loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(self._loop)
            self._is_running = True
            ready_evt.set()
            try:
                self._loop.run_forever()
            finally:
                self._is_running = False

        self._thread = threading.Thread(target=_thread_target, daemon=True, name="KON-BrowserSession-Worker")
        self._thread.start()
        ready_evt.wait(timeout=5.0)

    def call(self, coro: Any, timeout: float = 30.0) -> Any:
        """
        Executes an asynchronous coroutine inside the dedicated browser worker thread.
        Never blocks or conflicts with the main application/uvicorn event loop.
        """
        if not self._is_running or not self._loop:
            raise RuntimeError("BrowserSession worker loop não está em execução.")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    @staticmethod
    def validate_url(url: str) -> str:
        """
        Validates and cleans target URL. Enforces http/https schemes.
        """
        clean = (url or "").strip()
        if not clean:
            raise ValueError("URL não pode ser vazia.")
        if "://" in clean:
            if not clean.startswith(("http://", "https://")):
                raise ValueError(f"Esquema de URL não suportado: '{clean}'. Apenas http e https são permitidos.")
        else:
            if " " in clean or "." not in clean:
                raise ValueError(f"URL inválida ou malformada: '{clean}'.")
            clean = f"https://{clean}"

        parsed = urllib.parse.urlparse(clean)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"Esquema ou domínio inválido para navegação: '{clean}'.")
        return clean

    @staticmethod
    def verify_youtube_channel(current_url: str, current_title: str, expected_name: str) -> bool:
        """
        Verifies if current page is indeed the requested YouTube channel:
        - URL matches youtube.com/(@|channel/|c/|user/)
        - Title matches requested channel name (accent and case insensitive).
        """
        pattern = re.compile(r"youtube\.com/(?:@|channel/|c/|user/)", re.IGNORECASE)
        if not pattern.search(current_url):
            return False

        norm_title = normalize_text(current_title)
        norm_expected = normalize_text(expected_name)
        return norm_expected in norm_title

    async def _ensure_page(self) -> Page:
        """Ensures Playwright, persistent context, and page are active."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        needs_context = False
        if self._context is None:
            needs_context = True
        else:
            try:
                # Test context liveness
                _ = self._context.pages
            except Exception:
                needs_context = True

        if needs_context:
            launch_kwargs: Dict[str, Any] = {
                "user_data_dir": str(self._profile_dir),
                "headless": self._headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-default-browser-check",
                    "--no-first-run",
                ],
            }
            try:
                # Try system Google Chrome first
                self._context = await self._playwright.chromium.launch_persistent_context(
                    channel="chrome",
                    **launch_kwargs,
                )
            except Exception as ex_chrome:
                kon_logger.debug(f"[BROWSER_SESSION] Chrome nativo indisponível ({ex_chrome}), usando Chromium padrão.")
                self._context = await self._playwright.chromium.launch_persistent_context(
                    **launch_kwargs,
                )

        # Tab reuse / recovery
        if self._page is None or self._page.is_closed():
            active_pages = [p for p in self._context.pages if not p.is_closed()]
            if active_pages:
                self._page = active_pages[0]
            else:
                self._page = await self._context.new_page()

        return self._page

    async def _async_open(self, url: str) -> Dict[str, Any]:
        """Navigates to URL in the persistent tab."""
        validated_url = self.validate_url(url)
        page = await self._ensure_page()
        try:
            await page.goto(validated_url, wait_until="domcontentloaded", timeout=25000)
        except Exception as err:
            kon_logger.warning(f"[BROWSER_SESSION] Aviso no goto({validated_url}): {err}")

        title = await page.title()
        return {
            "ok": True,
            "url": page.url,
            "title": title,
            "message": f"Navegador KON em '{page.url}' ({title}).",
        }

    async def _async_search(
        self,
        query: str,
        site: str = "youtube",
        channels_only: bool = False,
    ) -> Dict[str, Any]:
        """Performs search on YouTube or Google and extracts candidates."""
        page = await self._ensure_page()
        encoded = urllib.parse.quote_plus(query.strip())
        site_norm = site.lower().strip()

        if site_norm == "youtube":
            if channels_only:
                target_url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%253D%253D"
            else:
                target_url = f"https://www.youtube.com/results?search_query={encoded}"
        else:
            target_url = f"https://www.google.com/search?q={encoded}"

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(1.2)
        except Exception as err:
            kon_logger.warning(f"[BROWSER_SESSION] Aviso no search({target_url}): {err}")

        # Extract top candidates
        candidates = await self._extract_search_candidates(page, site_norm)
        norm_q = normalize_text(query)

        # Check ambiguity: multiple candidates and no single exact match
        exact_matches = [c for c in candidates if normalize_text(c.get("title", "")) == norm_q]
        is_ambiguous = len(candidates) > 1 and len(exact_matches) != 1

        title = await page.title()
        return {
            "ok": True,
            "site": site_norm,
            "query": query,
            "channels_only": channels_only,
            "url": page.url,
            "title": title,
            "candidates": candidates[:5],
            "ambiguous": is_ambiguous,
            "message": f"Busca realizada por '{query}'. {len(candidates)} candidatos encontrados.",
        }

    async def _extract_search_candidates(self, page: Page, site: str) -> List[Dict[str, Any]]:
        """Extracts search result items directly from page DOM."""
        if site == "youtube":
            js_code = """
            () => {
                const items = [];
                // 1. Channel renderers
                const channelEls = document.querySelectorAll('ytd-channel-renderer');
                for (const el of channelEls) {
                    if (items.length >= 5) break;
                    const titleEl = el.querySelector('#text, #channel-title');
                    const linkEl = el.querySelector('a#main-link, a');
                    if (titleEl && linkEl) {
                        items.push({
                            type: 'channel',
                            title: titleEl.innerText.trim(),
                            url: linkEl.href,
                        });
                    }
                }
                // 2. Video renderers
                const videoEls = document.querySelectorAll('ytd-video-renderer');
                for (const el of videoEls) {
                    if (items.length >= 5) break;
                    const titleEl = el.querySelector('#video-title');
                    if (titleEl) {
                        items.push({
                            type: 'video',
                            title: titleEl.innerText.trim(),
                            url: titleEl.href || (titleEl.closest('a') ? titleEl.closest('a').href : ''),
                        });
                    }
                }
                // 3. Fallback links
                if (items.length === 0) {
                    const links = document.querySelectorAll('a#video-title, a.yt-simple-endpoint');
                    for (const l of links) {
                        if (items.length >= 5) break;
                        const t = l.innerText.trim();
                        if (t && l.href) {
                            items.push({ type: 'link', title: t, url: l.href });
                        }
                    }
                }
                return items;
            }
            """
        else:
            js_code = """
            () => {
                const items = [];
                const blocks = document.querySelectorAll('div.g, div[data-hveid]');
                for (const b of blocks) {
                    if (items.length >= 5) break;
                    const h3 = b.querySelector('h3');
                    const a = b.querySelector('a');
                    if (h3 && a && a.href) {
                        items.push({
                            type: 'result',
                            title: h3.innerText.trim(),
                            url: a.href,
                        });
                    }
                }
                return items;
            }
            """
        try:
            res = await page.evaluate(js_code)
            return res if isinstance(res, list) else []
        except Exception as err:
            kon_logger.debug(f"[BROWSER_SESSION] Erro ao extrair candidatos: {err}")
            return []

    async def _async_snapshot(self) -> Dict[str, Any]:
        """Captures lightweight semantic DOM snapshot with up to 25 interactive elements."""
        page = await self._ensure_page()
        title = await page.title()
        url = page.url

        js_code = """
        () => {
            const results = [];
            const candidates = document.querySelectorAll('button, a[href], input, select, textarea, [role="button"], [role="link"], ytd-channel-renderer, ytd-video-renderer');
            let id = 1;
            for (const el of candidates) {
                if (id > 25) break;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const style = window.getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') continue;

                let text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.value || '').trim();
                text = text.replace(/\\s+/g, ' ').substring(0, 100);
                let role = el.getAttribute('role') || el.tagName.toLowerCase();
                let href = el.getAttribute('href') || '';

                results.push({
                    id: id++,
                    tag: el.tagName.toLowerCase(),
                    role: role,
                    text: text,
                    href: href,
                });
            }
            return results;
        }
        """
        elements: List[Dict[str, Any]] = []
        try:
            raw_elements = await page.evaluate(js_code)
            if isinstance(raw_elements, list):
                elements = raw_elements
        except Exception as err:
            kon_logger.debug(f"[BROWSER_SESSION] Erro no snapshot DOM: {err}")

        # Cache element mapping
        self._last_snapshot_elements = {item["id"]: item for item in elements if "id" in item}

        return {
            "ok": True,
            "title": title,
            "url": url,
            "count": len(elements),
            "elements": elements,
            "message": f"Snapshot de '{title}' ({len(elements)} elementos interativos).",
        }

    async def _async_click(
        self,
        element_id: Optional[int] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        selector: Optional[str] = None,
        verify_channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Clicks an element using semantic locator (without moving physical mouse)."""
        page = await self._ensure_page()
        old_url = page.url
        old_title = await page.title()

        locator: Optional[Locator] = None

        if element_id is not None:
            el_data = self._last_snapshot_elements.get(int(element_id))
            if el_data:
                tag = el_data.get("tag", "")
                text = el_data.get("text", "")
                href = el_data.get("href", "")
                if href:
                    locator = page.locator(f'{tag}[href="{href}"]').first
                elif text:
                    locator = page.locator(f'{tag}:has-text("{text[:30]}")').first
            if locator is None:
                locator = page.locator(f"button, a, input").nth(int(element_id) - 1)

        elif role and name:
            locator = page.get_by_role(role, name=name).first
        elif name:
            locator = page.get_by_text(name, exact=False).first
        elif selector:
            locator = page.locator(selector).first

        if locator is None:
            return {
                "ok": False,
                "error": "Nenhum seletor, role/name ou element_id válido foi fornecido.",
                "url": page.url,
                "title": await page.title(),
                "changed": False,
            }

        try:
            await locator.click(timeout=10000)
            await asyncio.sleep(0.8)
        except Exception as err:
            return {
                "ok": False,
                "error": f"Falha ao clicar no elemento: {err}",
                "url": page.url,
                "title": await page.title(),
                "changed": False,
            }

        new_url = page.url
        new_title = await page.title()
        changed = (new_url != old_url or new_title != old_title)

        result: Dict[str, Any] = {
            "ok": True,
            "url": new_url,
            "title": new_title,
            "changed": changed,
            "message": f"Clique executado. URL atual: '{new_url}'.",
        }

        if verify_channel:
            is_verified = self.verify_youtube_channel(new_url, new_title, verify_channel)
            result["channel_verified"] = is_verified
            if not is_verified:
                result["ok"] = False
                result["message"] = (
                    f"Clique efetuado, mas o canal '{verify_channel}' não foi verificado na página destino. "
                    f"URL: {new_url}, Título: {new_title}."
                )

        return result

    async def _async_type_text(
        self,
        element_id: Optional[int] = None,
        selector: Optional[str] = None,
        text: str = "",
        submit: bool = False,
    ) -> Dict[str, Any]:
        """Types text into an element via locator (without physical keyboard)."""
        page = await self._ensure_page()
        locator: Optional[Locator] = None

        if element_id is not None:
            el_data = self._last_snapshot_elements.get(int(element_id))
            if el_data:
                tag = el_data.get("tag", "")
                locator = page.locator(f"{tag}").nth(int(element_id) - 1)
            else:
                locator = page.locator("input, textarea").nth(int(element_id) - 1)
        elif selector:
            locator = page.locator(selector).first
        else:
            locator = page.locator("input[type='text'], input:not([type]), textarea, input[type='search']").first

        try:
            await locator.fill(text, timeout=8000)
            if submit:
                await locator.press("Enter")
                await asyncio.sleep(0.8)
        except Exception as err:
            return {
                "ok": False,
                "error": f"Falha ao digitar no elemento: {err}",
                "url": page.url,
                "title": await page.title(),
            }

        return {
            "ok": True,
            "text": text,
            "submitted": submit,
            "url": page.url,
            "title": await page.title(),
            "message": f"Texto digitado com sucesso{' e enviado' if submit else ''}.",
        }

    async def _async_go_back(self) -> Dict[str, Any]:
        """Navigates back in browser history."""
        page = await self._ensure_page()
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=15000)
        except Exception as err:
            kon_logger.debug(f"[BROWSER_SESSION] Erro no go_back: {err}")
        return {
            "ok": True,
            "url": page.url,
            "title": await page.title(),
            "message": "Navegado para a página anterior.",
        }

    async def _async_reload(self) -> Dict[str, Any]:
        """Reloads current page."""
        page = await self._ensure_page()
        try:
            await page.reload(wait_until="domcontentloaded", timeout=15000)
        except Exception as err:
            kon_logger.debug(f"[BROWSER_SESSION] Erro no reload: {err}")
        return {
            "ok": True,
            "url": page.url,
            "title": await page.title(),
            "message": "Página recarregada.",
        }

    async def _async_close(self) -> None:
        """Closes page, context, and Playwright session."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        self._page = None
        self._context = None
        self._playwright = None

    # -------------------------------------------------------------------------
    # Synchronous Public Interface (Thread-Safe)
    # -------------------------------------------------------------------------

    def open(self, url: str, timeout: float = 30.0) -> Dict[str, Any]:
        return self.call(self._async_open(url), timeout=timeout)

    def search(
        self,
        query: str,
        site: str = "youtube",
        channels_only: bool = False,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        return self.call(self._async_search(query, site=site, channels_only=channels_only), timeout=timeout)

    def snapshot(self, timeout: float = 15.0) -> Dict[str, Any]:
        return self.call(self._async_snapshot(), timeout=timeout)

    def click(
        self,
        element_id: Optional[int] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        selector: Optional[str] = None,
        verify_channel: Optional[str] = None,
        timeout: float = 20.0,
    ) -> Dict[str, Any]:
        return self.call(
            self._async_click(
                element_id=element_id,
                role=role,
                name=name,
                selector=selector,
                verify_channel=verify_channel,
            ),
            timeout=timeout,
        )

    def type_text(
        self,
        element_id: Optional[int] = None,
        selector: Optional[str] = None,
        text: str = "",
        submit: bool = False,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        return self.call(
            self._async_type_text(
                element_id=element_id,
                selector=selector,
                text=text,
                submit=submit,
            ),
            timeout=timeout,
        )

    def go_back(self, timeout: float = 15.0) -> Dict[str, Any]:
        return self.call(self._async_go_back(), timeout=timeout)

    def reload(self, timeout: float = 15.0) -> Dict[str, Any]:
        return self.call(self._async_reload(), timeout=timeout)

    def close(self, timeout: float = 10.0) -> None:
        """Shuts down browser context and terminates background worker loop."""
        with self._lock:
            if not self._is_running:
                return
            try:
                self.call(self._async_close(), timeout=timeout)
            except Exception as err:
                kon_logger.debug(f"[BROWSER_SESSION] Erro ao fechar sessão: {err}")

            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            self._is_running = False


# -----------------------------------------------------------------------------
# Singleton Management
# -----------------------------------------------------------------------------
_GLOBAL_BROWSER_SESSION: Optional[BrowserSession] = None
_SESSION_LOCK = threading.Lock()


def get_browser_session() -> BrowserSession:
    """Returns the singleton persistent BrowserSession."""
    global _GLOBAL_BROWSER_SESSION
    with _SESSION_LOCK:
        if _GLOBAL_BROWSER_SESSION is None or not _GLOBAL_BROWSER_SESSION._is_running:
            _GLOBAL_BROWSER_SESSION = BrowserSession()
        return _GLOBAL_BROWSER_SESSION


def has_browser_session() -> bool:
    """Checks whether an active BrowserSession exists."""
    global _GLOBAL_BROWSER_SESSION
    return _GLOBAL_BROWSER_SESSION is not None and _GLOBAL_BROWSER_SESSION._is_running


def close_browser_session() -> None:
    """Closes the singleton BrowserSession if active."""
    global _GLOBAL_BROWSER_SESSION
    with _SESSION_LOCK:
        if _GLOBAL_BROWSER_SESSION is not None:
            try:
                _GLOBAL_BROWSER_SESSION.close()
            except Exception as err:
                kon_logger.debug(f"[BROWSER_SESSION] Erro ao fechar singleton: {err}")
            _GLOBAL_BROWSER_SESSION = None
