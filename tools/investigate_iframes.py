"""
手动调查脚本：使用 Playwright 访问体育页面，识别 iframe 中的 API 端点
保存样本响应数据供离线开发使用
"""

import asyncio
import json
import os
import sys
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 提供商信息
PROVIDERS = [
    {"name": "YBTY(开云体育)", "path": "/game/sport/ob", "code": "YBTY"},
    {"name": "IMTY(IM体育)", "path": "/game/sport/im", "code": "IMTY"},
    {"name": "FBTY(FB体育)", "path": "/game/sport/fb", "code": "FBTY"},
    {"name": "DBTY(熊猫体育)", "path": "/game/sport/db", "code": "DBTY"},
    {"name": "XJTY(V188体育)", "path": "/game/sport/V188", "code": "XJTY"},
]

BASE_URL = "https://www.uompld.vip:7988"
COOKIE_FILE = "data/platform_a_cookies.json"
SAMPLE_DIR = "data/sample_responses"


def load_cookies():
    """加载保存的cookie"""
    cookie_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), COOKIE_FILE)
    with open(cookie_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def convert_cookies_for_playwright(raw_cookies):
    """将cookie文件格式转换为Playwright格式"""
    pw_cookies = []
    for c in raw_cookies:
        if isinstance(c, dict) and c.get('name') and c.get('value'):
            pw_cookies.append({
                'name': c['name'],
                'value': c['value'],
                'domain': c.get('domain', 'www.uompld.vip'),
                'path': c.get('path', '/'),
                'httpOnly': c.get('httpOnly', False),
                'secure': c.get('secure', True),
                'sameSite': c.get('sameSite', 'Lax'),
            })
    return pw_cookies


async def investigate_provider(page, context, provider, sample_dir):
    """调查单个体育提供商页面"""
    print(f"\n{'='*60}")
    print(f"调查: {provider['name']} ({provider['path']})")
    print(f"{'='*60}")

    url = f"{BASE_URL}{provider['path']}"
    captured = []

    # 设置响应拦截
    async def on_response(response):
        url_lower = response.url.lower()
        content_type = response.headers.get('content-type', '')

        if 'json' not in content_type:
            return

        try:
            body = await response.json()
            captured.append({
                'url': response.url,
                'method': response.request.method,
                'status': response.status,
                'headers': dict(response.headers),
                'body': body,
            })
            print(f"  [CAPTURED] {response.request.method} {response.status} {response.url[:120]}")
        except Exception:
            pass

    page.on('response', on_response)

    try:
        print(f"  导航到: {url}")
        await page.goto(url, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(3000)

        # 检测 iframe
        iframes = await page.query_selector_all('iframe')
        print(f"  检测到 {len(iframes)} 个 iframe:")
        for i, iframe in enumerate(iframes):
            src = await iframe.get_attribute('src')
            id_attr = await iframe.get_attribute('id')
            print(f"    iframe[{i}]: id={id_attr}, src={src}")

        await page.wait_for_load_state('networkidle', timeout=15000)
        await page.wait_for_timeout(5000)

        # 截图
        screenshot_path = os.path.join(sample_dir, f"{provider['code']}_screenshot.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"  截图保存: {screenshot_path}")

        title = await page.title()
        print(f"  页面标题: {title}")

        # 获取可见文本
        body_text = await page.evaluate("""
            () => {
                const exclude = ['script', 'style', 'iframe', 'noscript'];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false
                );
                let texts = [];
                let node;
                while (node = walker.nextNode()) {
                    const t = node.textContent.trim();
                    if (t && !exclude.includes(node.parentElement?.tagName?.toLowerCase())) {
                        texts.push(t.substring(0, 100));
                    }
                }
                return texts.slice(0, 50);
            }
        """)
        if body_text:
            print(f"  页面文本片段:")
            for t in body_text[:20]:
                print(f"    {t}")

    except Exception as e:
        print(f"  错误: {e}")
    finally:
        page.remove_listener('response', on_response)

    return captured


async def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sample_dir = os.path.join(project_root, SAMPLE_DIR)
    os.makedirs(sample_dir, exist_ok=True)

    raw_cookies = load_cookies()
    pw_cookies = convert_cookies_for_playwright(raw_cookies)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )

        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
            user_agent=('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/125.0.0.0 Safari/537.36'),
        )

        await context.add_cookies(pw_cookies)
        print(f"已注入 {len(pw_cookies)} 个cookie")

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        # 先访问首页验证登录
        print("\n验证登录状态...")
        await page.goto(BASE_URL, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)
        print(f"首页标题: {await page.title()}")

        is_logged_in = await page.evaluate("""
            () => !document.querySelector('input[type="password"]');
        """)
        print(f"登录状态: {'已登录' if is_logged_in else '未登录'}")

        if not is_logged_in:
            print("警告: 未检测到登录状态，请检查cookie是否有效")

        # 调查每个提供商
        all_captured = {}
        for provider in PROVIDERS:
            captured = await investigate_provider(page, context, provider, sample_dir)
            if captured:
                all_captured[provider['code']] = captured

                provider_dir = os.path.join(sample_dir, provider['code'])
                os.makedirs(provider_dir, exist_ok=True)

                summary = []
                for i, c in enumerate(captured):
                    fname = f"response_{i}.json"
                    fpath = os.path.join(provider_dir, fname)
                    with open(fpath, 'w', encoding='utf-8') as f:
                        json.dump(c, f, ensure_ascii=False, indent=2)
                    summary.append({
                        'file': fname,
                        'url': c['url'],
                        'method': c['method'],
                        'status': c['status'],
                    })

                summary_path = os.path.join(provider_dir, 'summary.json')
                with open(summary_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'provider': provider['name'],
                        'captured_count': len(captured),
                        'responses': summary,
                    }, f, ensure_ascii=False, indent=2)

                print(f"\n  已保存 {len(captured)} 个响应到 {provider_dir}/")

        # 总报告
        report_path = os.path.join(sample_dir, 'investigation_report.json')
        total_captured = sum(len(v) for v in all_captured.values())
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_providers': len(PROVIDERS),
                'providers_with_data': len(all_captured),
                'total_captured_responses': total_captured,
                'details': {
                    code: {
                        'name': next(p['name'] for p in PROVIDERS if p['code'] == code),
                        'captured_count': len(responses),
                    }
                    for code, responses in all_captured.items()
                }
            }, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"调查完成!")
        print(f"  共捕获 {total_captured} 个API响应")
        print(f"  报告保存: {report_path}")
        print(f"  样本目录: {sample_dir}")

        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
