"""
平台B解析器 (万博体育 ManBetX)
支持 Playwright 浏览器自动化登录 + Cookie 持久化 + 灵活多策略HTML解析。

数据获取策略:
- 优先从文件加载cookie（免登录）
- cookie失效时使用Playwright自动登录
- SPA API 拦截（导航 AISports 页面捕获 JSON 响应）
- 直接 API 调用（aiohttp）
- Playwright + HTML 解析（兜底）
"""

import asyncio
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from bs4 import BeautifulSoup

from .base_spider import BaseSpider

from .providers.manbetx_provider import ManBetXProvider


# 稳定的浏览器启动参数，避免资源加载挂起导致页面无法完整展示
STABLE_BROWSER_ARGS = [
    '--no-sandbox',
    '--disable-blink-features=AutomationControlled',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--disable-extensions',
    '--disable-background-timer-throttling',
    '--disable-features=TranslateUI',
    '--ignore-certificate-errors',
]

# 页面加载时拦截的非必要资源类型，减少网络挂起
BLOCKED_RESOURCE_TYPES = frozenset({'image', 'font', 'media'})


class PlatformBParser(BaseSpider):
    """平台B解析器 (万博体育)，支持Playwright登录、cookie持久化、CSS选择器灵活配置"""

    def __init__(self, config: Dict[str, Any], logger):
        super().__init__(config, logger)
        self.platform_name = "platform_b"

        platform_config = config.get('platforms', {}).get('platform_b', {})
        self.base_url = platform_config.get('base_url', '').rstrip('/')
        self.odds_base_url = platform_config.get('odds_base_url', '').rstrip('/') or self.base_url
        self.login_url = platform_config.get('login_url', '/login')
        self.login_api = platform_config.get('login_api', '')
        self.odds_endpoint = platform_config.get('odds_endpoint', '/sports/football')
        self.credentials = platform_config.get('credentials', {})
        self.captcha_config = platform_config.get('captcha', {})
        self.click_captcha_config = platform_config.get('click_captcha', {})
        self.cookie_config = platform_config.get('cookie_login', {})
        self.login_popup_config = platform_config.get('login_popup', {})
        self.use_playwright_flag = platform_config.get('use_playwright', True)
        self.pw_config = platform_config.get('playwright', {})
        self.selectors = platform_config.get('selectors', {})
        self.timeout = platform_config.get('timeout', 30)
        self.full_login_url = f"{self.base_url}/{self.login_api.lstrip('/')}" if self.login_api else f"{self.base_url}/{self.login_url.lstrip('/')}"
        self.full_odds_url = f"{self.odds_base_url}/{self.odds_endpoint.lstrip('/')}"
        self._playwright_verified_at: float = 0.0

    # ==================== 主入口 ====================

    async def crawl_matches(self, platform_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.logger.info(f"开始爬取平台数据: {platform_config['name']}")

        if not await self._ensure_login():
            self.logger.error("登录失败，无法爬取万博体育数据")
            self.logger.info("提示：请确保在中国IP环境下运行，或在浏览器登录后导出cookie")
            return []

        # 策略1: SPA API 拦截（导航到 AISports SPA，自动截获 match API 响应）
        matches = await self._crawl_spa_api()
        if matches:
            self.logger.info(f"SPA API 拦截成功: {len(matches)} 场比赛")
            return matches

        # 策略2: 直接 API 调用（aiohttp）
        self.logger.info("SPA 未获取数据，尝试直接 API 调用...")
        matches = await self._crawl_direct_api()
        if matches:
            self.logger.info(f"直接 API 调用成功: {len(matches)} 场比赛")
            return matches

        # 策略3: Playwright + HTML 解析
        self.logger.info("API 调用也未获取数据，尝试 HTML 解析...")
        html = await self._fetch_odds_page()
        if not html:
            self.logger.error("获取赔率页面失败 — 所有策略均未获取到数据")
            return []

        if self._is_forbidden_page(html):
            self.logger.error("IP被万博体育封锁（forbidden页面）")
            return []

        try:
            soup = self.parse_html(html)
            matches = self.extract_match_info(soup)
            self.logger.info(f"HTML 解析: {len(matches)} 场比赛")
            return matches
        except Exception as e:
            self.logger.error(f"解析页面失败: {str(e)}")
            return []

    # ==================== 登录流程 ====================

    async def _ensure_login(self) -> bool:
        if self.is_logged_in:
            if self._playwright_verified_at and (time.time() - self._playwright_verified_at) < 300:
                return True
            if await self._verify_login_state():
                return True
            self.is_logged_in = False

        # 1) 优先cookie登录
        if self.cookie_config.get('enabled', False):
            if await self._load_cookies_from_file():
                if await self._verify_login_state():
                    self.is_logged_in = True
                    self.logger.info("万博体育 cookie 登录成功")
                    return True
                self.logger.warning("Cookie文件无效或已过期")

        # 2) Playwright自动登录
        if self.credentials.get('username') and self.credentials.get('password'):
            self.logger.info("尝试Playwright自动登录万博体育...")
            if await self._login_with_playwright():
                self.is_logged_in = True
                return True

        # 3) API登录（兜底）
        if self.login_api and self.credentials.get('username'):
            self.logger.info("尝试API登录...")
            if await self.login(self.full_login_url, self.credentials, self.captcha_config):
                self.is_logged_in = True
                return True

        self.logger.error("所有登录方式均失败")
        self.logger.info("请在浏览器登录后导出cookie到 data/platform_b_cookies.json")
        return False

    async def _load_cookies_from_file(self) -> bool:
        """从文件加载platform_b的cookie到session"""
        try:
            cookie_file = self.cookie_config.get('cookie_file', '')
            if not cookie_file:
                return False
            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)
            if not os.path.exists(cookie_path):
                self.logger.info(f"Cookie文件不存在: {cookie_path}")
                return False

            with open(cookie_path, 'r', encoding='utf-8') as f:
                cookies_data = json.load(f)

            placeholder_patterns = ['your_', 'replace_', 'placeholder', 'xxx', 'here']
            valid_cookies = []
            for c in cookies_data:
                if isinstance(c, dict):
                    val = c.get('value', '')
                    if not any(p in val.lower() for p in placeholder_patterns):
                        valid_cookies.append(c)

            if not valid_cookies:
                self.logger.warning("Cookie文件中无有效cookie")
                return False

            from yarl import URL
            loaded_domains = set()
            for cookie in valid_cookies:
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                if not (name and value):
                    continue
                # 使用cookie自身的domain，而非统一用base_url
                cookie_domain = cookie.get('domain', '')
                if cookie_domain and cookie_domain not in loaded_domains:
                    # 构造该domain的URL用于cookie注入
                    domain_url = f"https://{cookie_domain.lstrip('.')}"
                    try:
                        self.session.cookie_jar.update_cookies(
                            {name: value},
                            response_url=URL(domain_url)
                        )
                        loaded_domains.add(cookie_domain)
                    except Exception:
                        pass
                # 也注入到base_url和odds_base_url
                self.session.cookie_jar.update_cookies(
                    {name: value},
                    response_url=URL(self.base_url)
                )
                if self.odds_base_url != self.base_url:
                    self.session.cookie_jar.update_cookies(
                        {name: value},
                        response_url=URL(self.odds_base_url)
                    )

            self.logger.info(f"已从文件加载 {len(valid_cookies)} 个万博体育cookie"
                             f"{' (已同步到两个域名)' if self.odds_base_url != self.base_url else ''}")
            return True
        except Exception as e:
            self.logger.warning(f"加载cookie文件失败: {str(e)}")
            return False

    async def _verify_login_state(self) -> bool:
        """验证万博体育登录状态（优先检查数据域名，回退登录域名）"""
        try:
            verify_url = self.config.get('platforms', {}).get('platform_b', {}).get('login_verify_endpoint', '')
            if verify_url:
                full_url = f"{self.base_url}/{verify_url.lstrip('/')}" if not verify_url.startswith('http') else verify_url
                try:
                    async with self.session.get(full_url, headers=self.get_random_headers(),
                                                allow_redirects=False, timeout=15) as resp:
                        if resp.status in (401, 403, 302, 301):
                            return False
                        if resp.status == 200:
                            return True
                except Exception:
                    pass

            # 优先通过数据域名验证登录状态（用户指明的真实数据页面）
            verify_targets = [self.full_odds_url]
            if self.odds_base_url != self.base_url:
                verify_targets.append(self.full_login_url)

            for target_url in verify_targets:
                try:
                    headers = self.get_random_headers()
                    headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
                    async with self.session.get(
                        target_url, headers=headers, allow_redirects=False, timeout=15
                    ) as resp:
                        if resp.status in (302, 301, 401, 403):
                            continue
                        if resp.status != 200:
                            continue
                        body = await resp.text()
                        if self._is_forbidden_page(body):
                            continue
                        has_password = 'type="password"' in body
                        if has_password:
                            continue
                        logged_in_keywords = ['我的账户', '个人中心', '会员中心', '账户余额', '退出']
                        if any(kw in body for kw in logged_in_keywords):
                            return True
                        has_login_title = bool(re.search(r'<title[^>]*>.*?(登录|login).*?</title>', body, re.I))
                        if has_login_title:
                            continue
                        return True
                except Exception:
                    continue

            return False
        except Exception as e:
            self.logger.warning(f"验证登录状态异常: {str(e)}")
            return False

    async def _login_with_playwright(self) -> bool:
        """使用Playwright自动化登录万博体育（弹窗登录模式）

        流程：
        1. 打开 https://cn.fhuhjdsp.com/app/index
        2. 等待登录弹窗出现
        3. 在弹窗中自动填写账号密码
        4. 提交登录
        5. 处理验证码
        6. 等待弹窗关闭，确认登录成功
        7. 保存cookie
        """
        try:
            from playwright.async_api import async_playwright

            self.logger.info(f"Playwright弹窗登录: {self.full_login_url}")

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    channel='chrome',
                    headless=False,
                    args=STABLE_BROWSER_ARGS,
                )
                context_options = {
                    'user_agent': random.choice(self.user_agents) if self.user_agents else (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                    ),
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'zh-CN',
                }
                context = await browser.new_context(**context_options)
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => {
                            const plugins = [1, 2, 3, 4, 5];
                            plugins.item = () => null;
                            plugins.namedItem = () => null;
                            plugins.refresh = () => {};
                            return plugins;
                        }
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['zh-CN', 'zh', 'en-US', 'en']
                    });
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'Win32'
                    });
                    Object.defineProperty(navigator, 'hardwareConcurrency', {
                        get: () => 8
                    });
                    Object.defineProperty(navigator, 'deviceMemory', {
                        get: () => 8
                    });
                    delete window.__playwright__binding__;
                    delete window.__pwInitScripts;
                    window.chrome = {
                        runtime: {},
                        loadTimes: function() {},
                        csi: function() {},
                        app: {}
                    };
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                    );
                    Object.defineProperty(navigator, 'connection', {
                        get: () => ({
                            effectiveType: '4g',
                            rtt: 50,
                            downlink: 10,
                            saveData: false
                        })
                    });
                """)

                page = await context.new_page()
                page.set_default_timeout(60000)

                # 拦截非必要资源（图片/字体/媒体），减少网络挂起
                await page.route('**/*', self._block_resource)
                # 收集浏览器控制台错误，便于排查页面加载问题
                console_errors = []
                page.on('console', lambda msg: console_errors.append(
                    f"[{msg.type}] {msg.text}"
                ) if msg.type in ('error', 'warning') else None)
                page.on('pageerror', lambda err: self.logger.error(f"浏览器JS错误: {err}"))

                # 导航到首页（登录弹窗通过点击"欢迎登录"触发）
                # 使用 domcontentloaded 替代 networkidle：后者会因 CDN 资源不可达而永久挂起
                self.logger.info("正在打开万博体育首页...")
                try:
                    await page.goto(self.full_login_url, wait_until='domcontentloaded', timeout=30000)
                except Exception:
                    self.logger.warning("首页加载超时，尝试 base_url...")
                    try:
                        await page.goto(self.base_url, wait_until='domcontentloaded', timeout=30000)
                    except Exception:
                        self.logger.error("base_url 也无法加载，可能IP被封锁")
                        await self._save_failure_screenshot(page, 'page_load_failed')

                await page.wait_for_timeout(3000)

                # 检查IP限制
                if await self._detect_forbidden_page(page):
                    self.logger.error("万博体育检测到海外IP，登录被阻止")
                    await self._save_failure_screenshot(page, 'forbidden')
                    await browser.close()
                    return False

                # 点击"欢迎登录"触发登录弹窗
                await self._trigger_login_popup(page)

                # 等待登录弹窗出现
                login_popup = await self._wait_for_login_popup(page)
                if login_popup is None:
                    # 弹窗未出现，检查是否已登录
                    self.logger.info("未检测到登录弹窗，检查是否已登录...")
                    if await self._check_logged_in_on_index(page):
                        self.logger.info("检测到已登录状态（cookie有效）")
                        return await self._save_playwright_cookies(context, browser)
                    self.logger.error("未检测到登录弹窗且未登录，无法继续")
                    if console_errors:
                        self.logger.warning(f"浏览器控制台错误: {console_errors[:10]}")
                    await self._save_failure_screenshot(page, 'no_login_popup')
                    await browser.close()
                    return False

                # 在弹窗中填写登录表单
                password_field = await self._fill_login_form_in_popup(page, login_popup)
                if password_field is None:
                    self.logger.error("无法在弹窗中找到登录表单字段")
                    if console_errors:
                        self.logger.warning(f"浏览器控制台错误: {console_errors[:10]}")
                    await self._save_failure_screenshot(page, 'no_form_fields')
                    await browser.close()
                    return False

                # 处理点击式验证码
                if self.click_captcha_config.get('enabled', False):
                    await self._handle_click_captcha(page)

                # 提交登录表单
                await self._submit_login_form(page, password_field)
                await page.wait_for_timeout(3000)

                # 检查登录错误
                if await self._detect_login_error(page):
                    self.logger.error("检测到登录错误提示（账号或密码错误等）")
                    await self._save_failure_screenshot(page, 'login_error')
                    await browser.close()
                    return False

                # 等待弹窗关闭（登录成功标志）
                self.logger.info("等待登录弹窗关闭...")
                if not await self._wait_for_popup_close(page, login_popup):
                    self.logger.warning("弹窗未自动关闭，尝试手动关闭...")
                    await self._close_popup_manually(page)

                # 刷新页面以获取登录后的完整状态
                await page.wait_for_timeout(2000)
                try:
                    await page.goto(self.full_login_url, wait_until='domcontentloaded', timeout=15000)
                    await page.wait_for_timeout(3000)
                except Exception:
                    pass

                # 保存截图用于诊断
                await self._save_failure_screenshot(page, 'after_login')

                # 验证登录状态
                if await self._check_logged_in_on_index(page):
                    self.logger.info(f"弹窗登录成功，当前URL: {page.url}")
                    self._playwright_verified_at = time.time()
                    # 导航到 SPA 页面以获取 API 域名 cookie（mxq01pc.43b8y8.com）
                    try:
                        self.logger.info(f"导航到 SPA 页面获取跨域 cookie...")
                        await page.goto(self.full_odds_url, wait_until='domcontentloaded', timeout=20000)
                        await page.wait_for_timeout(5000)
                    except Exception as e:
                        self.logger.warning(f"SPA 导航失败(不影响登录): {e}")
                    return await self._save_playwright_cookies(context, browser)

                # 即使检查不到登录标识，也尝试保存cookie（可能登录已成功但UI不同）
                self.logger.warning("未检测到明确登录标识，但仍尝试保存cookie...")
                await self._save_failure_screenshot(page, 'login_verify_failed')
                # 尝试保存cookie并返回（让后续爬取来判断是否真正登录）
                return await self._save_playwright_cookies(context, browser)

        except ImportError:
            self.logger.error("Playwright 未安装，请运行: pip install playwright && playwright install")
            return False
        except Exception as e:
            import traceback
            self.logger.error(f"Playwright弹窗登录失败: {str(e)}\n{traceback.format_exc()}")

    async def _trigger_login_popup(self, page) -> None:
        """点击页面上的登录入口触发弹窗"""
        trigger_selectors = [
            '#wel_login_btn',
            'a:has-text("欢迎登录")',
            'a:has-text("登录")',
            '[onclick*="popupLoginModal"]',
            '[onclick*="login"]',
        ]
        for sel in trigger_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=3000)
                if el and await el.is_visible():
                    self.logger.info(f"点击登录触发按钮: {sel}")
                    await el.click()
                    await page.wait_for_timeout(2000)
                    return
            except Exception:
                continue
        self.logger.info("未找到显式登录触发按钮，尝试直接等待弹窗...")

    async def _wait_for_login_popup(self, page) -> Optional[Any]:
        """等待登录弹窗出现并返回弹窗元素"""
        popup_selectors = self.login_popup_config.get('dialog_selectors', [
            '.modal', '.dialog', '[class*="login-dialog"]', '[class*="login-modal"]',
            '.ant-modal', '.el-dialog', 'div[class*="login"]',
        ])
        popup_timeout = self.login_popup_config.get('popup_timeout_ms', 10000)

        for sel in popup_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=popup_timeout)
                if el and await el.is_visible():
                    self.logger.info(f"检测到登录弹窗 (选择器: {sel})")
                    return el
            except Exception:
                continue

        # 回退：查找任何包含密码输入框的可见容器
        try:
            pw_input = await page.wait_for_selector('input[type="password"]', timeout=5000)
            if pw_input and await pw_input.is_visible():
                self.logger.info("通过密码输入框定位到登录弹窗")
                return pw_input
        except Exception:
            pass

        return None

    async def _fill_login_form_in_popup(self, page, popup_element) -> Optional[Any]:
        """在登录弹窗中仿人填写账号密码，返回密码输入框"""
        username = self.credentials.get('username', '')
        password = self.credentials.get('password', '')

        # 新域名默认显示"手机登录"标签，需先切换到"密码登录"
        pwd_tab_selectors = [
            'text=密码登录', '[data-tab="password"]', '.tab-password',
            'a:has-text("密码登录")', 'li:has-text("密码登录")', 'span:has-text("密码登录")',
            '.login-tab-item:has-text("密码")',
        ]
        for sel in pwd_tab_selectors:
            try:
                tab = await page.wait_for_selector(sel, timeout=3000)
                if tab and await tab.is_visible():
                    self.logger.info(f"切换到密码登录标签: {sel}")
                    await tab.click()
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

        username_selectors = [
            'input[placeholder*="账号" i]', 'input[placeholder*="用户" i]',
            'input[placeholder*="手机" i]', 'input[placeholder*="邮箱" i]',
            'input[name="username"]', 'input[name="account"]', 'input[name="phone"]',
            'input[autocomplete="username"]', 'input[id*="username"]', 'input[id*="account"]',
        ]
        username_field = None
        for sel in username_selectors:
            try:
                inp = await page.wait_for_selector(sel, timeout=3000)
                if inp and await inp.is_visible():
                    username_field = inp
                    break
            except Exception:
                continue

        if not username_field:
            inputs = await page.query_selector_all('input:not([type="password"]):not([type="hidden"])')
            for inp in inputs:
                if await inp.is_visible():
                    username_field = inp
                    break

        password_selectors = [
            'input[type="password"]', 'input[placeholder*="密码" i]',
            'input[name="password"]', 'input[autocomplete="current-password"]',
        ]
        password_field = None
        for sel in password_selectors:
            try:
                inp = await page.wait_for_selector(sel, timeout=3000)
                if inp and await inp.is_visible():
                    password_field = inp
                    break
            except Exception:
                continue

        if not username_field or not password_field:
            return None

        # 仿人输入用户名
        await username_field.click()
        await page.wait_for_timeout(random.randint(200, 500))
        await page.keyboard.type(username, delay=random.randint(50, 150))
        self.logger.info("已在弹窗中输入用户名")

        await page.wait_for_timeout(random.randint(300, 800))

        # 仿人输入密码
        await password_field.click()
        await page.wait_for_timeout(random.randint(200, 500))
        await page.keyboard.type(password, delay=random.randint(50, 150))
        self.logger.info("已在弹窗中输入密码")

        await page.wait_for_timeout(random.randint(300, 600))
        return password_field

    async def _wait_for_popup_close(self, page, popup_element) -> bool:
        """等待登录弹窗关闭"""
        max_wait = 30
        start = time.time()
        while time.time() - start < max_wait:
            try:
                # 检测弹窗是否已隐藏
                is_visible = await popup_element.is_visible()
                if not is_visible:
                    self.logger.info("登录弹窗已关闭")
                    return True
            except Exception:
                # popup_element 如果不再存在于DOM
                self.logger.info("登录弹窗已从DOM移除")
                return True

            # 同时检查密码输入框是否还可见
            try:
                pw = await page.query_selector('input[type="password"]')
                if pw and not await pw.is_visible():
                    self.logger.info("密码输入框不可见，弹窗已关闭")
                    return True
            except Exception:
                pass

            await asyncio.sleep(1)
        return False

    async def _close_popup_manually(self, page) -> None:
        """手动关闭登录弹窗"""
        close_selectors = [
            '.modal .close', '.dialog .close', '.modal-header .close',
            '[class*="close"]', '.ant-modal-close', '.el-dialog__close',
            '.layui-layer-close', 'button.close', 'a.close',
            '[aria-label="Close"]', '[aria-label="关闭"]',
        ]
        for sel in close_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el and await el.is_visible():
                    self.logger.info(f"点击关闭按钮: {sel}")
                    await el.click()
                    await page.wait_for_timeout(2000)
                    return
            except Exception:
                continue

        # 按 Escape 键
        try:
            await page.keyboard.press('Escape')
            self.logger.info("按 Escape 关闭弹窗")
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    async def _check_logged_in_on_index(self, page) -> bool:
        """检查页面是否处于已登录状态"""
        try:
            body_text = await page.evaluate("() => document.body.innerText || ''")

            # 未登录特征：存在"欢迎登录"字样或弹出登录触发
            if '欢迎登录' in body_text:
                pw_input = await page.query_selector('input[type="password"]')
                if pw_input and await pw_input.is_visible():
                    self.logger.info("检测到密码输入框可见，未登录")
                    return False

            # 检查已登录特征
            logged_in_indicators = [
                '我的账户', '个人中心', '会员中心', '账户余额',
                '退出', 'logout', '用户中心', '亲爱的',
                '用户名', '安全退出',
            ]
            found = [kw for kw in logged_in_indicators if kw in body_text]
            if found:
                self.logger.info(f"检测到已登录标识: {found}")
                # 确认没有密码输入框
                pw_input = await page.query_selector('input[type="password"]')
                if pw_input and await pw_input.is_visible():
                    self.logger.info("但密码输入框仍可见，可能还在登录弹窗中")
                    return False
                return True

            # 检查 URL 是否跳转到首页而非 register 页
            current_url = page.url
            if '/home/index' in current_url or current_url.rstrip('/') == self.base_url.rstrip('/'):
                self.logger.info(f"URL 已跳转至 {current_url}，视为已登录")
                return True

            self.logger.info(f"未找到登录标识，页面文本前200字符: {body_text[:200]}")
            return False
        except Exception as e:
            self.logger.debug(f"检查登录状态异常: {e}")
            return False

    async def _detect_forbidden_page(self, page) -> bool:
        try:
            title = await page.title()
            if 'forbidden' in title.lower():
                return True
            content = await page.content()
            return '访问受限' in content or 'FORBIDDEN' in content
        except Exception:
            return False

    async def _detect_login_error(self, page) -> bool:
        """检测登录页面上的错误提示信息"""
        try:
            error_keywords = [
                '账号或密码错误', '用户名或密码错误', '密码错误', '账号错误',
                '登录失败', '验证失败', '账户不存在', '账号已锁定', '账号被冻结',
                'Invalid credentials', 'Login failed', 'Wrong password', 'incorrect',
            ]
            page_text = await page.evaluate("() => document.body.innerText || ''")
            page_text_lower = page_text.lower()
            for keyword in error_keywords:
                if keyword.lower() in page_text_lower:
                    self.logger.warning(f"检测到错误提示关键词: '{keyword}'")
                    snippet = page_text[:500]
                    self.logger.info(f"页面文本预览: {snippet}")
                    return True
            return False
        except Exception as e:
            self.logger.debug(f"检测登录错误异常: {e}")
            return False

    async def _submit_login_form(self, page, password_field) -> bool:
        """多重策略提交登录表单，任一种成功即返回True"""
        strategies = [
            ('Enter键提交', self._submit_by_enter),
            ('JS表单提交', self._submit_by_js_submit),
            ('dispatchEvent点击', self._submit_by_dispatch_event),
            ('按钮直接点击', self._submit_by_button_click),
        ]

        for name, strategy in strategies:
            try:
                if await strategy(page, password_field):
                    self.logger.info(f"登录提交成功 ({name})")
                    return True
                self.logger.debug(f"提交策略 '{name}' 已执行，等待页面响应...")
            except Exception as e:
                self.logger.debug(f"提交策略 '{name}' 异常: {e}")

        self.logger.warning("所有提交策略均失败，无法提交登录表单")
        return False

    async def _submit_by_enter(self, page, password_field) -> bool:
        """在密码框按Enter提交"""
        await password_field.focus()
        await page.wait_for_timeout(random.randint(100, 300))
        await page.keyboard.press('Enter')
        return True

    async def _submit_by_js_submit(self, page, password_field) -> bool:
        """通过JavaScript直接提交表单"""
        result = await page.evaluate("""
            () => {
                const pw = document.querySelector('input[type="password"]');
                if (!pw) return false;
                const form = pw.closest('form');
                if (form) {
                    form.submit();
                    return true;
                }
                // 尝试触发最近的button
                const allBtns = document.querySelectorAll('button');
                for (const b of allBtns) {
                    if (b.textContent.includes('登录') || b.textContent.includes('登入') || b.type === 'submit') {
                        b.click();
                        return true;
                    }
                }
                return false;
            }
        """)
        return bool(result)

    async def _submit_by_dispatch_event(self, page, password_field) -> bool:
        """通过dispatchEvent模拟真实点击事件"""
        result = await page.evaluate("""
            () => {
                const allBtns = document.querySelectorAll(
                    'button, .login-btn, .submit-btn, input[type="submit"]'
                );
                let btn = null;
                for (const b of allBtns) {
                    if (b.textContent.includes('登录') || b.textContent.includes('登入') ||
                        b.type === 'submit' || b.className.includes('login')) {
                        btn = b;
                        break;
                    }
                }
                if (!btn) return false;
                const rect = btn.getBoundingClientRect();
                const opts = { bubbles: true, cancelable: true, clientX: rect.x + 10, clientY: rect.y + 5 };
                btn.dispatchEvent(new MouseEvent('mousedown', opts));
                btn.dispatchEvent(new MouseEvent('mouseup', opts));
                btn.dispatchEvent(new MouseEvent('click', opts));
                return true;
            }
        """)
        return bool(result)

    async def _submit_by_button_click(self, page, password_field) -> bool:
        """通过Playwright原生click方法点击按钮"""
        btn_selectors = [
            'button[type="submit"]', 'button:has-text("登录")', 'button:has-text("登入")',
            'button:has-text("LOGIN")', 'a:has-text("登录")', '.login-btn', '.submit-btn',
            'input[type="submit"]', 'button[class*="login"]',
        ]
        for sel in btn_selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(force=True)
                return True
        return False

    async def _handle_click_captcha(self, page):
        """处理点击式验证码"""
        try:
            from .captcha_solver import ClickCaptchaSolver
            solver = ClickCaptchaSolver(self.click_captcha_config, logger=self.logger)
            await solver.detect_and_solve(page)
        except Exception as e:
            self.logger.warning(f"点击验证码处理异常: {e}")

    async def _save_playwright_cookies(self, context, browser) -> bool:
        """保存Playwright浏览器cookie到文件并注入到session"""
        try:
            browser_cookies = await context.cookies()
            self.logger.info(f"获取到 {len(browser_cookies)} 个cookie")

            if self.session is not None:
                from yarl import URL
                for cookie in browser_cookies:
                    self.session.cookie_jar.update_cookies(
                        {cookie['name']: cookie['value']},
                        response_url=URL(self.base_url)
                    )
                    if self.odds_base_url != self.base_url:
                        self.session.cookie_jar.update_cookies(
                            {cookie['name']: cookie['value']},
                            response_url=URL(self.odds_base_url)
                        )

            self._save_cookies(browser_cookies)
            await browser.close()
            return True
        except Exception as e:
            self.logger.warning(f"保存cookie失败: {e}")
            await browser.close()
            return False

    def _save_cookies(self, cookies: list) -> None:
        """保存cookie到文件"""
        try:
            cookie_file = self.cookie_config.get('cookie_file', '')
            if not cookie_file:
                return
            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)
            cookies_data = [
                {
                    'name': c.get('name', ''),
                    'value': c.get('value', ''),
                    'domain': c.get('domain', ''),
                    'path': c.get('path', '/'),
                    'secure': c.get('secure', False),
                    'httpOnly': c.get('httpOnly', False),
                    'sameSite': c.get('sameSite', 'Lax'),
                }
                for c in cookies
            ]
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookies_data, f, ensure_ascii=False, indent=4)
            self.logger.info(f"已保存 {len(cookies_data)} 个cookie到 {cookie_path}")
        except Exception as e:
            self.logger.warning(f"保存cookie到文件失败: {e}")

    # ==================== 数据爬取 ====================

    async def _fetch_odds_page(self) -> Optional[str]:
        """获取赔率页面HTML（以登录态请求）"""
        try:
            if self.use_playwright_flag:
                return await self._crawl_with_playwright()
            else:
                return await self._crawl_with_aiohttp()
        except Exception as e:
            self.logger.error(f"获取赔率页面失败: {e}")
            return None

    async def _crawl_with_aiohttp(self) -> Optional[str]:
        html = await self.make_request(self.full_odds_url, 'GET')
        if html and self._is_forbidden_page(html):
            self.logger.error("IP被万博封锁，请使用中国IP")
            return None
        return html

    async def _crawl_with_playwright(self) -> Optional[str]:
        try:
            from playwright.async_api import async_playwright

            headless = self.pw_config.get('headless', True)
            wait_selector = self.pw_config.get('wait_selector', 'div, table')
            wait_timeout = self.pw_config.get('wait_timeout_ms', 15000)

            self.logger.info(f"Playwright渲染: {self.full_odds_url}")
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    channel='chrome', headless=headless,
                    args=STABLE_BROWSER_ARGS,
                )
                context_options = {
                    'user_agent': random.choice(self.user_agents) if self.user_agents else (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                    ),
                    'viewport': {'width': 1920, 'height': 1080},
                    'locale': 'zh-CN',
                }
                context = await browser.new_context(**context_options)

                # 将session中的cookie注入到Playwright（同时注入登录域和数据域）
                if self.session:
                    for cookie in self.session.cookie_jar:
                        base_cookie = {
                            'name': cookie.key,
                            'value': cookie.value,
                            'domain': cookie.get('domain', ''),
                            'path': cookie.get('path', '/'),
                        }
                        try:
                            await context.add_cookies([base_cookie])
                        except Exception:
                            continue
                        # 如果数据域名不同，也注入到数据域名
                        if self.odds_base_url != self.base_url:
                            try:
                                from urllib.parse import urlparse
                                odds_domain = urlparse(self.odds_base_url).hostname
                                odds_cookie = dict(base_cookie)
                                odds_cookie['domain'] = odds_domain
                                await context.add_cookies([odds_cookie])
                            except Exception:
                                continue

                page = await context.new_page()
                page.set_default_timeout(30000)

                # 拦截非必要资源 + 控制台错误收集
                await page.route('**/*', self._block_resource)
                console_errors = []
                page.on('console', lambda msg: console_errors.append(
                    f"[{msg.type}] {msg.text}"
                ) if msg.type in ('error', 'warning') else None)

                try:
                    await page.goto(self.full_odds_url, wait_until='domcontentloaded', timeout=30000)
                except Exception:
                    self.logger.warning("页面加载超时，尝试获取已有内容")
                    if console_errors:
                        self.logger.warning(f"浏览器控制台错误: {console_errors[:5]}")

                try:
                    await page.wait_for_selector(wait_selector, timeout=wait_timeout)
                except Exception:
                    self.logger.warning("等待目标元素超时，继续获取内容")

                await page.wait_for_timeout(3000)

                if await self._detect_forbidden_page(page):
                    self.logger.error("IP被万博封锁")
                    await self._save_failure_screenshot(page, 'forbidden_page')
                    await browser.close()
                    return None

                html = await page.content()
                await browser.close()
                return html

        except ImportError:
            return await self._crawl_with_aiohttp()
        except Exception as e:
            self.logger.error(f"Playwright爬取失败: {e}")
            return None

    async def _crawl_spa_api(self) -> List[Dict[str, Any]]:
        """
        使用 Playwright 导航到 AISports SPA 页面，拦截内部 API 响应获取赛事数据。

        万博体育的 AISports SPA 加载后会自动调用 mxq01pc.43b8y8.com 的
        /ai/game/matches API 获取赛事列表。关键依赖:
        1. 中国IP — 非中国IP会被重定向到 /home/forbidden
        2. 有效Cookie — 登录态cookie需注入到浏览器上下文

        Returns:
            标准化赛事数据列表
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.error("Playwright未安装，无法使用SPA API拦截")
            return []

        headless = self.pw_config.get('headless', True)
        wait_timeout = self.pw_config.get('wait_timeout_ms', 20000)

        self.logger.info(f"SPA API拦截模式: {self.full_odds_url}")

        provider = ManBetXProvider(filter_config={
            'sport_type': self.config.get('playwright_scraping', {}).get('filters', {}).get('sport_type'),
            'market_types': self.config.get('playwright_scraping', {}).get('filters', {}).get('market_types', []),
        })

        all_api_responses = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                channel='chrome', headless=headless,
                args=STABLE_BROWSER_ARGS,
            )
            context_options = {
                'user_agent': random.choice(self.user_agents) if self.user_agents else (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                ),
                'viewport': {'width': 1920, 'height': 1080},
                'locale': 'zh-CN',
            }
            context = await browser.new_context(**context_options)

            # 注入cookie到浏览器上下文
            if self.session:
                from urllib.parse import urlparse
                odds_hostname = urlparse(self.odds_base_url).hostname or ''
                api_domains = ['43b8y8.com', 'mxq01pc.43b8y8.com']

                for cookie in self.session.cookie_jar:
                    base = {
                        'name': cookie.key,
                        'value': cookie.value,
                        'domain': cookie.get('domain', ''),
                        'path': cookie.get('path', '/'),
                    }
                    # 原始域名
                    try:
                        await context.add_cookies([base])
                    except Exception:
                        pass
                    # 数据域名 (cn.fhuhjdsp.com)
                    if odds_hostname and odds_hostname not in str(base.get('domain', '')):
                        try:
                            c = dict(base)
                            c['domain'] = odds_hostname
                            await context.add_cookies([c])
                        except Exception:
                            pass
                    # API域名
                    for api_domain in api_domains:
                        try:
                            c = dict(base)
                            c['domain'] = api_domain
                            await context.add_cookies([c])
                        except Exception:
                            pass

            page = await context.new_page()
            page.set_default_timeout(60000)

            # 网络响应拦截 - 捕获所有JSON响应（主页面+弹窗页面）
            all_urls_logged = set()

            async def on_response(response):
                url = response.url
                content_type = response.headers.get('content-type', '')
                if 'json' not in content_type.lower():
                    return
                try:
                    body = await response.json()
                    if url not in all_urls_logged:
                        all_urls_logged.add(url)
                        self.logger.info(f"[SPA拦截] {response.status} {url}")
                    all_api_responses.append({
                        'url': url,
                        'status': response.status,
                        'body': body,
                    })
                except Exception:
                    pass

            page.on('response', on_response)

            # 监听从场馆点击打开的弹窗/新标签页
            async def on_new_page(new_page):
                self.logger.info(f"[SPA拦截] 检测到新页面: {new_page.url}")
                new_page.on('response', on_response)
                await new_page.route('**/*', self._block_resource)
                # 等待新页面加载
                try:
                    await new_page.wait_for_load_state('domcontentloaded', timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(5)  # 等待新页面上的 API 调用

            context.on('page', on_new_page)

            await page.route('**/*', self._block_resource)

            # 导航到 SPA 页面
            self.logger.info(f"导航到 SPA 页面: {self.full_odds_url}")
            try:
                await page.goto(self.full_odds_url, wait_until='domcontentloaded', timeout=30000)
            except Exception as e:
                self.logger.warning(f"SPA 页面加载超时: {e}")

            # 检测是否被重定向到 forbidden（IP被拦截的特征）
            current_url = page.url
            if 'forbidden' in current_url.lower():
                self.logger.error(f"SPA页面被重定向到: {current_url}")
                self.logger.error("IP被万博体育封锁（非中国IP），无法爬取")
                await browser.close()
                return []

            self.logger.info(f"等待 SPA 数据加载 ({wait_timeout}ms)...")
            await page.wait_for_timeout(wait_timeout)

            # 检查是否自动捕获到了比赛API响应
            match_api_responses = [r for r in all_api_responses if '/ai/home/matches' in r.get('url', '') or '/ai/game/matches' in r.get('url', '')]

            # ── 策略: 点击体育场馆触发体育模块加载 ──
            # SPA 页面是场馆大厅，需要点击体育场馆入口才会加载比赛数据和 API 调用
            if not match_api_responses and 'forbidden' not in current_url.lower():
                self.logger.info("未自动捕获比赛API，尝试点击体育场馆触发模块加载...")
                sports_venue_selectors = [
                    'text=新万博体育-体育',
                    'text=万博体育',
                    'text=新亚洲体育',
                    'text=亚洲体育',
                    '[class*="sport"]',
                    '[class*="game-item"]',
                    '.hall-item',
                    '.venue-item',
                ]
                clicked = False
                for sel in sports_venue_selectors:
                    try:
                        elem = await page.wait_for_selector(sel, timeout=3000)
                        if elem and await elem.is_visible():
                            self.logger.info(f"点击体育场馆: {sel}")
                            await elem.click()
                            clicked = True
                            # 等待场馆页面加载和 API 调用
                            await page.wait_for_timeout(8000)
                            break
                    except Exception:
                        continue

                if not clicked:
                    # 尝试通过 halls API 数据定位场馆元素
                    self.logger.info("未找到体育场馆元素，尝试 JS 定位...")
                    try:
                        clicked = await page.evaluate("""
                            () => {
                                const items = document.querySelectorAll('div, li, a, button');
                                for (const el of items) {
                                    const text = el.textContent || '';
                                    if (text.includes('体育') && !text.includes('彩票') &&
                                        !text.includes('真人') && !text.includes('电子') &&
                                        !text.includes('棋牌') && !text.includes('电竞')) {
                                        if (el.offsetParent !== null) {
                                            el.click();
                                            return true;
                                        }
                                    }
                                }
                                return false;
                            }
                        """)
                        if clicked:
                            self.logger.info("JS 触发体育场馆点击成功")
                            await page.wait_for_timeout(8000)
                    except Exception:
                        pass

                # 重新检查是否有新捕获的 match API 响应
                match_api_responses = [r for r in all_api_responses if '/ai/home/matches' in r.get('url', '') or '/ai/game/matches' in r.get('url', '')]

            # 如果 SPA 未自动触发比赛API（可能是页面部分加载但体育模块未初始化），
            # 尝试从页面通过 fetch 直接调用 API（仅在页面正常加载时有效）
            if not match_api_responses and 'forbidden' not in current_url.lower():
                self.logger.info("自动拦截未捕获比赛API，尝试页内直接调用...")
                from urllib.parse import urlencode
                api_params = {
                    'groupId': '1', 'gameSort': '1', 'virtualType': '2',
                    'oddsType': 'H',
                }
                api_base_url = "https://mxq01pc.43b8y8.com"

                for page_num in range(1, 2):
                    try:
                        params = dict(api_params)
                        api_url = f"{api_base_url}/ai/home/matches?{urlencode(params)}"

                        import json as _json
                        result = await page.evaluate(f"""
                            async () => {{
                                try {{
                                    const resp = await fetch({_json.dumps(api_url)}, {{
                                        credentials: 'include',
                                        headers: {{ 'Accept': 'application/json, text/plain, */*' }},
                                    }});
                                    if (!resp.ok) return {{ error: 'HTTP ' + resp.status }};
                                    return await resp.json();
                                }} catch (e) {{
                                    return {{ error: e.message }};
                                }}
                            }}
                        """)

                        if isinstance(result, dict) and result.get('error'):
                            self.logger.warning(f"页内API调用失败 (page={page_num}): {result['error']}")
                            break

                        self.logger.info(f"页内API调用成功 (page={page_num})")
                        all_api_responses.append({
                            'url': api_url, 'status': 200, 'body': result,
                        })

                        if isinstance(result, dict):
                            code_val = result.get('code')
                            if code_val is not None and code_val != 0 and code_val != 200:
                                self.logger.warning(
                                    f"API返回错误 code={code_val}: {result.get('msg', '')}"
                                )
                                break
                    except Exception as e:
                        self.logger.warning(f"页内API异常 (page={page_num}): {e}")
                        break

                # 重新检查：fetch 回退是否捕获到了比赛API响应
                match_api_responses = [r for r in all_api_responses if '/ai/home/matches' in r.get('url', '') or '/ai/game/matches' in r.get('url', '')]

            # ── 新增回退: 浏览器直接导航到 API URL ──
            # page.evaluate+fetch 在跨域时可能因 CORS 失败。
            # page.goto() 是顶级页面导航，不受 CORS 限制，且浏览器自动携带 cookie。
            if not match_api_responses and 'forbidden' not in current_url.lower():
                self.logger.info("页内 fetch 未返回数据，尝试页面导航到 API URL...")
                from urllib.parse import urlencode as _urlencode

                api_base_url = "https://mxq01pc.43b8y8.com"
                for page_num in range(1, 2):
                    try:
                        params = {
                            'groupId': '1', 'gameSort': '1', 'virtualType': '2',
                            'oddsType': 'H',
                        }
                        api_url = f"{api_base_url}/ai/home/matches?{_urlencode(params)}"

                        self.logger.info(f"直接导航 API (page={page_num}): {api_url}")
                        response = await page.goto(api_url, wait_until='domcontentloaded', timeout=15000)

                        if response and response.status == 200:
                            import json as _json
                            body_text = await page.evaluate('document.body.innerText')
                            if body_text and body_text.strip():
                                try:
                                    body = _json.loads(body_text)
                                    all_api_responses.append({
                                        'url': api_url, 'status': 200, 'body': body,
                                    })
                                    self.logger.info(f"导航API响应获取成功 (page={page_num})")
                                    if isinstance(body, dict):
                                        code_val = body.get('code')
                                        if code_val is not None and code_val != 0 and code_val != 200:
                                            self.logger.warning(
                                                f"导航API返回错误 code={code_val}: {body.get('msg', '')}"
                                            )
                                            break
                                    # 短暂随机延时，避免高频触发反爬
                                    import random as _random
                                    await page.wait_for_timeout(_random.randint(500, 1500))
                                    continue
                                except _json.JSONDecodeError as e:
                                    self.logger.warning(f"导航API JSON解析失败 (page={page_num}): {e}")
                                    self.logger.debug(f"原始文本前200字符: {body_text[:200]}")
                        else:
                            status = response.status if response else 'N/A'
                            self.logger.warning(f"导航API返回非200 (page={page_num}, status={status})")
                    except Exception as e:
                        self.logger.warning(f"导航API异常 (page={page_num}): {e}")
                        break

            # 保存截图用于诊断
            try:
                diag_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'diagnosis')
                os.makedirs(diag_dir, exist_ok=True)
                ts = __import__('time').strftime('%Y%m%d_%H%M%S')
                await page.screenshot(path=os.path.join(diag_dir, f'platform_b_spa_{ts}.png'), full_page=False)
            except Exception:
                pass

            await browser.close()

        self.logger.info(f"SPA拦截共捕获 {len(all_api_responses)} 个JSON响应")

        if not all_api_responses:
            return []

        # 保存原始响应用于诊断（使用时间戳文件名，避免覆盖）
        try:
            diag_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'diagnosis')
            os.makedirs(diag_dir, exist_ok=True)
            import json as _json
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            with open(os.path.join(diag_dir, f'platform_b_raw_responses_{ts}.json'), 'w', encoding='utf-8') as f:
                _json.dump(all_api_responses, f, ensure_ascii=False, indent=2, default=str)
            # 单独保存 match API 响应
            match_only = [r for r in all_api_responses if '/ai/home/matches' in r.get('url', '') or '/ai/game/matches' in r.get('url', '')]
            if match_only:
                with open(os.path.join(diag_dir, f'platform_b_match_api_{ts}.json'), 'w', encoding='utf-8') as f:
                    _json.dump(match_only, f, ensure_ascii=False, indent=2, default=str)
                self.logger.info(f"match API响应已单独保存, 共 {len(match_only)} 个")
        except Exception:
            pass

        # 解析所有捕获的响应
        all_matches = []
        seen_mids = set()
        for resp in all_api_responses:
            url = resp.get('url', '')
            body = resp.get('body', {})
            if not provider.can_handle(url):
                continue

            matches = provider.parse_matches_response(body)
            for m in matches:
                mid = m.get('mid', '')
                if mid and mid not in seen_mids:
                    seen_mids.add(mid)
                    all_matches.append(m)

            # 保存第一个成功的 match API 响应作为样本
            if matches:
                sample_dir = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    'data', 'sample_responses', 'MANBETX'
                )
                try:
                    os.makedirs(sample_dir, exist_ok=True)
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    ManBetXProvider.save_sample_response(
                        body, os.path.join(sample_dir, f'matches_{ts}.json')
                    )
                except Exception:
                    pass

        self.logger.info(f"SPA API 解析完成: {len(all_matches)} 场比赛 (去重后)")
        return all_matches

    async def _crawl_direct_api(self) -> List[Dict[str, Any]]:
        """
        直接调用 ai/home/matches API 获取赛事数据（使用 aiohttp）。

        当 SPA 页面数据无法正常加载时使用此方法。

        Returns:
            标准化赛事数据列表
        """
        api_base_urls = ["https://mxq01pc.43b8y8.com"]

        provider = ManBetXProvider(filter_config={
            'sport_type': self.config.get('playwright_scraping', {}).get('filters', {}).get('sport_type'),
            'market_types': self.config.get('playwright_scraping', {}).get('filters', {}).get('market_types', []),
        })

        headers = self.get_random_headers()
        headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Referer': f'{self.odds_base_url}/sports/AISports?isWindow=true',
            'Origin': self.odds_base_url,
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })

        api_params = {
            'groupId': '1', 'gameSort': '1', 'virtualType': '2',
            'oddsType': 'H',
        }

        all_matches = []
        seen_mids = set()

        for api_base in api_base_urls:
            if all_matches:
                break
            try:
                from urllib.parse import urlencode
                matches_url = f"{api_base}/ai/home/matches?{urlencode(api_params)}"

                async with self.session.get(
                    matches_url, headers=headers, timeout=15
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"API返回HTTP {resp.status}")
                        if resp.status in (401, 403):
                            break
                        continue

                    body = await resp.json()
                    if isinstance(body, dict):
                        code_val = body.get('code')
                        if code_val is not None and code_val != 0 and code_val != 200:
                            msg = body.get('msg', '')
                            self.logger.info(f"API业务错误: code={code_val} msg={msg}")
                            break

                    matches = provider.parse_matches_response(body)
                    if not matches:
                        self.logger.info("无比赛数据")
                        break

                    for m in matches:
                        mid = m.get('mid', '')
                        if mid and mid not in seen_mids:
                            seen_mids.add(mid)
                            all_matches.append(m)

                    self.logger.info(f"获取 {len(matches)} 场 (累计 {len(all_matches)})")

            except asyncio.TimeoutError:
                self.logger.warning("API超时")
            except Exception as e:
                self.logger.warning(f"API异常: {e}")
                break

        self.logger.info(f"直接API调用完成: {len(all_matches)} 场比赛")
        return all_matches

    async def _block_resource(self, route):
        """拦截非必要资源（图片/字体/媒体），CSS仍放行以保证页面渲染"""
        try:
            if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                await route.abort()
            else:
                await route.continue_()
        except Exception:
            pass  # 浏览器关闭时 route 已失效，忽略

    async def _save_failure_screenshot(self, page, tag: str):
        """登录或爬取失败时保存截图到 data/diagnosis/ 目录"""
        try:
            diag_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'diagnosis')
            os.makedirs(diag_dir, exist_ok=True)
            ts = time.strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(diag_dir, f'platform_b_{tag}_{ts}.png')
            await page.screenshot(path=filename, full_page=False)
            self.logger.info(f"失败截图已保存: {filename}")
        except Exception as e:
            self.logger.debug(f"保存截图失败: {e}")

    def _is_forbidden_page(self, html: str) -> bool:
        return '访问受限' in html or 'FORBIDDEN' in html or 'forbidden' in html.lower()[:200]

    # ==================== HTML解析 ====================

    def extract_match_info(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        matches = []
        try:
            rows = self._find_match_rows(soup)
            if not rows:
                self.logger.warning("未找到赛事行，分析页面结构...")
                self._diagnose_page_structure(soup)
                return matches

            for row in rows:
                match_data = self._parse_single_match(row)
                if match_data and self._is_valid_match(match_data):
                    matches.append(match_data)
        except Exception as e:
            self.logger.error(f"解析页面失败: {str(e)}")
        return matches

    def _find_match_rows(self, soup: BeautifulSoup) -> List:
        # 策略1: 使用配置的选择器
        row_sel = self.selectors.get('match_row', '')
        if row_sel:
            for css_sel in [s.strip() for s in row_sel.split(',')]:
                rows = soup.select(css_sel)
                if rows:
                    self.logger.debug(f"使用选择器 '{css_sel}' 找到 {len(rows)} 行")
                    return rows

        # 策略2: 通用table解析
        tables = soup.select('table')
        for table in tables:
            rows = table.select('tbody tr, tr')
            if rows:
                data_rows = [r for r in rows if r.select('td') and not r.select('th')]
                if len(data_rows) >= 3:
                    self.logger.debug(f"使用通用table找到 {len(data_rows)} 行")
                    return data_rows

        # 策略3: div-based布局
        div_containers = soup.select('div[class*="match"], div[class*="event"], div[class*="game"]')
        if div_containers and len(div_containers) >= 3:
            self.logger.debug(f"使用div布局找到 {len(div_containers)} 个容器")
            return div_containers

        # 策略4: 任何包含数字的行
        return soup.select('tr:has(td), div:has(span):has(text)')

    def _diagnose_page_structure(self, soup: BeautifulSoup):
        """诊断页面结构，输出关键元素帮助调试选择器"""
        for tag in ['table', 'div[class*="match"]', 'div[class*="event"]', 'div[class*="odds"]']:
            elems = soup.select(tag)
            if elems:
                self.logger.info(f"  发现 {len(elems)} 个 {tag} 元素")
                for i, elem in enumerate(elems[:2]):
                    classes = elem.get('class', [])
                    tid = elem.get('id', '')
                    text_preview = elem.get_text(strip=True)[:80]
                    self.logger.info(f"    [{i}] class={classes}, id={tid}, text='{text_preview}'")

    def _parse_single_match(self, element) -> Optional[Dict[str, Any]]:
        try:
            league = self._try_extract(element, 'league_name', default='未知联赛')
            home = self._try_extract(element, 'home_team', default='未知主队')
            away = self._try_extract(element, 'away_team', default='未知客队')
            match_time = self._try_extract_time(element)
            status = self._normalize_status(self._try_extract(element, 'match_status', default='未开始'))
            odds = self._extract_all_odds(element)

            return {
                'platform': self.platform_name,
                'league_name': league,
                'home_team': home,
                'away_team': away,
                'match_time': match_time,
                'match_status': status,
                'home_win_odds': odds.get('home_win'),
                'draw_odds': odds.get('draw'),
                'away_win_odds': odds.get('away_win'),
                'big_ball_odds': odds.get('big_ball'),
                'small_ball_odds': odds.get('small_ball'),
                'handicap': odds.get('handicap'),
                'collect_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        except Exception as e:
            self.logger.warning(f"解析单场比赛失败: {str(e)}")
            return None

    def _is_valid_match(self, match_data: Dict) -> bool:
        if match_data.get('home_team') in ('未知主队', '') and match_data.get('away_team') in ('未知客队', ''):
            return False
        has_odds = any(match_data.get(k) for k in ['home_win_odds', 'draw_odds', 'away_win_odds'])
        return has_odds

    # ==================== 字段提取 ====================

    def _try_extract(self, element, key: str, default: str = '') -> str:
        sel_str = self.selectors.get(key, '')
        if not sel_str:
            return default
        for css_sel in [s.strip() for s in sel_str.split(',')]:
            try:
                found = element.select_one(css_sel)
                if found:
                    text = found.get_text(strip=True)
                    if text:
                        return text
            except Exception:
                continue
        return default

    def _try_extract_raw(self, element, key: str):
        sel_str = self.selectors.get(key, '')
        if not sel_str:
            return None
        for css_sel in [s.strip() for s in sel_str.split(',')]:
            try:
                found = element.select_one(css_sel)
                if found:
                    return found
            except Exception:
                continue
        return None

    def _try_extract_time(self, element) -> str:
        raw = self._try_extract(element, 'match_time', default='')
        if not raw:
            all_text = element.get_text()
            time_match = re.search(r'(\d{2}:\d{2})', all_text)
            if time_match:
                raw = time_match.group(1)
        if not raw:
            return ''
        for fmt in ['%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M', '%m-%d %H:%M', '%d-%m %H:%M', '%H:%M']:
            try:
                return datetime.strptime(raw.strip(), fmt).strftime('%Y-%m-%d %H:%M')
            except ValueError:
                continue
        return raw.strip()

    def _extract_all_odds(self, element) -> Dict[str, Optional[float]]:
        result = {
            'home_win': self._extract_odds_value(element, 'home_odds'),
            'draw': self._extract_odds_value(element, 'draw_odds'),
            'away_win': self._extract_odds_value(element, 'away_odds'),
            'big_ball': self._extract_odds_value(element, 'over_odds'),
            'small_ball': self._extract_odds_value(element, 'under_odds'),
            'handicap': self._extract_odds_value(element, 'handicap_line'),
        }

        # 如果逐个提取失败，尝试从赔率容器批量提取数字
        if not any([result['home_win'], result['draw'], result['away_win']]):
            container = self._try_extract_raw(element, 'odds_1x2')
            if container:
                nums = re.findall(r'(\d+\.?\d*)', container.get_text(strip=True))
                nums = [float(n) for n in nums if float(n) > 1.0]
                if len(nums) >= 3:
                    result['home_win'] = nums[0]
                    result['draw'] = nums[1]
                    result['away_win'] = nums[2]

        # 如果还是没有，尝试从元素的所有文本中提取数字组
        if not any([result['home_win'], result['draw'], result['away_win']]):
            all_text = element.get_text()
            nums = re.findall(r'(\d+\.\d+)', all_text)
            nums = [float(n) for n in nums if 1.01 <= float(n) <= 100.0]
            if len(nums) >= 3:
                result['home_win'] = nums[0]
                result['draw'] = nums[1]
                result['away_win'] = nums[2]

        return result

    def _extract_odds_value(self, element, key: str) -> Optional[float]:
        found = self._try_extract_raw(element, key)
        if not found:
            return None
        text = found.get_text(strip=True)
        match = re.search(r'(\d+\.?\d*)', text)
        if not match:
            return None
        val = float(match.group(1))
        return val if val > 1.0 else None

    def _normalize_status(self, raw: str) -> str:
        status_map = {
            '未开始': '未开始', 'not_started': '未开始', 'scheduled': '未开始',
            '进行中': '进行中', 'live': '进行中', 'in_progress': '进行中', 'inplay': '进行中',
            '已结束': '已结束', 'finished': '已结束', 'ended': '已结束',
            '中场': '进行中', 'ht': '进行中', 'half_time': '进行中',
        }
        raw_lower = raw.lower()
        for key, value in status_map.items():
            if key in raw_lower:
                return value
        return '未开始'
