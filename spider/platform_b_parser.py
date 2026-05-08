"""
平台B解析器 (万博体育 ManBetX)
支持 Playwright 浏览器自动化登录 + Cookie 持久化 + 灵活多策略HTML解析。

当前环境IP可能被万博封锁（海外IP返回forbidden页面），代码支持在中国IP环境下正常运行：
- 优先从文件加载cookie（免登录）
- cookie失效时使用Playwright自动登录
- 支持手动登录回退
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


class PlatformBParser(BaseSpider):
    """平台B解析器 (万博体育)，支持Playwright登录、cookie持久化、CSS选择器灵活配置"""

    def __init__(self, config: Dict[str, Any], logger):
        super().__init__(config, logger)
        self.platform_name = "platform_b"

        platform_config = config.get('platforms', {}).get('platform_b', {})
        self.base_url = platform_config.get('base_url', '')
        self.login_url = platform_config.get('login_url', '/login')
        self.login_api = platform_config.get('login_api', '')
        self.odds_endpoint = platform_config.get('odds_endpoint', '/sports/football')
        self.credentials = platform_config.get('credentials', {})
        self.captcha_config = platform_config.get('captcha', {})
        self.click_captcha_config = platform_config.get('click_captcha', {})
        self.cookie_config = platform_config.get('cookie_login', {})
        self.use_playwright_flag = platform_config.get('use_playwright', True)
        self.pw_config = platform_config.get('playwright', {})
        self.selectors = platform_config.get('selectors', {})
        self.timeout = platform_config.get('timeout', 30)

        self.full_login_url = f"{self.base_url}{self.login_api}" if self.login_api else f"{self.base_url}{self.login_url}"
        self.full_odds_url = f"{self.base_url}{self.odds_endpoint}"

    # ==================== 主入口 ====================

    async def crawl_matches(self, platform_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.logger.info(f"开始爬取平台数据: {platform_config['name']}")

        if not await self._ensure_login():
            self.logger.error("登录失败，无法爬取万博体育数据")
            self.logger.info("提示：请确保在中国IP环境下运行，或在浏览器登录后导出cookie")
            return []

        html = await self._fetch_odds_page()
        if not html:
            self.logger.error("获取赔率页面失败")
            return []

        if self._is_forbidden_page(html):
            self.logger.error("IP被万博体育封锁（forbidden页面），请使用中国IP或VPN")
            return []

        try:
            soup = self.parse_html(html)
            matches = self.extract_match_info(soup)
            self.logger.info(f"成功爬取 {len(matches)} 场比赛数据")
            return matches
        except Exception as e:
            self.logger.error(f"解析页面失败: {str(e)}")
            return []

    # ==================== 登录流程 ====================

    async def _ensure_login(self) -> bool:
        if self.is_logged_in:
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
            for cookie in valid_cookies:
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                if name and value:
                    self.session.cookie_jar.update_cookies(
                        {name: value},
                        response_url=URL(self.base_url)
                    )

            self.logger.info(f"已从文件加载 {len(valid_cookies)} 个万博体育cookie")
            return True
        except Exception as e:
            self.logger.warning(f"加载cookie文件失败: {str(e)}")
            return False

    async def _verify_login_state(self) -> bool:
        """验证万博体育登录状态"""
        try:
            verify_url = self.config.get('platforms', {}).get('platform_b', {}).get('login_verify_endpoint', '')
            if verify_url:
                full_url = f"{self.base_url}{verify_url}" if not verify_url.startswith('http') else verify_url
                try:
                    async with self.session.get(full_url, headers=self.get_random_headers(),
                                                allow_redirects=False, timeout=15) as resp:
                        if resp.status in (401, 403, 302, 301):
                            return False
                        if resp.status == 200:
                            return True
                except Exception:
                    pass

            # 回退：访问首页检查
            headers = self.get_random_headers()
            headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            async with self.session.get(
                self.base_url, headers=headers, allow_redirects=False, timeout=15
            ) as resp:
                if resp.status in (302, 301, 401, 403):
                    return False
                if resp.status != 200:
                    return False
                body = await resp.text()
                if self._is_forbidden_page(body):
                    return False
                has_password = 'type="password"' in body
                has_login_title = bool(re.search(r'<title[^>]*>.*?(登录|login).*?</title>', body, re.I))
                if has_password or has_login_title:
                    return False
                return True
        except Exception as e:
            self.logger.warning(f"验证登录状态异常: {str(e)}")
            return False

    async def _login_with_playwright(self) -> bool:
        """使用Playwright自动化登录万博体育"""
        try:
            from playwright.async_api import async_playwright

            self.logger.info(f"Playwright登录: {self.full_login_url}")

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    channel='chrome',
                    headless=False,
                    args=[
                        '--no-sandbox',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-web-security',
                    ]
                )
                context = await browser.new_context(
                    user_agent=random.choice(self.user_agents) if self.user_agents else (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                    ),
                    viewport={'width': 1920, 'height': 1080},
                    locale='zh-CN'
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)

                page = await context.new_page()
                page.set_default_timeout(60000)

                # 导航到登录页
                self.logger.info("正在打开万博体育登录页面...")
                try:
                    await page.goto(self.full_login_url, wait_until='networkidle', timeout=60000)
                except Exception:
                    self.logger.warning("登录页加载超时，尝试首页...")
                    await page.goto(self.base_url, wait_until='networkidle', timeout=60000)

                await page.wait_for_timeout(3000)

                # 检查是否触发IP限制页
                if await self._detect_forbidden_page(page):
                    self.logger.error("万博体育检测到海外IP，登录被阻止")
                    self.logger.error("请使用中国IP或VPN后重试")
                    await browser.close()
                    return False

                # 检查是否已经登录（可能通过记住密码）
                current_url = page.url
                if '/login' not in current_url and 'login' not in current_url.lower():
                    self.logger.info("检测到已登录状态（可能记住密码）")
                    return await self._save_playwright_cookies(context, browser)

                # 填写登录表单
                await self._fill_login_form(page)

                # 检测并处理点击式验证码
                if self.click_captcha_config.get('enabled', False):
                    await self._handle_click_captcha(page)

                # 等待登录完成
                self.logger.info("等待登录完成（30秒）...")
                try:
                    await page.wait_for_url(
                        lambda url: '/login' not in url and 'login' not in url.lower(),
                        timeout=30000
                    )
                except Exception:
                    pass
                await page.wait_for_timeout(2000)

                # 二次验证：如果还在登录页，手动等待
                if '/login' in page.url or 'login' in page.url.lower():
                    self.logger.warning("自动登录未完成，请在浏览器中手动完成登录")
                    self.logger.info("等待手动登录（最多90秒）...")
                    try:
                        await page.wait_for_url(
                            lambda url: '/login' not in url and 'login' not in url.lower(),
                            timeout=90000
                        )
                    except Exception:
                        self.logger.error("手动登录超时")
                        await browser.close()
                        return False

                self.logger.info(f"登录完成，当前URL: {page.url}")
                return await self._save_playwright_cookies(context, browser)

        except ImportError:
            self.logger.error("Playwright 未安装，请运行: pip install playwright && playwright install")
            return False
        except Exception as e:
            self.logger.error(f"Playwright登录失败: {str(e)}")
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

    async def _fill_login_form(self, page):
        """填写万博体育登录表单"""
        username = self.credentials.get('username', '')
        password = self.credentials.get('password', '')
        filled = False

        username_selectors = [
            'input[placeholder*="账号" i]', 'input[placeholder*="用户" i]',
            'input[placeholder*="手机" i]', 'input[placeholder*="邮箱" i]',
            'input[name="username"]', 'input[name="account"]', 'input[name="phone"]',
            'input[autocomplete="username"]', 'input[id*="username"]', 'input[id*="account"]',
        ]
        for sel in username_selectors:
            try:
                inp = await page.wait_for_selector(sel, timeout=3000)
                if inp:
                    await inp.fill(username)
                    self.logger.info(f"已填写用户名 ({sel})")
                    filled = True
                    break
            except Exception:
                continue

        if not filled:
            try:
                inputs = await page.query_selector_all('input:not([type="password"]):not([type="hidden"])')
                for inp in inputs:
                    if await inp.is_visible():
                        await inp.fill(username)
                        self.logger.info("已填写用户名 (智能回退)")
                        filled = True
                        break
            except Exception:
                pass

        pw_selectors = [
            'input[type="password"]', 'input[placeholder*="密码" i]',
            'input[name="password"]', 'input[autocomplete="current-password"]',
        ]
        for sel in pw_selectors:
            try:
                inp = await page.wait_for_selector(sel, timeout=3000)
                if inp:
                    await inp.fill(password)
                    self.logger.info("已填写密码")
                    break
            except Exception:
                continue

        await page.wait_for_timeout(500)

        btn_selectors = [
            'button[type="submit"]', 'button:has-text("登录")', 'button:has-text("登入")',
            'button:has-text("LOGIN")', 'a:has-text("登录")', '.login-btn', '.submit-btn',
            'input[type="submit"]', 'button[class*="login"]',
        ]
        for sel in btn_selectors:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                self.logger.info("已点击登录按钮")
                return

        self.logger.info("未找到登录按钮，尝试Enter提交")
        await page.keyboard.press('Enter')

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

            from yarl import URL
            for cookie in browser_cookies:
                self.session.cookie_jar.update_cookies(
                    {cookie['name']: cookie['value']},
                    response_url=URL(self.base_url)
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
                    args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
                )
                context = await browser.new_context(
                    user_agent=random.choice(self.user_agents) if self.user_agents else (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
                    ),
                    viewport={'width': 1920, 'height': 1080}, locale='zh-CN',
                )

                # 将session中的cookie注入到Playwright
                if self.session:
                    for cookie in self.session.cookie_jar:
                        try:
                            await context.add_cookies([{
                                'name': cookie.key,
                                'value': cookie.value,
                                'domain': cookie.get('domain', ''),
                                'path': cookie.get('path', '/'),
                            }])
                        except Exception:
                            continue

                page = await context.new_page()
                page.set_default_timeout(30000)

                try:
                    await page.goto(self.full_odds_url, wait_until='networkidle', timeout=60000)
                except Exception:
                    self.logger.warning("页面加载超时，尝试获取已有内容")

                try:
                    await page.wait_for_selector(wait_selector, timeout=wait_timeout)
                except Exception:
                    self.logger.warning("等待目标元素超时，继续获取内容")

                await page.wait_for_timeout(3000)

                if await self._detect_forbidden_page(page):
                    self.logger.error("IP被万博封锁")
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
