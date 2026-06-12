import base64
import re
from typing import Optional

from playwright.async_api import async_playwright

from ..config import settings


DEFAULT_USER_NAME = "\u5df2\u767b\u5f55\u6296\u97f3\u7528\u6237"
BAD_USER_NAMES = {
    "\u6211\u7684",
    "\u767b\u5f55",
    "\u641c\u7d22",
    "\u6d88\u606f",
    "\u53d1\u5e03",
    "\u76f4\u64ad",
}


class DouyinLoginManager:
    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None
        self.user_info = None
        self.login_url = "https://www.douyin.com/"

    async def ensure_page(self):
        if self.page and not self.page.is_closed():
            return

        await self.close()
        profile_dir = settings.DATA_DIR / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        await self._open_login_panel_if_needed()

    async def close(self):
        try:
            if self.page and not self.page.is_closed():
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.playwright:
                await self.playwright.stop()
        finally:
            self.playwright = None
            self.context = None
            self.page = None

    async def start(self):
        await self.ensure_page()
        return await self.status(include_screenshot=True)

    async def status(self, include_screenshot: bool = False):
        await self.ensure_page()
        user = await self._extract_user_info()
        if user:
            self.user_info = user
            return {"logged_in": True, "user": user, "qr_image": None}

        data = {"logged_in": False, "user": None, "qr_image": None}
        if include_screenshot:
            data["qr_image"] = await self._login_screenshot()
        return data

    async def get_cached_status(self):
        if self.user_info and self.user_info.get("avatar"):
            return {"logged_in": True, "user": self.user_info}
        if not self.context:
            await self.ensure_page()
        if self.context:
            user = await self._extract_user_info()
            if user:
                self.user_info = user
                return {"logged_in": True, "user": user}
        return {"logged_in": False, "user": None}

    async def logout(self):
        await self.ensure_page()
        try:
            if self.context:
                await self.context.clear_cookies()
            if self.page and not self.page.is_closed():
                await self.page.evaluate(
                    """() => {
                        try { localStorage.clear(); } catch (err) {}
                        try { sessionStorage.clear(); } catch (err) {}
                    }"""
                )
        finally:
            self.user_info = None
            await self.close()
        return {"logged_in": False, "user": None}

    async def _open_login_panel_if_needed(self):
        try:
            if await self._has_session_cookie():
                return

            selectors = [
                'button:has-text("\u767b\u5f55")',
                'div:has-text("\u767b\u5f55")',
                '[class*="login"]',
            ]
            for selector in selectors:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click(timeout=1000)
                    await self.page.wait_for_timeout(1500)
                    return
        except Exception:
            return

    async def _has_session_cookie(self):
        if not self.context:
            return False
        cookies = await self.context.cookies()
        names = {cookie.get("name") for cookie in cookies}
        return bool(names & {"sessionid", "sid_guard", "sid_tt", "passport_csrf_token"})

    async def _extract_user_info(self) -> Optional[dict]:
        if not self.page or self.page.is_closed():
            return None

        if not await self._has_session_cookie():
            return None

        try:
            await self._reveal_user_menu()
            await self.page.wait_for_timeout(700)
            info = await self.page.evaluate(self._profile_probe_js())
            name = self._normalize_name((info or {}).get("name"))
            avatar = (
                (info or {}).get("avatar")
                or await self._screenshot_avatar_element()
                or await self._extract_avatar_from_html()
            )
            return {"name": name, "avatar": avatar}
        except Exception:
            return {"name": DEFAULT_USER_NAME, "avatar": ""}

    def _normalize_name(self, name):
        clean = (name or "").strip()
        if not clean or clean in BAD_USER_NAMES:
            return DEFAULT_USER_NAME
        if any(word in clean for word in BAD_USER_NAMES):
            return DEFAULT_USER_NAME
        return clean[:30]

    def _profile_probe_js(self):
        return r"""() => {
            const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
            const badNames = new Set(["\u6211\u7684", "\u767b\u5f55", "\u641c\u7d22", "\u6d88\u606f", "\u53d1\u5e03", "\u76f4\u64ad"]);
            const absoluteUrl = (value) => {
                if (!value) return "";
                const raw = value.trim().replace(/^url\(["']?/, "").replace(/["']?\)$/, "");
                try { return new URL(raw, location.href).href; } catch (err) { return raw; }
            };
            const bestFromSrcset = (value) => {
                if (!value) return "";
                const first = value.split(",").map(x => x.trim().split(" ")[0]).find(Boolean);
                return absoluteUrl(first || "");
            };
            const imageUrl = (node) => {
                if (node.tagName === "IMG") {
                    return absoluteUrl(
                        node.currentSrc ||
                        node.src ||
                        node.getAttribute("data-src") ||
                        node.getAttribute("data-lazy-src") ||
                        bestFromSrcset(node.getAttribute("srcset"))
                    );
                }
                const bg = getComputedStyle(node).backgroundImage || "";
                if (bg && bg !== "none") return absoluteUrl(bg);
                return "";
            };
            const likelyUrl = (url) => /avatar|aweme|douyin|pstatp|byteimg|tos-|webcast/i.test(url || "");
            const likelyNode = (node) => {
                const text = [
                    node.className,
                    node.id,
                    node.getAttribute("aria-label"),
                    node.getAttribute("alt"),
                    node.getAttribute("title")
                ].join(" ");
                return /avatar|head|user|account|profile|\u5934\u50cf|\u7528\u6237|\u6211\u7684/i.test(text);
            };

            const candidates = Array.from(document.querySelectorAll(
                'img, [class*="avatar"], [class*="Avatar"], [class*="head"], [class*="user"], [class*="User"], [class*="account"], [class*="profile"]'
            ));
            let avatar = "";
            let fallbackAvatar = "";
            let name = "";

            for (const node of candidates) {
                const rect = node.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const src = imageUrl(node);
                if (src && !src.startsWith("data:") && likelyUrl(src)) {
                    if (!fallbackAvatar) fallbackAvatar = src;
                    if (!avatar && likelyNode(node) && rect.width >= 18 && rect.height >= 18 && rect.width <= 180 && rect.height <= 180) {
                        avatar = src;
                    }
                }

                const label = clean(node.getAttribute("aria-label") || node.getAttribute("title") || node.innerText);
                if (!name && label && label.length <= 30 && !badNames.has(label) && !/\u767b\u5f55|\u641c\u7d22|\u6d88\u606f|\u53d1\u5e03|\u76f4\u64ad/.test(label)) {
                    name = label;
                }
            }

            const metaName = clean(document.querySelector('meta[name="user:nickname"]')?.content);
            if (!name && metaName) name = metaName;
            if (!avatar) avatar = fallbackAvatar;
            return { name, avatar };
        }"""

    async def _reveal_user_menu(self):
        try:
            for selector in self._avatar_selectors():
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.hover(timeout=1000)
                    await self.page.wait_for_timeout(500)
                    return
        except Exception:
            return

    def _avatar_selectors(self):
        return [
            '[class*="avatar"]',
            '[class*="Avatar"]',
            '[class*="user"] img',
            '[class*="User"] img',
            '[class*="head"] img',
            'img[alt*="\u5934\u50cf"]',
            'img[alt*="\u7528\u6237"]',
            'img',
        ]

    async def _screenshot_avatar_element(self):
        try:
            for selector in self._avatar_selectors():
                elements = await self.page.query_selector_all(selector)
                for el in elements:
                    if not await el.is_visible():
                        continue
                    box = await el.bounding_box()
                    if not box:
                        continue
                    width = box.get("width", 0)
                    height = box.get("height", 0)
                    if width < 18 or height < 18 or width > 180 or height > 180:
                        continue
                    png = await el.screenshot(type="png")
                    encoded = base64.b64encode(png).decode("ascii")
                    return f"data:image/png;base64,{encoded}"
        except Exception:
            return ""
        return ""

    async def _extract_avatar_from_html(self):
        try:
            html = await self.page.content()
        except Exception:
            return ""

        patterns = [
            r'"avatar[^"]*"\s*:\s*"([^"]+)"',
            r'"url_list"\s*:\s*\[\s*"([^"]+)"',
            r'(https?:\\?/\\?/[^"\']+(?:avatar|aweme|douyin|pstatp|byteimg|tos-)[^"\']+\.(?:webp|png|jpe?g)[^"\']*)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if not match:
                continue
            url = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
            if url.startswith("//"):
                url = "https:" + url
            if url.startswith("http") and not url.startswith("data:"):
                return url
        return ""

    async def _login_screenshot(self):
        await self._open_login_panel_if_needed()
        await self.page.wait_for_timeout(800)
        png = await self.page.screenshot(full_page=False)
        encoded = base64.b64encode(png).decode("ascii")
        return f"data:image/png;base64,{encoded}"
