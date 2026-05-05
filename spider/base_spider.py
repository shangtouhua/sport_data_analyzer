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
        self.user_agents = config.get('user_agents', [])
        self.min_delay = config.get('min_delay', 0.5)
        self.max_delay = config.get('max_delay', 3.0)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1.0)
        # 登录状态管理
        self.is_logged_in = False
        self.login_cookies = None

    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session:
            await self.session.close()
        # 重置登录状态
        self.is_logged_in = False
        self.login_cookies = None

    def get_random_headers(self) -> Dict[str, str]:
        """
        生成随机请求头，用于反爬防护

        Returns:
            包含随机User-Agent的请求头字典
        """
        headers = {
            'User-Agent': random.choice(self.user_agents),
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
        处理登录流程

        Args:
            login_url: 登录页面URL
            credentials: 登录凭证，包含username和password
            captcha_config: 验证码配置

        Returns:
            登录是否成功
        """
        try:
            self.logger.info(f"开始登录: {login_url}")

            # 获取登录页面，提取CSRF token等信息
            login_page = await self.fetch_page(login_url)
            if not login_page:
                self.logger.error("获取登录页面失败")
                return False

            # 解析登录页面
            soup = self.parse_html(login_page)

            # 处理验证码（如果存在）
            captcha_solution = None
            if captcha_config and captcha_config.get('type') == 'image':
                captcha_solution = await self._handle_image_captcha(soup, captcha_config)
                if not captcha_solution:
                    self.logger.error("验证码识别失败")
                    return False

            # 准备登录数据
            login_data = self._prepare_login_data(soup, credentials, captcha_solution)

            # 提交登录表单
            success = await self._submit_login_form(login_url, login_data)

            if success:
                self.is_logged_in = True
                self.logger.info("登录成功")
            else:
                self.logger.error("登录失败")

            return success

        except Exception as e:
            self.logger.error(f"登录过程发生异常: {str(e)}")
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

            # 如果没有提供检查URL，使用一个需要登录的页面
            if not check_url:
                check_url = self.config.get('platform_a', {}).get('base_url', '') + '/profile'

            # 发送请求检查登录状态
            headers = self.get_random_headers()
            if self.login_cookies:
                # 使用登录时保存的cookies
                cookies = {cookie.key: cookie.value for cookie in self.login_cookies}

            async with self.session.get(check_url, headers=headers, cookies=cookies) as response:
                if response.status == 200:
                    content = await response.text()
                    # 检查页面是否包含登录相关内容
                    return not any(indicator in content.lower()
                                 for indicator in ['login', '登录', 'sign in'])
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