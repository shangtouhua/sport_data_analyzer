"""
验证码识别与自动求解模块
支持点击式文字验证码（OCR识别文字 + YOLO目标检测 + Playwright顺序点击）

功能：
1. OCREngine: 使用ddddocr/pytesseract识别图片中的中英文文字
2. YOLODetector: 使用YOLOv8检测验证码区域中的元素位置（canvas场景备用）
3. ClickCaptchaSolver: 点击式验证码全流程求解
   - 检测验证码出现
   - 定位可点击元素（HTML选择器或YOLO）
   - OCR识别每个元素的文字
   - 根据提示文本解析点击顺序
   - 按序模拟类人点击
   - 验证结果
"""

import asyncio
import random
import re
import logging
from typing import Dict, List, Optional, Tuple, Any
import io


class OCREngine:
    """
    OCR识别引擎
    封装 ddddocr（主要）和 pytesseract（备用），用于识别验证码中的文字
    """

    def __init__(self, engine: str = "ddddocr", logger: Optional[logging.Logger] = None):
        """
        初始化OCR引擎

        Args:
            engine: OCR引擎类型，可选 "ddddocr" 或 "pytesseract"
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger('OCREngine')
        self.engine_name = engine
        self._ocr_instance = None
        self._initialized = False

    async def init(self) -> bool:
        """
        初始化OCR引擎（加载模型）

        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True

        try:
            if self.engine_name == "ddddocr":
                self._ocr_instance = await self._init_ddddocr()
            else:
                self._ocr_instance = await self._init_pytesseract()
            self._initialized = True
            self.logger.info(f"OCR引擎初始化成功: {self.engine_name}")
            return True
        except Exception as e:
            self.logger.error(f"OCR引擎初始化失败: {e}")
            if self.engine_name == "ddddocr":
                self.logger.info("尝试回退到 pytesseract OCR引擎...")
                try:
                    self._ocr_instance = await self._init_pytesseract()
                    self.engine_name = "pytesseract"
                    self._initialized = True
                    self.logger.info("已回退到 pytesseract OCR引擎")
                    return True
                except Exception as e2:
                    self.logger.error(f"pytesseract回退也失败: {e2}")
            return False

    async def _init_ddddocr(self):
        """
        初始化ddddocr（在线程中执行，避免阻塞事件循环）

        Returns:
            ddddocr.DdddOcr 实例
        """
        import ddddocr
        loop = asyncio.get_event_loop()
        ocr = await loop.run_in_executor(
            None,
            lambda: ddddocr.DdddOcr(show_ad=False)
        )
        return ocr

    async def _init_pytesseract(self):
        """返回标记对象表示使用pytesseract"""
        return "pytesseract"

    async def recognize(self, image_data: bytes) -> Optional[str]:
        """
        识别图片中的文字

        Args:
            image_data: 图片二进制数据（PNG/JPG）

        Returns:
            识别出的文字，失败返回None
        """
        if not self._initialized:
            self.logger.warning("OCR引擎未初始化")
            return None

        try:
            if self.engine_name == "ddddocr":
                return await self._recognize_ddddocr(image_data)
            else:
                return await self._recognize_pytesseract(image_data)
        except Exception as e:
            self.logger.error(f"OCR识别失败: {e}")
            return None

    async def _recognize_ddddocr(self, image_data: bytes) -> Optional[str]:
        """
        使用ddddocr识别

        Args:
            image_data: 图片二进制数据

        Returns:
            识别结果
        """
        if self._ocr_instance is None:
            return None

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._ocr_instance.classification(image_data)
        )
        text = result.strip() if result else ""
        self.logger.debug(f"ddddocr识别结果: '{text}'")
        return text if text else None

    async def _recognize_pytesseract(self, image_data: bytes) -> Optional[str]:
        """
        使用pytesseract识别

        Args:
            image_data: 图片二进制数据

        Returns:
            识别结果
        """
        import pytesseract
        from PIL import Image

        image = Image.open(io.BytesIO(image_data))
        if image.mode != 'L':
            image = image.convert('L')
        threshold = 128
        image = image.point(lambda x: 255 if x > threshold else 0)

        config = '--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ一-鿿'
        text = pytesseract.image_to_string(image, config=config)
        text = text.strip().replace(' ', '')
        self.logger.debug(f"pytesseract识别结果: '{text}'")
        return text if text else None

    async def recognize_element(self, page, element) -> Optional[str]:
        """
        对Playwright页面元素截图并识别文字

        Args:
            page: Playwright page对象
            element: Playwright element句柄

        Returns:
            元素中的文字
        """
        try:
            screenshot_bytes = await element.screenshot()
            if not screenshot_bytes:
                return None
            return await self.recognize(screenshot_bytes)
        except Exception as e:
            self.logger.warning(f"元素OCR识别失败: {e}")
            return None

    def close(self):
        """释放OCR资源"""
        self._ocr_instance = None
        self._initialized = False


class YOLODetector:
    """
    YOLOv8目标检测器
    当验证码元素在canvas或图片中时，检测字符/按钮位置
    """

    def __init__(self, model_name: str = "yolov8n.pt", logger: Optional[logging.Logger] = None):
        """
        初始化YOLO检测器

        Args:
            model_name: YOLO模型名称
            logger: 日志记录器
        """
        self.logger = logger or logging.getLogger('YOLODetector')
        self.model_name = model_name
        self._model = None
        self._initialized = False

    async def init(self) -> bool:
        """
        加载YOLO模型

        Returns:
            是否加载成功
        """
        try:
            from ultralytics import YOLO
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: YOLO(self.model_name)
            )
            self._initialized = True
            self.logger.info(f"YOLO模型加载成功: {self.model_name}")
            return True
        except ImportError:
            self.logger.warning("ultralytics未安装，YOLO检测不可用")
            return False
        except Exception as e:
            self.logger.error(f"YOLO模型加载失败: {e}")
            return False

    async def detect_regions(self, image_data: bytes,
                             target_classes: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """
        检测图片中的目标区域

        Args:
            image_data: 图片二进制数据（PNG/JPG）
            target_classes: 目标类别ID列表，None表示检测所有类别

        Returns:
            检测结果列表，每个元素包含坐标和置信度
        """
        if not self._initialized or self._model is None:
            self.logger.warning("YOLO模型未就绪")
            return []

        try:
            import numpy as np
            from PIL import Image

            image = Image.open(io.BytesIO(image_data))
            img_array = np.array(image)

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self._model(img_array)
            )

            regions = []
            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue

                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    if target_classes is not None and cls_id not in target_classes:
                        continue

                    x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                    regions.append({
                        'x1': int(x1), 'y1': int(y1),
                        'x2': int(x2), 'y2': int(y2),
                        'confidence': float(boxes.conf[i].item()),
                        'class_id': cls_id,
                        'class_name': result.names[cls_id],
                    })

            regions.sort(key=lambda r: (r['y1'], r['x1']))
            return regions

        except Exception as e:
            self.logger.error(f"YOLO检测失败: {e}")
            return []

    async def detect_captcha_elements(self, page, captcha_container_selector: str) -> List[Dict]:
        """
        对页面验证码区域截图并使用YOLO检测各个元素

        Args:
            page: Playwright page对象
            captcha_container_selector: 验证码容器的CSS选择器

        Returns:
            检测到的元素列表（包含页面绝对坐标）
        """
        try:
            container = await page.query_selector(captcha_container_selector)
            if not container:
                self.logger.warning(f"未找到验证码容器: {captcha_container_selector}")
                return []

            screenshot_bytes = await container.screenshot()
            if not screenshot_bytes:
                return []

            regions = await self.detect_regions(screenshot_bytes)

            container_box = await container.bounding_box()
            if not container_box:
                return regions

            for r in regions:
                r['page_x'] = container_box['x'] + r['x1']
                r['page_y'] = container_box['y'] + r['y1']
                r['page_x2'] = container_box['x'] + r['x2']
                r['page_y2'] = container_box['y'] + r['y2']

            return regions

        except Exception as e:
            self.logger.error(f"YOLO检测验证码元素失败: {e}")
            return []


class ClickCaptchaSolver:
    """
    点击式验证码自动求解器
    处理"请按顺序点击以下文字"类型的验证码

    工作流程:
    1. 检测验证码弹窗出现
    2. 定位所有可点击元素（优先Playwright选择器，回退YOLO检测）
    3. OCR识别每个元素的文字
    4. 解析提示文本获取目标点击顺序
    5. 按顺序模拟类人点击
    6. 验证结果
    """

    CONTAINER_SELECTORS = [
        '.click-captcha',
        '.captcha-click',
        '.sec-click-captcha',
        '.captcha_click',
        '[class*="clickCaptcha"]',
        '[class*="click_captcha"]',
        '[class*="clickcaptcha"]',
        '[class*="sec-captcha"]',
        'div[id*="captcha"]',
        'div[id*="CAPTCHA"]',
        '[class*="verify"]',
    ]

    CLICKABLE_SELECTORS = [
        '.captcha-click-item',
        '.click-captcha-item',
        '.sec-click-item',
        '.captcha-item',
        '.click-item',
        '[class*="captcha"] span',
        '[class*="captcha"] div[role="button"]',
        '[class*="captcha"] button',
        '[class*="click"] span',
        '[class*="click"] button',
    ]

    PROMPT_SELECTORS = [
        '.captcha-prompt',
        '.click-captcha-prompt',
        '.sec-captcha-prompt',
        '.captcha-tip',
        '.captcha-title',
        '[class*="prompt"]',
        '[class*="tip"]',
    ]

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        初始化点击验证码求解器

        Args:
            config: click_captcha配置字典
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger or logging.getLogger('ClickCaptchaSolver')
        self._ocr = None
        self._yolo = None
        self._ocr_initialized = False
        self._yolo_initialized = False
        self._yolo_results = []

    async def ensure_init(self) -> None:
        """确保OCR和YOLO组件已初始化"""
        if not self._ocr_initialized:
            engine = self.config.get('ocr_engine', 'ddddocr')
            self._ocr = OCREngine(engine=engine, logger=self.logger)
            self._ocr_initialized = await self._ocr.init()

        use_yolo = self.config.get('use_yolo', False)
        if use_yolo and not self._yolo_initialized:
            model = self.config.get('yolo_model', 'yolov8n.pt')
            self._yolo = YOLODetector(model_name=model, logger=self.logger)
            self._yolo_initialized = await self._yolo.init()

    async def detect_and_solve(self, page) -> bool:
        """
        检测并自动求解点击式验证码

        Args:
            page: Playwright page对象

        Returns:
            验证码是否已通过（True=已通过或无需处理）
        """
        try:
            # 快速检查：用户可能已手动登录（URL已离开登录页）
            try:
                if '/user/login' not in page.url:
                    self.logger.debug("用户已登录，无需处理点击式验证码")
                    return True
            except Exception:
                pass

            await self.ensure_init()

            captcha_container = await self._detect_captcha(page)
            if not captcha_container:
                self.logger.debug("未检测到点击式验证码")
                return True

            self.logger.info("检测到点击式验证码，开始自动求解...")

            max_retries = self.config.get('max_retries', 3)
            for attempt in range(max_retries):
                self.logger.info(f"验证码求解 第{attempt + 1}/{max_retries} 次尝试")

                solved = await self._attempt_solve(page, captcha_container)
                if solved:
                    await asyncio.sleep(1)
                    if await self._verify_solved(page):
                        self.logger.info("点击式验证码自动求解成功！")
                        return True

                self.logger.warning(f"第{attempt + 1}次求解失败")
                await self._try_refresh_captcha(page)
                await asyncio.sleep(1)

            self.logger.warning("=" * 50)
            self.logger.warning("点击式验证码自动求解失败，请手动完成验证")
            self.logger.warning("请在浏览器窗口中手动点击验证码元素")
            self.logger.warning("完成验证后，系统将自动继续")
            self.logger.warning("=" * 50)

            manual_timeout = self.config.get('manual_timeout', 90)
            return await self._wait_for_manual_solve(page, timeout=manual_timeout)

        except Exception as e:
            self.logger.warning(f"点击验证码处理异常: {e}")
            return True

    async def _detect_captcha(self, page) -> Optional[Any]:
        """
        检测页面上是否存在点击式验证码

        Args:
            page: Playwright page对象

        Returns:
            验证码容器元素句柄，未检测到返回None
        """
        for selector in self.CONTAINER_SELECTORS:
            try:
                container = await page.wait_for_selector(selector, timeout=3000)
                if container and await container.is_visible():
                    self.logger.debug(f"通过选择器检测到验证码: {selector}")
                    return container
            except Exception:
                continue

        prompt_keywords = [
            '请按顺序点击', '依次点击', '请点击以下', '请依次点击',
            '按顺序点击', 'click in order', 'please click',
            '请选择', '请按', '验证码',
        ]
        try:
            body_text = await page.text_content('body') or ''
            for keyword in prompt_keywords:
                if keyword in body_text:
                    self.logger.debug(f"通过关键词检测到验证码: '{keyword}'")
                    return await self._find_captcha_container_near_text(page, keyword)
        except Exception:
            pass

        return None

    async def _find_captcha_container_near_text(self, page, keyword: str) -> Optional[Any]:
        """
        通过关键词定位附近的验证码容器

        Args:
            page: Playwright page对象
            keyword: 提示文本关键词

        Returns:
            容器元素
        """
        for selector in ['[class*="captcha"]', '[class*="verify"]', '[class*="safe"]',
                         '.modal', '.dialog', '.popup', '[class*="pop"]']:
            try:
                elements = await page.query_selector_all(selector)
                for elem in elements:
                    text = await elem.text_content() or ''
                    if keyword in text:
                        return elem
            except Exception:
                continue
        return None

    async def _attempt_solve(self, page, container) -> bool:
        """
        尝试自动求解一次

        Args:
            page: Playwright page对象
            container: 验证码容器元素

        Returns:
            是否求解成功
        """
        prompt_text = await self._extract_prompt_text(page, container)
        if not prompt_text:
            self.logger.warning("未找到验证码提示文本")
            return False

        target_sequence = self._parse_target_sequence(prompt_text)
        if not target_sequence:
            self.logger.warning(f"未能从提示文本解析出目标序列: '{prompt_text}'")
            return False

        self.logger.info(f"验证码提示: '{prompt_text}'")
        self.logger.info(f"目标点击顺序: {target_sequence}")

        clickable_elements = await self._locate_clickable_elements(page, container)
        if not clickable_elements:
            if self._yolo_results:
                self.logger.info("使用YOLO坐标执行点击...")
                return await self._execute_yolo_clicks(page, self._yolo_results)
            self.logger.warning("未找到可点击的验证码元素")
            return False

        self.logger.info(f"找到 {len(clickable_elements)} 个可点击元素")

        element_labels = await self._recognize_elements_text(page, clickable_elements)
        if not element_labels:
            self.logger.warning("未能识别任何元素文字")
            return False

        self.logger.debug(f"元素文字识别结果: {element_labels}")

        click_order = self._determine_click_order(target_sequence, element_labels)
        if not click_order:
            self.logger.warning("无法匹配目标点击顺序")
            self.logger.debug(f"目标: {target_sequence}, 识别: {element_labels}")
            return False

        self.logger.info(f"确定的点击顺序(索引): {click_order}")
        return await self._execute_clicks(page, clickable_elements, click_order)

    async def _extract_prompt_text(self, page, container) -> Optional[str]:
        """
        提取验证码提示文本

        Args:
            page: Playwright page对象
            container: 验证码容器

        Returns:
            提示文本
        """
        for selector in self.PROMPT_SELECTORS:
            try:
                elem = await container.query_selector(selector)
                if elem:
                    text = await elem.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        try:
            text = await container.text_content()
            if text and text.strip():
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                for line in lines:
                    if any(k in line for k in ['点击', '顺序', '请', 'captcha', 'click']):
                        return line
                return lines[0] if lines else None
        except Exception:
            pass

        return None

    def _parse_target_sequence(self, prompt_text: str) -> Optional[List[str]]:
        """
        从提示文本中解析出目标点击顺序

        支持格式:
        - "请按顺序点击：安、全、验、证" → ["安", "全", "验", "证"]
        - "请依次点击'安','全','验','证'" → ["安", "全", "验", "证"]
        - "请点击 安全验证" → ["安", "全", "验", "证"]

        Args:
            prompt_text: 提示文本

        Returns:
            目标字符序列，解析失败返回None
        """
        if not prompt_text:
            return None

        # 模式1: 提取中英文逗号/顿号分隔的序列
        patterns = [
            r'[：:]\s*([一-鿿぀-ヿa-zA-Z0-9]+(?:[、，,]\s*[一-鿿぀-ヿa-zA-Z0-9]+)+)',
            r'[：:]\s*([一-鿿]+(?:\s+[一-鿿]+)+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt_text)
            if match:
                text = match.group(1)
                parts = re.split(r'[、，,，\s]+', text)
                parts = [p.strip().strip("'\"") for p in parts if p.strip()]
                if len(parts) >= 2:
                    return parts

        # 模式2: 提取"点击XXX"中的单个字符
        click_match = re.search(r'点击[\s]*([一-鿿]{2,10})', prompt_text)
        if click_match:
            word = click_match.group(1).strip()
            # 排除常见的提示用词（不是验证码目标字符）
            prompt_words = {'以下文字', '下列文字', '以下字符', '下方文字', '上方文字', '下面文字',
                              '安全验证', '在线验证', '图片验证', '滑动验证'}
            if word not in prompt_words and 2 <= len(word) <= 10:
                return list(word)

        # 模式3: 提取逗号分隔的序列（不依赖冒号前缀）
        # 如 "请依次点击'安','全','验','证'" → ["安", "全", "验", "证"]
        comma_match = re.search(r"['\"]([一-鿿a-zA-Z0-9])['\"]\s*[,，]\s*['\"]([一-鿿a-zA-Z0-9])['\"]", prompt_text)
        if comma_match:
            parts = re.findall(r"['\"]([一-鿿a-zA-Z0-9])['\"]", prompt_text)
            if len(parts) >= 2:
                return parts

        # 模式4: 提取逗号分隔的序列
        if ',' in prompt_text and 'click' not in prompt_text.lower():
            parts = [p.strip().strip("'\"") for p in prompt_text.split(',') if p.strip()]
            filter_words = {'click', 'in', 'order', 'please', 'the', 'and', 'then', '依次', '顺序'}
            # 过滤掉过长的非目标词
            filtered = [p for p in parts if len(p) <= 3 or p.lower() not in filter_words]
            # 去掉包含提示关键词的部分
            prompt_kw = ['请按', '依次', '点击', '请点击', 'Please', 'click', '顺序']
            filtered = [p for p in filtered if not any(kw in p for kw in prompt_kw)]
            if len(filtered) >= 2:
                return filtered

        # 模式5: 提取所有中文字符（fallback）
        chinese_chars = re.findall(r'[一-鿿]', prompt_text)
        # 排除常见的提示用字
        exclude_chars = set('请按顺序点击依次验证码验证以下文字请选择下列')
        chinese_chars = [c for c in chinese_chars if c not in exclude_chars]
        if len(chinese_chars) >= 2:
            return chinese_chars

        return None

    async def _locate_clickable_elements(self, page, container) -> List[Any]:
        """
        定位验证码中所有可点击元素

        Args:
            page: Playwright page对象
            container: 验证码容器元素

        Returns:
            元素句柄列表
        """
        elements = []

        for selector in self.CLICKABLE_SELECTORS:
            try:
                items = await container.query_selector_all(selector)
                if items and len(items) >= 2:
                    self.logger.debug(f"通过选择器找到{len(items)}个元素: {selector}")
                    elements = items
                    break
            except Exception:
                continue

        if not elements:
            try:
                for tag in ['span', 'div', 'button', 'li', 'a', 'label']:
                    items = await container.query_selector_all(f'{tag}:not(:empty)')
                    if items and len(items) >= 2:
                        elements = items
                        self.logger.debug(f"通过标签找到{len(items)}个元素: {tag}")
                        break
            except Exception:
                pass

        if not elements and self.config.get('use_yolo', False) and self._yolo:
            self.logger.info("使用YOLO检测验证码元素...")
            container_selector = await self._find_container_selector(page, container)
            if container_selector:
                self._yolo_results = await self._yolo.detect_captcha_elements(page, container_selector)
                if self._yolo_results:
                    self.logger.info(f"YOLO检测到{len(self._yolo_results)}个元素区域")

        return elements

    async def _find_container_selector(self, page, container) -> Optional[str]:
        """尝试生成容器元素的CSS选择器"""
        try:
            elem_id = await container.get_attribute('id')
            if elem_id:
                return f'#{elem_id}'
            elem_class = await container.get_attribute('class')
            if elem_class:
                classes = elem_class.strip().split()
                if classes:
                    return '.' + '.'.join(classes)
        except Exception:
            pass
        return None

    async def _recognize_elements_text(self, page, elements: List) -> List[Tuple[int, str]]:
        """
        识别所有可点击元素的文字

        Args:
            page: Playwright page对象
            elements: 元素句柄列表

        Returns:
            (元素索引, 文字) 元组列表
        """
        results = []

        for i, element in enumerate(elements):
            try:
                text = await element.text_content()
                if text:
                    text = text.strip()
                    if text:
                        results.append((i, text))
                        self.logger.debug(f"元素{i}[DOM]: '{text}'")
                        continue
            except Exception:
                pass

            try:
                text = await self._ocr.recognize_element(page, element)
                if text:
                    text = text.strip()
                    results.append((i, text))
                    self.logger.debug(f"元素{i}[OCR]: '{text}'")
            except Exception:
                continue

        return results

    def _determine_click_order(self, target_sequence: List[str],
                               element_labels: List[Tuple[int, str]]) -> Optional[List[int]]:
        """
        根据目标序列和元素识别结果确定点击顺序

        Args:
            target_sequence: 目标点击序列
            element_labels: [(索引, 文字), ...]

        Returns:
            按点击顺序排列的元素索引列表
        """
        click_order = []

        for target in target_sequence:
            best_match_idx = None
            best_match_score = 0

            for elem_idx, elem_text in element_labels:
                if elem_idx in click_order:
                    continue

                if elem_text == target:
                    best_match_idx = elem_idx
                    break

                if target in elem_text:
                    score = len(target) / max(len(elem_text), 1)
                    if score > best_match_score:
                        best_match_score = score
                        best_match_idx = elem_idx

                if elem_text.startswith(target):
                    if best_match_score < 0.9:
                        best_match_score = 0.9
                        best_match_idx = elem_idx

            if best_match_idx is not None and best_match_idx not in click_order:
                click_order.append(best_match_idx)

        if len(click_order) >= max(len(target_sequence) * 0.5, 1):
            return click_order

        return None

    async def _execute_clicks(self, page, elements: List, click_order: List[int]) -> bool:
        """
        按顺序执行点击

        Args:
            page: Playwright page对象
            elements: 所有元素句柄列表
            click_order: 按点击顺序排列的元素索引列表

        Returns:
            是否完成所有点击
        """
        delay_min = self.config.get('click_delay_min', 0.3)
        delay_max = self.config.get('click_delay_max', 0.8)

        for idx, elem_idx in enumerate(click_order):
            if elem_idx >= len(elements):
                continue

            element = elements[elem_idx]
            try:
                box = await element.bounding_box()
                if not box:
                    continue

                click_x = box['x'] + box['width'] * random.uniform(0.15, 0.85)
                click_y = box['y'] + box['height'] * random.uniform(0.15, 0.85)

                self.logger.info(f"点击第{idx + 1}个: 元素{elem_idx} ({click_x:.0f}, {click_y:.0f})")

                await page.mouse.move(click_x, click_y)
                await asyncio.sleep(random.uniform(0.1, 0.3))
                await page.mouse.click(click_x, click_y)
                await asyncio.sleep(random.uniform(delay_min, delay_max))

            except Exception as e:
                self.logger.warning(f"点击元素{elem_idx}失败: {e}")

        await asyncio.sleep(1.5)

        try:
            confirm_selectors = [
                'button:has-text("确认")',
                'button:has-text("确定")',
                'button:has-text("提交")',
                'button:has-text("验证")',
                'button:has-text("confirm")',
                'button:has-text("submit")',
            ]
            for sel in confirm_selectors:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    self.logger.info("已点击确认/提交按钮")
                    await asyncio.sleep(1)
                    break
        except Exception:
            pass

        return True

    async def _execute_yolo_clicks(self, page, regions: List[Dict]) -> bool:
        """
        按YOLO检测到的坐标执行点击

        Args:
            page: Playwright page对象
            regions: YOLO检测到的区域列表
        """
        delay_min = self.config.get('click_delay_min', 0.3)
        delay_max = self.config.get('click_delay_max', 0.8)

        for idx, region in enumerate(regions):
            cx = (region['page_x'] + region['page_x2']) // 2
            cy = (region['page_y'] + region['page_y2']) // 2
            cx += random.randint(-5, 5)
            cy += random.randint(-5, 5)

            self.logger.info(f"YOLO点击第{idx+1}个: ({cx}, {cy})")
            await page.mouse.move(cx, cy)
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.mouse.click(cx, cy)
            await asyncio.sleep(random.uniform(delay_min, delay_max))

        return True

    async def _try_refresh_captcha(self, page) -> None:
        """尝试刷新验证码"""
        refresh_selectors = [
            'button:has-text("刷新")',
            'button:has-text("换一批")',
            'button:has-text("换一个")',
            'button:has-text("reload")',
            'button:has-text("refresh")',
            '[class*="refresh"]',
            '[class*="reload"]',
        ]
        for selector in refresh_selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    self.logger.info("已点击刷新/换一批按钮")
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue

    async def _verify_solved(self, page) -> bool:
        """
        验证验证码是否已通过

        Args:
            page: Playwright page对象

        Returns:
            是否已通过
        """
        try:
            for selector in self.CONTAINER_SELECTORS:
                try:
                    container = await page.query_selector(selector)
                    if container:
                        if await container.is_visible():
                            return False
                except Exception:
                    continue

            body_text = await page.text_content('body') or ''
            success_keywords = ['验证成功', '验证通过', 'verified', 'captcha passed']
            for kw in success_keywords:
                if kw in body_text:
                    return True

            return True
        except Exception:
            return True

    async def _wait_for_manual_solve(self, page, timeout: int = 90) -> bool:
        """
        等待用户手动完成验证码

        轮询过程中同时检测用户是否已登录（URL离开登录页），
        避免用户在已完成登录后脚本仍继续等待验证码。

        Args:
            page: Playwright page对象
            timeout: 超时秒数

        Returns:
            是否已完成
        """
        import time
        start = time.time()
        while time.time() - start < timeout:
            # 检测用户是否已登录（URL已离开登录页）
            try:
                if '/user/login' not in page.url:
                    self.logger.info("检测到用户已登录，退出验证码等待")
                    return True
            except Exception:
                pass

            if await self._verify_solved(page):
                return True
            await asyncio.sleep(1)
        return False