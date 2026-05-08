"""
通用爬虫基类
封装通用的爬虫功能：请求处理、重试机制、反爬防护、异常处理等
包含登录和验证码识别功能
"""

import asyncio
import random
import time
import aiohttp
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin
import logging
from bs4 import BeautifulSoup
import io
import base64
import json
import os
import tempfile

from yarl import URL
from .captcha_solver import ClickCaptchaSolver

class BaseSpider:
    """
    通用爬虫基类
    提供基础的爬虫功能，包括请求处理、重试机制、反爬防护等
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化爬虫

        Args:
            config: 爬虫配置字典
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger
        self.session = None
        # 从config读取爬虫配置（config已是spider子段）
        self.user_agents = config.get('user_agents', [])
        self.min_delay = config.get('min_delay', 0.5)
        self.max_delay = config.get('max_delay', 3.0)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1.0)
        # 登录状态管理
        self.is_logged_in = False
        self.login_cookies = None
        self.login_token = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession(trust_env=False)

        # 尝试从文件加载cookie（如果配置了cookie登录）
        cookie_loaded = await self._try_load_cookies_from_file()
        if cookie_loaded:
            self.is_logged_in = True
            self.logger.info("从文件加载cookie成功，跳过API登录")

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session:
            await self.session.close()
        # 重置登录状态
        self.is_logged_in = False
        self.login_cookies = None
        self.login_token = None

    async def _try_load_cookies_from_file(self) -> bool:
        """
        尝试从配置文件指定的路径加载并验证cookie
        包含对占位符值、合并cookie的检测，以及加载后主动验证

        Returns:
            cookie是否有效且已加载
        """
        try:
            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            cookie_config = platform_config.get('cookie_login', {})
            if not cookie_config.get('enabled', False):
                return False

            cookie_file = cookie_config.get('cookie_file', '')
            if not cookie_file:
                return False

            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)
            if not os.path.exists(cookie_path):
                self.logger.warning(f"Cookie文件不存在: {cookie_path}")
                self.logger.info("请先在浏览器登录，然后导出cookie到该文件")
                return False

            with open(cookie_path, 'r', encoding='utf-8') as f:
                cookies_data = json.load(f)

            # 过滤无效cookie（占位符值），只加载有效的cookie
            placeholder_patterns = ['your_', 'replace_', 'placeholder', 'xxx', 'here']
            valid_cookies = []
            skipped_cookies = []
            for c in cookies_data:
                if isinstance(c, dict):
                    val = c.get('value', '')
                    if any(p in val.lower() for p in placeholder_patterns):
                        skipped_cookies.append(c.get('name', 'unknown'))
                    else:
                        valid_cookies.append(c)

            if skipped_cookies:
                self.logger.warning(f"跳过含占位符的cookie: {skipped_cookies}")

            if not valid_cookies:
                self.logger.error("Cookie文件中所有cookie均为占位符值，无法使用")
                self.logger.error("请在浏览器登录后，重新导出真实的cookie到 data/platform_a_cookies.json")
                self.logger.error("运行以下命令获取帮助: python tools/extract_cookies.py")
                return False

            # 检测合并cookie（一个cookie值包含多个键值对）
            for c in valid_cookies:
                if '; ' in c.get('value', ''):
                    self.logger.warning(
                        f"Cookie '{c.get('name')}' 包含合并的cookie值（含有'; '分隔符），"
                        f"应拆分为独立cookie条目"
                    )

            # 将有效cookie注入到session中
            base_url_str = platform_config.get('base_url', '')
            base_url = URL(base_url_str) if base_url_str else URL()
            loaded_count = 0
            for cookie in valid_cookies:
                name = cookie.get('name', '')
                value = cookie.get('value', '')
                if name and value:
                    self.session.cookie_jar.update_cookies(
                        {name: value},
                        response_url=base_url
                    )
                    loaded_count += 1

            # 从cookie中提取login_token（X-API-TOKEN）
            for cookie in cookies_data:
                if isinstance(cookie, dict) and cookie.get('name') == 'X-API-TOKEN':
                    self.login_token = cookie.get('value', '')
                    break

            self.login_cookies = self.session.cookie_jar
            self.logger.info(f"已从文件加载 {loaded_count} 个cookie")

            # 主动验证cookie是否有效
            if not await self._verify_cookies_work():
                self.logger.error("Cookie已过期或无效，需要重新在浏览器登录并导出")
                self.logger.info("运行以下命令获取帮助: python tools/extract_cookies.py")
                self.is_logged_in = False
                return False

            self.logger.info("Cookie验证通过，登录状态有效")
            return True

        except Exception as e:
            self.logger.warning(f"加载cookie文件失败: {str(e)}")
            return False

    async def _verify_cookies_work(self) -> bool:
        """
        主动验证当前session中的cookie是否有效
        通过访问首页并检测响应状态和内容来判断

        Returns:
            cookie是否有效
        """
        try:
            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            base_url = platform_config.get('base_url', '')
            if not base_url:
                return False

            # 优先使用配置的验证端点（如果存在），避免SPA首页误判
            verify_endpoint = platform_config.get('login_verify_endpoint', '')
            verify_header_name = platform_config.get('login_verify_header', 'X-API-TOKEN')
            if verify_endpoint:
                verify_url = f"{base_url}{verify_endpoint}" if not verify_endpoint.startswith('http') else verify_endpoint
                self.logger.info(f"使用配置的验证端点检查登录状态: {verify_endpoint}")
                v_headers = self.get_random_headers()
                if self.login_token:
                    v_headers[verify_header_name] = self.login_token
                try:
                    async with self.session.get(
                        verify_url, headers=v_headers, allow_redirects=False, timeout=15
                    ) as v_resp:
                        if v_resp.status in (401, 403, 302, 301):
                            self.logger.warning(f"验证端点返回状态码 {v_resp.status}，Cookie可能已失效")
                        else:
                            self.logger.info("验证端点状态正常，Cookie有效")
                            return True
                except Exception as e:
                    self.logger.warning(f"验证端点请求失败: {e}，回退到页面扫描")

            headers = self.get_random_headers()
            headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

            async with self.session.get(
                base_url, headers=headers, allow_redirects=False, timeout=15
            ) as response:
                if response.status in (302, 301, 307):
                    self.logger.warning(f"Cookie无效：请求被重定向到 {response.headers.get('Location', 'unknown')}")
                    return False
                if response.status in (401, 403):
                    self.logger.warning(f"Cookie无效：返回状态码 {response.status}")
                    return False
                if response.status != 200:
                    return False

                body = await response.text()

                # 精确检测：查找登录表单元素（密码输入框是登录页面的强信号）
                # SPA 首页导航栏可能包含"登录"文字，但不会有密码输入框
                has_password_field = 'input type="password"' in body or 'type="password"' in body
                if has_password_field:
                    self.logger.warning("Cookie无效：页面包含密码输入框，未登录")
                    return False

                # 检测页面标题是否包含"登录"（比正文更可靠）
                title_match = __import__('re').search(r'<title[^>]*>(.*?)</title>', body, __import__('re').IGNORECASE)
                if title_match:
                    title_text = title_match.group(1)
                    if any(kw in title_text for kw in ['登录', 'login', '用户登录']):
                        self.logger.warning(f"Cookie无效：页面标题包含登录关键词 '{title_text}'")
                        return False

                # 检测已登录状态关键词（后台/管理页面特征）
                logged_in_keywords = ['我的账户', '个人中心', '控制台', '仪表盘', '我的投注', '账户余额']
                if any(kw in body[:2000] for kw in logged_in_keywords):
                    self.logger.info("检测到已登录状态关键词")
                    return True

                self.logger.info("Cookie验证通过（未检测到登录表单）")
                return True

        except Exception as e:
            self.logger.warning(f"验证cookie时发生异常: {str(e)}")
            return False

    def get_random_headers(self) -> Dict[str, str]:
        """
        生成随机请求头，用于反爬防护

        Returns:
            包含随机User-Agent的请求头字典
        """
        user_agent = random.choice(self.user_agents) if self.user_agents else 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        return headers

    async def make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[str]:
        """
        发送HTTP请求，包含重试机制

        Args:
            url: 请求URL
            method: 请求方法（GET/POST）
            **kwargs: 其他请求参数

        Returns:
            响应内容字符串，失败返回None
        """
        headers = self.get_random_headers()
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
        kwargs['headers'] = headers

        for attempt in range(self.max_retries + 1):
            try:
                # 随机延时，避免高频请求
                if self.min_delay > 0 and self.max_delay > self.min_delay:
                    delay = random.uniform(self.min_delay, self.max_delay)
                    await asyncio.sleep(delay)

                self.logger.debug(f"发起请求: {url} (尝试 {attempt + 1}/{self.max_retries + 1})")

                async with self.session.request(method, url, **kwargs) as response:
                    if response.status == 200:
                        content = await response.text()
                        self.logger.debug(f"请求成功: {url}")
                        return content
                    elif response.status in [429, 503]:  # 限流或服务不可用
                        self.logger.warning(f"请求被限流: {url}, 状态码: {response.status}")
                        if attempt < self.max_retries:
                            await asyncio.sleep(self.retry_delay * (attempt + 1))
                            continue
                    else:
                        self.logger.error(f"请求失败: {url}, 状态码: {response.status}")
                        return None

            except asyncio.TimeoutError:
                self.logger.warning(f"请求超时: {url} (尝试 {attempt + 1})")
            except aiohttp.ClientError as e:
                self.logger.error(f"客户端错误: {url}, 错误: {str(e)}")
            except Exception as e:
                self.logger.error(f"未知错误: {url}, 错误: {str(e)}")

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay * (attempt + 1))

        self.logger.error(f"请求失败，已达到最大重试次数: {url}")
        return None

    async def fetch_page(self, url: str, **kwargs) -> Optional[str]:
        """
        获取页面内容

        Args:
            url: 页面URL
            **kwargs: 请求参数

        Returns:
            页面HTML内容，失败返回None
        """
        return await self.make_request(url, 'GET', **kwargs)

    def parse_html(self, html_content: str) -> BeautifulSoup:
        """
        解析HTML内容

        Args:
            html_content: HTML字符串

        Returns:
            BeautifulSoup对象
        """
        return BeautifulSoup(html_content, 'html.parser')

    def extract_match_info(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        提取赛事信息（需要在子类中实现）

        Args:
            soup: BeautifulSoup对象

        Returns:
            赛事信息列表
        """
        raise NotImplementedError("子类必须实现extract_match_info方法")

    async def crawl_matches(self, platform_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        爬取赛事数据的主方法

        Args:
            platform_config: 平台配置

        Returns:
            赛事数据列表
        """
        base_url = platform_config['base_url']
        odds_endpoint = platform_config['odds_endpoint']
        url = urljoin(base_url, odds_endpoint)

        self.logger.info(f"开始爬取平台数据: {platform_config['name']}")

        html_content = await self.fetch_page(url, timeout=platform_config.get('timeout', 30))
        if not html_content:
            self.logger.error(f"获取页面内容失败: {url}")
            return []

        try:
            soup = self.parse_html(html_content)
            matches = self.extract_match_info(soup)
            self.logger.info(f"成功爬取 {len(matches)} 场比赛数据")
            return matches
        except Exception as e:
            self.logger.error(f"解析页面失败: {str(e)}")
            return []

    # ==================== 登录和验证码识别功能 ====================

    async def login(self, login_url: str, credentials: Dict[str, str],
                   captcha_config: Optional[Dict[str, Any]] = None) -> bool:
        """
        处理登录流程（通用入口，自动选择登录方式）

        Args:
            login_url: 登录页面URL或登录API URL
            credentials: 登录凭证，包含username和password
            captcha_config: 验证码配置

        Returns:
            登录是否成功
        """
        try:
            self.logger.info(f"开始登录: {login_url}")

            # 判断登录方式：如果配置了login_api字段，使用JSON API方式登录
            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            login_api = platform_config.get('login_api', '')

            if login_api:
                full_login_api = f"{platform_config.get('base_url', '')}{login_api}"
                success = await self._api_json_login(full_login_api, credentials)
            else:
                # 传统表单登录方式（兼容旧版）
                success = await self._form_login(login_url, credentials, captcha_config)

            if success:
                self.is_logged_in = True
                self.logger.info("登录成功")
            else:
                self.logger.error("登录失败")

            return success

        except Exception as e:
            self.logger.error(f"登录过程发生异常: {str(e)}")
            return False

    async def _api_json_login(self, login_api_url: str, credentials: Dict[str, str]) -> bool:
        """
        使用JSON API方式登录（适用于现代Next.js/React SPA网站）

        Args:
            login_api_url: 登录API的完整URL
            credentials: 登录凭证

        Returns:
            登录是否成功
        """
        try:
            self.logger.info(f"使用API登录: {login_api_url}")

            login_data = {
                'username': credentials.get('username', ''),
                'password': credentials.get('password', ''),
                'Kaptchcate': 99  # 99表示跳过验证码
            }

            headers = self.get_random_headers()
            platform_cfg = self.config.get('platforms', {}).get('platform_a', {})
            base_url = platform_cfg.get('base_url', '')
            login_page = platform_cfg.get('login_url', '/user/login')
            headers.update({
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/plain, */*',
                'Referer': f'{base_url}{login_page}'
            })

            async with self.session.post(login_api_url, json=login_data, headers=headers) as response:
                if response.status == 200:
                    resp_data = await response.json()
                    self.logger.debug(f"登录API响应: {resp_data}")

                    status_code = resp_data.get('status_code')
                    if status_code in (0, 200):
                        self.login_cookies = response.cookies
                        data = resp_data.get('data', {})
                        if data:
                            self.login_token = data.get('token', '')
                        return True
                    else:
                        error_msg = resp_data.get('message', '登录失败')
                        self.logger.error(f"登录API返回错误: {error_msg} (code: {status_code})")
                        return False
                else:
                    self.logger.error(f"登录API请求失败，状态码: {response.status}")
                    return False

        except aiohttp.ContentTypeError:
            self.logger.error("登录API响应不是有效的JSON格式")
            return False
        except Exception as e:
            self.logger.error(f"API登录过程发生异常: {str(e)}")
            return False

    async def _form_login(self, login_url: str, credentials: Dict[str, str],
                         captcha_config: Optional[Dict[str, Any]] = None) -> bool:
        """
        传统表单登录方式（适用于传统HTML表单网站）

        Args:
            login_url: 登录页面URL
            credentials: 登录凭证
            captcha_config: 验证码配置

        Returns:
            登录是否成功
        """
        try:
            self.logger.info(f"使用表单登录: {login_url}")

            login_page = await self.fetch_page(login_url)
            if not login_page:
                self.logger.error("获取登录页面失败")
                return False

            soup = self.parse_html(login_page)

            captcha_solution = None
            if captcha_config and captcha_config.get('type') == 'image':
                captcha_solution = await self._handle_image_captcha(soup, captcha_config)
                if not captcha_solution:
                    self.logger.error("验证码识别失败")
                    return False

            login_data = self._prepare_login_data(soup, credentials, captcha_solution)
            return await self._submit_login_form(login_url, login_data)

        except Exception as e:
            self.logger.error(f"表单登录过程发生异常: {str(e)}")
            return False

    async def _handle_image_captcha(self, soup: BeautifulSoup,
                                   captcha_config: Dict[str, Any]) -> Optional[str]:
        """
        处理图片验证码

        Args:
            soup: 登录页面的BeautifulSoup对象
            captcha_config: 验证码配置

        Returns:
            验证码识别结果，失败返回None
        """
        try:
            # 查找验证码图片
            captcha_img = soup.find('img', {'id': 'captcha'}) or \
                         soup.find('img', class_='captcha') or \
                         soup.find('img', alt=lambda x: x and 'captcha' in x.lower())

            if not captcha_img:
                self.logger.warning("未找到验证码图片")
                return None

            # 获取验证码图片URL
            captcha_src = captcha_img.get('src')
            if not captcha_src:
                self.logger.error("验证码图片src属性为空")
                return None

            # 处理相对URL
            if captcha_src.startswith('/'):
                # 需要从登录页面URL构建完整URL
                base_url = self.config.get('platform_a', {}).get('base_url', '')
                captcha_url = urljoin(base_url, captcha_src)
            else:
                captcha_url = captcha_src

            # 下载验证码图片
            captcha_image_data = await self._download_captcha_image(captcha_url)
            if not captcha_image_data:
                return None

            # 使用OCR识别验证码
            captcha_text = await self._recognize_captcha_ocr(captcha_image_data, captcha_config)

            return captcha_text

        except Exception as e:
            self.logger.error(f"处理图片验证码失败: {str(e)}")
            return None

    async def _download_captcha_image(self, captcha_url: str) -> Optional[bytes]:
        """
        下载验证码图片

        Args:
            captcha_url: 验证码图片URL

        Returns:
            图片二进制数据，失败返回None
        """
        try:
            async with self.session.get(captcha_url) as response:
                if response.status == 200:
                    return await response.read()
                else:
                    self.logger.error(f"下载验证码图片失败，状态码: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"下载验证码图片异常: {str(e)}")
            return None

    async def _recognize_captcha_ocr(self, image_data: bytes,
                                   captcha_config: Dict[str, Any]) -> Optional[str]:
        """
        使用OCR识别验证码

        Args:
            image_data: 验证码图片二进制数据
            captcha_config: 验证码配置

        Returns:
            识别的验证码文本，失败返回None
        """
        try:
            # 延迟导入，避免在没有安装依赖时报错
            from PIL import Image
            import pytesseract

            # 将二进制数据转换为PIL Image对象
            image = Image.open(io.BytesIO(image_data))

            # 图像预处理（可选）
            if captcha_config.get('preprocess', True):
                image = self._preprocess_captcha_image(image)

            # 使用Tesseract进行OCR识别
            custom_config = captcha_config.get('ocr_config', '--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
            captcha_text = pytesseract.image_to_string(image, config=custom_config)

            # 清理识别结果
            captcha_text = captcha_text.strip().replace(' ', '')

            self.logger.info(f"验证码识别结果: {captcha_text}")
            return captcha_text if captcha_text else None

        except ImportError as e:
            self.logger.error(f"OCR依赖未安装: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"OCR识别失败: {str(e)}")
            return None

    def _preprocess_captcha_image(self, image) -> Any:
        """
        验证码图片预处理

        Args:
            image: PIL Image对象

        Returns:
            处理后的Image对象
        """
        try:
            import cv2
            import numpy as np

            # 转换为numpy数组
            img_array = np.array(image)

            # 转换为灰度图
            if len(img_array.shape) == 3:
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            else:
                gray = img_array

            # 二值化处理
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # 去噪（可选）
            kernel = np.ones((2, 2), np.uint8)
            processed = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

            # 转换回PIL Image
            return Image.fromarray(processed)

        except ImportError:
            # 如果没有OpenCV，返回原始图像
            self.logger.warning("OpenCV未安装，跳过图像预处理")
            return image
        except Exception as e:
            self.logger.warning(f"图像预处理失败: {str(e)}")
            return image

    def _prepare_login_data(self, soup: BeautifulSoup, credentials: Dict[str, str],
                           captcha_solution: Optional[str] = None) -> Dict[str, str]:
        """
        准备登录表单数据

        Args:
            soup: 登录页面的BeautifulSoup对象
            credentials: 登录凭证
            captcha_solution: 验证码解决方案

        Returns:
            登录表单数据
        """
        login_data = {
            'username': credentials.get('username', ''),
            'password': credentials.get('password', '')
        }

        # 查找隐藏的CSRF token等字段
        hidden_inputs = soup.find_all('input', type='hidden')
        for input_field in hidden_inputs:
            name = input_field.get('name')
            value = input_field.get('value', '')
            if name:
                login_data[name] = value

        # 添加验证码字段（如果存在）
        if captcha_solution:
            # 常见的验证码字段名
            captcha_field_names = ['captcha', 'verify_code', 'code', 'captcha_code', 'validate_code']
            for field_name in captcha_field_names:
                if soup.find('input', {'name': field_name}):
                    login_data[field_name] = captcha_solution
                    break

        return login_data

    async def _submit_login_form(self, login_url: str, login_data: Dict[str, str]) -> bool:
        """
        提交登录表单

        Args:
            login_url: 登录URL
            login_data: 登录数据

        Returns:
            提交是否成功
        """
        try:
            # 确定表单提交URL（可能是当前页面或其他页面）
            submit_url = login_url

            # 发送POST请求提交登录表单
            headers = self.get_random_headers()
            headers.update({
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': login_url
            })

            async with self.session.post(submit_url, data=login_data, headers=headers) as response:
                if response.status in [200, 302]:  # 302通常是重定向到登录后页面
                    content = await response.text()

                    # 检查登录是否成功（根据响应内容判断）
                    if self._check_login_success(content):
                        # 保存登录后的cookies
                        self.login_cookies = response.cookies
                        return True
                    else:
                        self.logger.error("登录验证失败，用户名或密码错误")
                        return False
                else:
                    self.logger.error(f"登录请求失败，状态码: {response.status}")
                    return False

        except Exception as e:
            self.logger.error(f"提交登录表单失败: {str(e)}")
            return False

    def _check_login_success(self, content: str) -> bool:
        """
        检查登录是否成功

        Args:
            content: 登录响应内容

        Returns:
            登录是否成功
        """
        # 常见的登录失败提示关键词
        failure_indicators = [
            '用户名或密码错误',
            'login failed',
            'invalid username',
            'invalid password',
            '验证码错误',
            'captcha error',
            '登录失败'
        ]

        content_lower = content.lower()
        for indicator in failure_indicators:
            if indicator.lower() in content_lower:
                return False

        # 常见的登录成功提示关键词
        success_indicators = [
            '欢迎',
            'welcome',
            'dashboard',
            '个人中心',
            'logout',
            '退出'
        ]

        for indicator in success_indicators:
            if indicator.lower() in content_lower:
                return True

        # 如果没有明确的失败提示，默认成功
        return True

    async def _login_with_playwright(self, credentials: Dict[str, str]) -> bool:
        """
        使用Playwright自动化浏览器登录
        通过真实浏览器处理AES加密、浏览器指纹等反爬机制

        Args:
            credentials: 登录凭证

        Returns:
            登录是否成功
        """
        try:
            from playwright.async_api import async_playwright

            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            base_url = platform_config.get('base_url', '')
            login_page = platform_config.get('login_url', '/user/login')
            login_url = f"{base_url}{login_page}"

            self.logger.info(f"使用Playwright自动登录: {login_url}")
            self.logger.info("正在启动浏览器...")

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
                    user_agent=random.choice(self.user_agents) if self.user_agents else None,
                    viewport={'width': 1920, 'height': 1080},
                    locale='zh-CN'
                )

                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)

                page = await context.new_page()
                page.set_default_timeout(60000)

                # 导航到登录页面
                self.logger.info("正在打开登录页面...")
                await page.goto(login_url, wait_until='networkidle', timeout=60000)
                await page.wait_for_timeout(2000)

                # === 第1步：尝试自动填写登录表单（扩展多种选择器） ===
                auto_filled = False
                username_selectors = [
                    'input[placeholder*="账号" i], input[placeholder*="用户" i], input[placeholder*="手机" i], input[placeholder*="邮箱" i], input[placeholder*="email" i]',
                    'input[name="username"], input[name="account"], input[name="phone"], input[name="email"], input[autocomplete="username"]',
                    'input[id*="username"], input[id*="account"], input[id*="phone"], input[id*="email"]',
                ]
                for sel in username_selectors:
                    try:
                        inp = await page.wait_for_selector(sel, timeout=5000)
                        if inp:
                            await inp.fill(credentials.get('username', ''))
                            self.logger.info(f"已自动填写用户名 (使用选择器: {sel})")
                            auto_filled = True
                            break
                    except Exception:
                        continue

                # 智能回退：遍历可见非密码输入框，跳过搜索框
                if not auto_filled:
                    try:
                        all_inputs = await page.query_selector_all(
                            'input:not([type="password"]):not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
                        )
                        for inp in all_inputs:
                            if not await inp.is_visible():
                                continue
                            ph = (await inp.get_attribute('placeholder') or '').lower()
                            if any(kw in ph for kw in ['搜索', 'search', '查找', 'query']):
                                continue
                            await inp.fill(credentials.get('username', ''))
                            self.logger.info(f"已自动填写用户名 (智能回退)")
                            auto_filled = True
                            break
                    except Exception:
                        pass

                password_selectors = [
                    'input[placeholder*="密码" i], input[name="password"], input[autocomplete="current-password"]',
                    'input[type="password"]',
                ]
                pw_filled = False
                for sel in password_selectors:
                    try:
                        inp = await page.wait_for_selector(sel, timeout=5000)
                        if inp:
                            await inp.fill(credentials.get('password', ''))
                            self.logger.info(f"已自动填写密码 (使用选择器: {sel})")
                            pw_filled = True
                            break
                    except Exception:
                        continue

                await page.wait_for_timeout(500)

                # === 第2步：检测并处理验证码（独立于自动填写结果） ===
                user_already_logged_in = False

                # GeeTest 行为验证码（滑块拼图）
                self.logger.info("检测GeeTest验证码...")
                if '/user/login' not in page.url:
                    self.logger.info("用户已登录，跳过GeeTest验证码处理")
                    user_already_logged_in = True
                else:
                    captcha_passed = await self._detect_and_solve_geetest(page)
                    if not captcha_passed:
                        self.logger.warning("GeeTest验证码处理未完成，但仍尝试等待登录")

                # 点击式验证码（OCR + 顺序点击）
                if '/user/login' not in page.url:
                    self.logger.info("检测到用户已登录，跳过后续验证码处理")
                    user_already_logged_in = True
                else:
                    self.logger.info("检测点击式验证码...")
                    click_captcha_passed = await self._detect_and_solve_click_captcha(page)
                    if not click_captcha_passed:
                        self.logger.warning("点击式验证码处理未完成，但仍尝试等待登录")

                if not user_already_logged_in:
                    # === 第3步：点击登录按钮或等待手动登录 ===
                    btn_selectors = [
                        'button[type="submit"]',
                        'button:has-text("登录")',
                        'button:has-text("登入")',
                        'button:has-text("login")',
                        '.login-btn',
                        '.submit-btn',
                    ]

                    if auto_filled and pw_filled:
                        # 尝试点击登录按钮
                        clicked = False
                        for sel in btn_selectors:
                            btn = await page.query_selector(sel)
                            if btn:
                                await btn.click()
                                self.logger.info("已点击登录按钮")
                                clicked = True
                                break
                        if not clicked:
                            self.logger.warning("未找到登录按钮，尝试Enter提交")
                            await page.keyboard.press('Enter')

                        # 部分平台的验证码通过后需再次点击登录按钮
                        try:
                            still_on_login = '/user/login' in page.url
                            if still_on_login:
                                self.logger.info("验证码已处理完成，再次点击登录按钮...")
                                for sel in btn_selectors:
                                    btn = await page.query_selector(sel)
                                    if btn and await btn.is_enabled():
                                        await btn.click()
                                        self.logger.info("已重新点击登录按钮")
                                        break
                        except Exception:
                            pass

                        self.logger.info("等待登录完成（15秒）...")
                        try:
                            await page.wait_for_url(
                                lambda url: '/user/login' not in url,
                                timeout=15000
                            )
                        except Exception:
                            pass
                    else:
                        self.logger.warning("自动填写未完全成功，请手动在浏览器中完成登录")
                        self.logger.info("请在浏览器窗口中手动输入账号密码并登录，系统将自动处理验证码")
                        self.logger.info("等待手动登录（最多90秒）...")
                        try:
                            await page.wait_for_url(
                                lambda url: '/user/login' not in url,
                                timeout=90000
                            )
                        except Exception:
                            pass

                    await page.wait_for_timeout(2000)

                    # 检查登录是否成功
                    current_url = page.url
                    if '/user/login' in current_url:
                        self.logger.error("Playwright登录失败：仍然停留在登录页面")
                        try:
                            error_text = await page.text_content(
                                '.error-message, .el-message, [class*="error"], .message, .tip'
                            )
                            if error_text and error_text.strip():
                                self.logger.error(f"页面错误提示: {error_text.strip()}")
                        except Exception:
                            pass
                        await browser.close()
                        return False

                self.logger.info("Playwright登录成功，当前URL: {}".format(page.url))

                # 从浏览器上下文获取cookies
                browser_cookies = await context.cookies()
                self.logger.info(f"从浏览器获取到 {len(browser_cookies)} 个cookie")

                # 将cookie注入到aiohttp session
                for cookie in browser_cookies:
                    self.session.cookie_jar.update_cookies(
                        {cookie['name']: cookie['value']},
                        response_url=URL(base_url)
                    )
                    if cookie['name'] == 'X-API-TOKEN':
                        self.login_token = cookie['value']

                self.login_cookies = self.session.cookie_jar

                # 检查是否获取到认证token（X-API-TOKEN），避免保存无效cookie
                if self.login_token:
                    self.is_logged_in = True
                    self._save_cookies_to_file(browser_cookies)
                else:
                    self.logger.warning(
                        "Playwright登录后未获取到X-API-TOKEN（可能触发了IP限制页面），"
                        "保留原有cookie文件不覆盖"
                    )
                    self.is_logged_in = False
                    await browser.close()
                    return False

                await browser.close()
                self.logger.info("Playwright登录流程完成，cookie已保存")
                return True

        except ImportError as e:
            self.logger.error(f"Playwright未安装: {str(e)}")
            self.logger.info("请运行: pip install playwright && playwright install")
            return False
        except Exception as e:
            self.logger.error(f"Playwright登录失败: {str(e)}")
            self.logger.info("提示: Playwright登录需要系统安装Chrome浏览器")
            return False

    def _save_cookies_to_file(self, cookies: list) -> None:
        """
        将cookie列表保存到配置文件指定的路径

        Args:
            cookies: cookie对象列表（包含name, value, domain, path字段）
        """
        try:
            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            cookie_config = platform_config.get('cookie_login', {})
            cookie_file = cookie_config.get('cookie_file', '')
            if not cookie_file:
                return

            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)

            cookies_data = []
            for c in cookies:
                cookies_data.append({
                    'name': c.get('name', ''),
                    'value': c.get('value', ''),
                    'domain': c.get('domain', 'www.uompld.vip'),
                    'path': c.get('path', '/'),
                })

            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(cookies_data, f, ensure_ascii=False, indent=4)

            self.logger.info(f"已将 {len(cookies_data)} 个cookie保存到 {cookie_path}")
        except Exception as e:
            self.logger.warning(f"保存cookie到文件失败: {str(e)}")

    # ==================== GeeTest 行为验证码处理 ====================

    async def _detect_and_solve_geetest(self, page, detect_timeout: int = 5) -> bool:
        """
        检测并处理 GeeTest 行为验证码（滑块拼图）

        流程：
        1. 等待 GeeTest 弹窗出现（短超时，无验证码则跳过）
        2. 尝试自动滑块求解（类人鼠标拖动，最多3次）
        3. 自动求解失败时，提示用户手动完成
        4. 等待验证码通过后继续执行

        Args:
            page: Playwright 页面对象
            detect_timeout: 检测验证码出现的超时时间（秒）

        Returns:
            bool: 验证码是否已通过（True=已通过或无需处理，False=超时未通过）
        """
        try:
            # 等待 GeeTest 容器出现（多个常见选择器）
            geetest_selectors = [
                '.geetest_panel',
                '.geetest',
                '#geetest-captcha',
                '.gt_slider',
                '.geetest-holder',
            ]

            geetest_appeared = False
            for selector in geetest_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=detect_timeout * 1000)
                    geetest_appeared = True
                    self.logger.info(f"检测到 GeeTest 验证码（选择器: {selector}）")
                    break
                except Exception:
                    continue

            if not geetest_appeared:
                self.logger.debug("未检测到 GeeTest 验证码，继续执行")
                return True

            # 等待动画和 iframe 加载完成
            await asyncio.sleep(1.5)

            # 尝试自动求解（最多3次）
            for attempt in range(3):
                self.logger.info(f"自动滑块求解 第 {attempt + 1} 次尝试...")
                solved = await self._auto_slide_geetest(page)

                if solved:
                    self.logger.info("GeeTest 验证码自动求解成功！")
                    await asyncio.sleep(1)
                    return True

                self.logger.warning(f"第 {attempt + 1} 次自动求解失败")
                await asyncio.sleep(1)

            # 自动求解失败，回退到手动验证
            self.logger.warning("=" * 50)
            self.logger.warning("自动滑块求解失败，请手动完成验证码拼图")
            self.logger.warning("请在浏览器窗口中手动拖动滑块完成验证")
            self.logger.warning("完成验证码后，系统将自动继续")
            self.logger.warning("等待时间：最多 90 秒")
            self.logger.warning("=" * 50)

            manual_result = await self._wait_for_geetest_completion(page, timeout=90)

            if manual_result:
                self.logger.info("手动验证码已完成，继续登录流程")
                await asyncio.sleep(0.5)
                return True
            else:
                self.logger.error("验证码超时（90秒未完成），登录流程可能未完成")
                return False

        except Exception as e:
            self.logger.warning(f"GeeTest 验证码处理异常: {e}")
            return True

    async def _auto_slide_geetest(self, page) -> bool:
        """
        自动滑动 GeeTest 滑块验证码

        通过 Playwright 模拟类人鼠标拖动，支持 iframe 内嵌和直接 DOM 两种场景。

        Args:
            page: Playwright 页面对象

        Returns:
            bool: 滑动是否通过验证
        """
        try:
            # 检测 GeeTest 是否在 iframe 中
            geetest_frame = page
            frame_selectors = [
                '.geetest_panel iframe',
                '.geetest-captcha iframe',
                'iframe[src*="geetest"]',
                'iframe[id*="geetest"]',
            ]
            for fs in frame_selectors:
                iframe_elem = await page.query_selector(fs)
                if iframe_elem:
                    try:
                        frame = await iframe_elem.content_frame()
                        if frame:
                            geetest_frame = frame
                            self.logger.debug("GeeTest 位于 iframe 内")
                            break
                    except Exception:
                        continue

            # 定位滑块按钮
            slider_btn = None
            slider_selectors = [
                '.geetest_slider_button',
                '.gt_slider_knob',
                '.slider-btn',
                '.geetest_slider > div',
                '.geetest_btn',
            ]
            for selector in slider_selectors:
                try:
                    slider_btn = await geetest_frame.wait_for_selector(selector, timeout=2000)
                    if slider_btn and await slider_btn.is_visible():
                        self.logger.debug(f"定位到滑块按钮 (选择器: {selector})")
                        break
                except Exception:
                    continue

            if not slider_btn:
                self.logger.warning("未定位到 GeeTest 滑块按钮")
                return False

            box = await slider_btn.bounding_box()
            if not box:
                self.logger.warning("无法获取滑块位置信息")
                return False

            start_x = box['x'] + box['width'] / 2
            start_y = box['y'] + box['height'] / 2

            # 计算目标拖动距离
            track = await page.query_selector('.geetest_slider, .gt_slider, .geetest_track')
            if track:
                track_box = await track.bounding_box()
                if track_box:
                    target_x = track_box['x'] + track_box['width'] - box['width'] / 2 - 5
                else:
                    target_x = start_x + 250
            else:
                target_x = start_x + 250

            target_y = start_y + random.uniform(-2, 2)

            # 执行类人拖动
            await page.mouse.move(start_x, start_y)
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.1))

            steps = random.randint(28, 42)
            for i in range(1, steps + 1):
                progress = i / steps
                eased_progress = progress ** 1.15
                current_x = start_x + (target_x - start_x) * eased_progress
                y_jitter = random.uniform(-3, 3) * max(0, 1 - progress * 0.8)
                current_y = target_y + y_jitter

                await page.mouse.move(current_x, current_y)
                await asyncio.sleep(random.uniform(0.008, 0.025))

            await asyncio.sleep(random.uniform(0.03, 0.06))
            await page.mouse.up()

            await asyncio.sleep(2)

            # 检查验证结果
            solved = await page.evaluate("""
                () => {
                    const panel = document.querySelector('.geetest_panel');
                    if (!panel) return true;

                    const style = window.getComputedStyle(panel);
                    if (style.display === 'none' || style.visibility === 'hidden') return true;

                    if (panel.classList.contains('geetest_success')) return true;

                    return false;
                }
            """)

            return solved

        except Exception as e:
            self.logger.warning(f"自动滑块求解异常: {e}")
            return False

    async def _wait_for_geetest_completion(self, page, timeout: int = 90) -> bool:
        """
        等待用户手动完成 GeeTest 验证码

        轮询检测 GeeTest 面板状态，直到验证通过、用户已登录（URL变化）或超时。

        Args:
            page: Playwright 页面对象
            timeout: 超时时间（秒）

        Returns:
            bool: 是否已完成验证/登录
        """
        try:
            start_wait = time.time()
            while time.time() - start_wait < timeout:
                # 检测用户是否已登录（URL已离开登录页）
                try:
                    if '/user/login' not in page.url:
                        self.logger.info("检测到用户已登录，退出验证码等待")
                        return True
                except Exception:
                    pass

                solved = await page.evaluate("""
                    () => {
                        const panel = document.querySelector('.geetest_panel');
                        if (!panel) return true;

                        const style = window.getComputedStyle(panel);
                        if (style.display === 'none' || style.visibility === 'hidden') return true;

                        if (panel.classList.contains('geetest_success')) return true;

                        return false;
                    }
                """)

                if solved:
                    return True

                await asyncio.sleep(1)

            return False

        except Exception as e:
            self.logger.warning(f"等待手动验证码时异常: {e}")
            return False

    # ==================== 点击式验证码处理 ====================

    async def _detect_and_solve_click_captcha(self, page) -> bool:
        """
        检测并处理"按顺序点击文字"类型的验证码
        使用OCR识别文字 + 按顺序自动点击

        流程：
        1. 加载点击验证码配置
        2. 创建ClickCaptchaSolver实例
        3. 调用detect_and_solve自动检测和求解

        Args:
            page: Playwright 页面对象

        Returns:
            bool: 验证码是否已通过
        """
        try:
            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            click_captcha_config = platform_config.get('click_captcha', {})

            if not click_captcha_config.get('enabled', False):
                self.logger.debug("点击式验证码求解未启用")
                return True

            solver = ClickCaptchaSolver(click_captcha_config, logger=self.logger)
            return await solver.detect_and_solve(page)

        except Exception as e:
            self.logger.warning(f"点击式验证码处理异常: {e}")
            return True

    async def check_login_status(self, check_url: Optional[str] = None) -> bool:
        """
        检查登录状态是否有效

        Args:
            check_url: 用于检查登录状态的URL

        Returns:
            登录状态是否有效
        """
        try:
            if not self.is_logged_in:
                return False

            platform_config = self.config.get('platforms', {}).get('platform_a', {})
            base_url = platform_config.get('base_url', '')
            verify_endpoint = platform_config.get('login_verify_endpoint', '')
            verify_header_name = platform_config.get('login_verify_header', 'X-API-TOKEN')

            # 优先使用配置的验证端点（如果存在）
            if verify_endpoint:
                verify_url = f"{base_url}{verify_endpoint}" if not verify_endpoint.startswith('http') else verify_endpoint
                self.logger.info(f"使用配置的验证端点: {verify_endpoint}")
                v_headers = self.get_random_headers()
                if self.login_token:
                    v_headers[verify_header_name] = self.login_token
                try:
                    async with self.session.get(
                        verify_url, headers=v_headers, allow_redirects=False, timeout=15
                    ) as v_resp:
                        if v_resp.status in (401, 403, 302, 301):
                            self.logger.warning(f"验证端点返回状态码 {v_resp.status}，登录状态已失效")
                            return False
                        if v_resp.status == 200:
                            self.logger.info("验证端点确认登录状态正常")
                            return True
                except Exception as e:
                    self.logger.warning(f"验证端点请求失败: {e}，回退到token/页面检查")

            # 如果有login_token，验证其有效性
            if self.login_token:
                self.logger.info("使用token验证登录状态")
                headers = self.get_random_headers()
                headers[verify_header_name] = self.login_token
                try:
                    async with self.session.get(
                        base_url, headers=headers, allow_redirects=False, timeout=15
                    ) as response:
                        if response.status in (302, 301, 401, 403):
                            self.logger.warning("Token已失效")
                            return False
                        if response.status == 200:
                            return True
                except Exception:
                    pass

            # 如果没有提供检查URL，使用base_url
            if not check_url:
                platform_cfg = self.config.get('platforms', {}).get('platform_a', {})
                check_url = platform_cfg.get('base_url', '')

            headers = self.get_random_headers()

            async with self.session.get(check_url, headers=headers, allow_redirects=False) as response:
                if response.status in (200, 304):
                    body = await response.text()
                    # 精确检测登录表单（SPA首页导航栏的"登录"文字不应误判）
                    has_password_field = 'input type="password"' in body or 'type="password"' in body
                    if has_password_field:
                        self.logger.warning("登录状态无效：页面包含密码输入框")
                        return False
                    # 检测页面标题
                    title_match = __import__('re').search(r'<title[^>]*>(.*?)</title>', body, __import__('re').IGNORECASE)
                    if title_match:
                        title_text = title_match.group(1)
                        if any(kw in title_text for kw in ['登录', 'login', '用户登录']):
                            self.logger.warning(f"登录状态无效：页面标题包含登录关键词 '{title_text}'")
                            return False
                    # 检测已登录状态关键词
                    logged_in_keywords = ['我的账户', '个人中心', '控制台', '仪表盘', '我的投注', '账户余额']
                    if any(kw in body[:2000] for kw in logged_in_keywords):
                        self.logger.info("检测到已登录状态关键词")
                        return True
                    return True
                elif response.status == 302:
                    self.logger.warning("cookie已失效，需要重新登录")
                    return False
                else:
                    return False

        except Exception as e:
            self.logger.error(f"检查登录状态失败: {str(e)}")
            return False

    async def ensure_login(self, login_url: str, credentials: Dict[str, str],
                          captcha_config: Optional[Dict[str, Any]] = None,
                          max_retries: int = 3) -> bool:
        """
        确保登录状态，如果未登录则执行登录

        Args:
            login_url: 登录URL
            credentials: 登录凭证
            captcha_config: 验证码配置
            max_retries: 最大重试次数

        Returns:
            是否成功登录
        """
        # 如果已经登录，检查登录状态
        if self.is_logged_in:
            if await self.check_login_status():
                self.logger.info("当前已登录")
                return True
            else:
                self.logger.info("登录状态已失效，需要重新登录")
                self.is_logged_in = False

        # 没有提供登录凭证，直接返回失败
        if not credentials.get('username') or not credentials.get('password'):
            self.logger.error("未提供有效的登录凭证，跳过API登录")
            self.logger.info("请在浏览器登录后导出cookie，或配置有效的用户名和密码")
            return False

        # 执行登录
        for attempt in range(max_retries):
            self.logger.info(f"尝试登录 (第 {attempt + 1} 次)")
            if await self.login(login_url, credentials, captcha_config):
                return True

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避
                self.logger.info(f"等待 {wait_time} 秒后重试")
                await asyncio.sleep(wait_time)

        self.logger.error(f"登录失败，已达到最大重试次数 {max_retries}")
        return False