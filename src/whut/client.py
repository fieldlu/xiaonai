"""WHUT WebVPN 客户端 — 支持统一认证自动登录 + cookie 双重兜底。"""

import re
import logging

import httpx

from config import bot_config

logger = logging.getLogger(__name__)

WEBVPN_BASE = "https://webvpn.whut.edu.cn"

# 统一认证相关 URL（WHUT 使用 CAS + Wengine WebVPN）
AUTH_BASE = "https://auth.whut.edu.cn"
AUTH_LOGIN = f"{AUTH_BASE}/lyuapServer/login"
AUTH_NEEDCAPTCHA = f"{AUTH_BASE}/lyuapServer/needCaptcha"
AUTH_KICK = f"{AUTH_BASE}/lyuapServer/kick"

COOKIE_NAME = "wengine_vpn_ticketwebvpn_whut_edu_cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class WebVPNClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._ticket: str = getattr(bot_config, 'whut_vpn_ticket', '')
        self._login_lock = False  # 防止并发登录
        self._proxy: str | None = getattr(bot_config, 'webvpn_proxy', None) or None

    # ---- public API ----

    async def get_page(self, webvpn_url: str, max_text_len: int = 3000) -> str:
        _, text = await self._get_page(webvpn_url, max_text_len)
        return text

    async def get_page_html(self, webvpn_url: str) -> str:
        html, _ = await self._get_page(webvpn_url, 0, raw_html=True)
        return html

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ---- internal ----

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            cookies = {}
            if self._ticket:
                cookies[COOKIE_NAME] = self._ticket
            self._client = httpx.AsyncClient(
                follow_redirects=False,
                proxy=getattr(bot_config, 'webvpn_proxy', None) or None,  # 自己控制重定向以便检查登录态
                timeout=30,
                cookies=cookies,
                headers=HEADERS,
            )
        return self._client

    async def _get_page(self, webvpn_url: str, max_text_len: int = 0, raw_html: bool = False) -> tuple[str, str]:
        client = await self._get_client()
        resp = await client.get(webvpn_url)

        if self._is_login_redirect(resp):
            if not self._ticket:
                ok = await self._do_login()
                if not ok:
                    return ("WebVPN login failed, check credentials or manually update ticket.",) * 2
                await self._reset_client()
                client = await self._get_client()
                resp = await client.get(webvpn_url)

        return self._parse_response(resp, max_text_len, raw_html)

    def _is_login_redirect(self, resp: httpx.Response) -> bool:
        """判断是否被重定向到了登录页。"""
        loc = resp.headers.get("location", "")
        if loc and ("login" in loc.lower() or "auth" in loc.lower()):
            return True
        if resp.status_code == 200 and resp.url.host == WEBVPN_BASE.split("//")[1]:
            if "统一身份认证" in resp.text or "请登录" in resp.text:
                return True
        return "login" in str(resp.url) and resp.url.host == WEBVPN_BASE.split("//")[1]

    # ---- auto-login ----

    async def _do_login(self) -> bool:
        """通过统一认证自动登录，返回是否成功。"""
        if not bot_config.whut_username or not bot_config.whut_password:
            logger.warning("WHUT credentials not configured")
            return False

        if self._login_lock:
            return False
        self._login_lock = True
        try:
            return await self._login_flow()
        finally:
            self._login_lock = False

    async def _login_flow(self) -> bool:
        """CAS login via zhlgd.whut.edu.cn with RSA-encrypted password."""
        username = getattr(bot_config, "whut_username", "")
        password = getattr(bot_config, "whut_password", "")
        if not username or not password:
            logger.warning("WHUT credentials not configured")
            return False

        import json as _json, re as _re, base64 as _b64
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa, padding as _padding
        from cryptography.hazmat.primitives import serialization as _serialization
        from cryptography.hazmat.backends import default_backend as _backend
        import random as _random

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=HEADERS, proxy=self._proxy) as c:
                # Step 1: Navigate to WebVPN -> redirects to CAS login
                import urllib.parse as _ul
                resp = await c.get("https://zhlgd.whut.edu.cn/tpass/login?service=" + _ul.quote(WEBVPN_BASE + "/login?cas_login=true", safe=""))
                html = resp.text

                # Step 2: Extract LT and execution from CAS login form
                lt_m = _re.search(r'name="lt"\s+value="([^"]+)"', html)
                exec_m = _re.search(r'name="execution"\s+value="([^"]+)"', html)
                if not lt_m:
                    logger.error("CAS: cannot find lt in login form")
                    return False
                lt = lt_m.group(1)
                execution = exec_m.group(1) if exec_m else "e1s1"

                # Step 3: Get RSA public key
                rsa_resp = await c.post(
                    WEBVPN_BASE.split("//")[0] + "//zhlgd.whut.edu.cn" + "/tpass/rsa?skipWechat=true",
                    headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                )
                try:
                    rsa_data = _json.loads(rsa_resp.text)
                    public_key_pem = rsa_data.get("publicKey", "")
                except Exception:
                    logger.error("CAS: failed to get RSA public key")
                    return False
                if not public_key_pem:
                    logger.error("CAS: empty public key")
                    return False

                # Step 4: RSA encrypt password
                der_key = _b64.b64decode(public_key_pem)
                pubkey = _serialization.load_der_public_key(der_key, backend=_backend())
                pw_bytes = password.encode('utf-8')
                encrypted = pubkey.encrypt(pw_bytes, _padding.PKCS1v15())
                rsa_encrypted = _b64.b64encode(encrypted).decode()

                # Step 5: Submit login form
                form_data = {
                    "lt": lt,
                    "execution": execution,
                    "_eventId": "submit",
                    "un": username,
                    "ul": len(username),
                    "pl": len(password),
                    "pd": password,
                    "rsa": rsa_encrypted,
                }
                login_resp = await c.post(
                    resp.url,  # POST to the CAS login URL
                    data=form_data,
                    headers={
                        **HEADERS,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": str(resp.url),
                    },
                )
                # Login success = redirect to webvpn with ticket
                logger.info(f"CAS POST result: status={login_resp.status_code}, url={str(login_resp.url)[:80]}")

                if "login" in str(login_resp.url).lower() and "webvpn" not in str(login_resp.url).lower():
                    # Still on CAS login page - check for error
                    err = _re.search(r'id="error"[^>]*>([^<]+)', login_resp.text)
                    if err:
                        logger.error(f"CAS login error: {err.group(1)}")
                    else:
                        logger.error("CAS login failed - still on login page")
                    return False

                # Step 6: We should now be back at webvpn with an auth ticket
                # If not, try accessing the portal
                if "webvpn" not in str(login_resp.url):
                    await c.get(WEBVPN_BASE + "/")

                # Step 7: Extract ticket
                ticket = None
                for cookie in c.cookies.jar:
                    if COOKIE_NAME in cookie.name:
                        ticket = cookie.value
                        break
                if ticket:
                    self._ticket = ticket
                    logger.info(f"CAS login successful, ticket: {ticket[:30]}...")
                    return True
                logger.error("CAS login: no ticket after flow")
                return False
        except Exception as e:
            logger.error(f"CAS login error: {e}")
            return False

    @staticmethod
    def _extract(html: str, pattern: str) -> str:
        m = re.search(pattern, html)
        return m.group(1) if m else ""

    async def _reset_client(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ---- response parsing ----

    def _parse_response(self, resp: httpx.Response, max_text_len: int, raw_html: bool) -> tuple[str, str]:
        content_type = resp.headers.get("content-type", "")
        try:
            if "gbk" in content_type or "gb2312" in content_type:
                html = resp.content.decode("gbk", errors="replace")
            else:
                html = resp.content.decode("utf-8", errors="replace")
        except Exception:
            html = resp.text if hasattr(resp, "text") else ""
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

        if raw_html:
            return html, ""

        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if max_text_len and len(text) > max_text_len:
            text = text[:max_text_len] + "..."

        return html, text


whut_client = WebVPNClient()
