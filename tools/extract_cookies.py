#!/usr/bin/env python3
"""
Cookie提取工具
帮助用户从浏览器导出已登录平台的cookie，用于爬虫的cookie登录方式。

背景：平台A（https://www.uompld.vip:7988）使用Next.js前端框架，
登录时密码经过AES加密后传输，包含浏览器指纹检测，API直接登录非常困难。
推荐方式：在浏览器手动登录后，导出cookie供爬虫使用。

使用方法：
1. 在浏览器中正常登录平台A（www.uompld.vip:7988）
2. 按照下方对应浏览器的方式导出cookie
3. 运行本脚本验证并转换cookie文件
4. 将cookie文件保存到 data/platform_a_cookies.json
"""

import json
import os
import sys
from datetime import datetime


def print_chrome_instructions():
    """打印Chrome浏览器导出cookie的步骤"""
    instructions = """
╔══════════════════════════════════════════════════════════════╗
║              Chrome 浏览器导出 Cookie 步骤                    ║
╚══════════════════════════════════════════════════════════════╝

方法一：使用开发者工具（推荐）
───────────────────────────────────
1. 打开 Chrome 浏览器，登录 https://www.uompld.vip:7988
2. 按 F12 打开开发者工具
3. 切换到 Network（网络）标签页
4. 刷新页面，任意点击一个请求
5. 在请求详情中找到 Request Headers 中的 Cookie 字段
6. 复制完整的 Cookie 字符串

方法二：使用 EditThisCookie 扩展
───────────────────────────────────
1. 安装 EditThisCookie Chrome 扩展
2. 登录平台后点击扩展图标
3. 点击 "Export" 按钮导出 JSON 格式的 cookie
4. 将导出的 JSON 保存到此文件

方法三：使用 Cookie-Editor 扩展
───────────────────────────────────
1. 安装 Cookie-Editor Chrome 扩展
2. 登录平台后点击扩展图标
3. 点击 Export 按钮（图标右下角）
4. 复制导出的 JSON 数据
5. 粘贴到 data/platform_a_cookies.json

方法四：直接复制 Cookie 字符串
───────────────────────────────────
1. 登录后在浏览器地址栏输入：
   javascript:document.cookie
2. 复制输出的 cookie 字符串
3. 运行本脚本，选择"手动输入cookie字符串"
"""
    print(instructions)


def print_firefox_instructions():
    """打印Firefox浏览器导出cookie的步骤"""
    instructions = """
╔══════════════════════════════════════════════════════════════╗
║              Firefox 浏览器导出 Cookie 步骤                   ║
╚══════════════════════════════════════════════════════════════╝

使用开发者工具
───────────────────────────────────
1. 打开 Firefox，登录 https://www.uompld.vip:7988
2. 按 F12 打开开发者工具
3. 切换到 Storage（存储）标签页
4. 在左侧展开 Cookies，选择 www.uompld.vip
5. 右键任意 cookie → 全选 → 右键 → 导出为 JSON
6. 将导出的文件内容复制到 data/platform_a_cookies.json
"""
    print(instructions)


def validate_cookie_file(file_path: str) -> bool:
    """
    验证cookie文件是否有效

    Args:
        file_path: cookie文件路径

    Returns:
        是否有效
    """
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            cookies = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON格式错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 读取文件失败: {e}")
        return False

    if not isinstance(cookies, list):
        print("❌ cookie文件格式错误：需要JSON数组格式")
        return False

    if len(cookies) == 0:
        print("❌ cookie文件为空")
        return False

    # 检查是否包含关键cookie字段
    required_fields = ['name', 'value']
    valid_cookies = 0
    for i, cookie in enumerate(cookies):
        if all(field in cookie for field in required_fields):
            valid_cookies += 1
        else:
            print(f"  ⚠️  第{i+1}个cookie缺少必要字段（需要name、value）")

    if valid_cookies == 0:
        print("❌ 没有找到有效的cookie条目")
        return False

    # 检查是否包含平台的关键cookie
    cookie_names = [c.get('name', '') for c in cookies if isinstance(c, dict)]
    print(f"\n  找到 {valid_cookies} 个有效cookie")
    print(f"  Cookie名称列表: {cookie_names}")

    # 常见的关键cookie名称
    important_cookies = ['token', 'session', 'sid', 'auth', 'PHPSESSID', 'JSESSIONID', 'login', 'user']
    found_important = [name for name in cookie_names if any(imp in name.lower() for imp in important_cookies)]

    if found_important:
        print(f"  ✅ 发现关键cookie: {found_important}")
    else:
        print("  ⚠️  未检测到明显的登录相关cookie，可能登录状态不完整")

    return True


def create_template_cookie_file(file_path: str):
    """
    创建cookie模板文件

    Args:
        file_path: 模板文件路径
    """
    template = [
        {
            "name": "your_cookie_name_here",
            "value": "your_cookie_value_here",
            "domain": "www.uompld.vip",
            "path": "/"
        }
    ]

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print(f"✅ 已创建cookie模板文件: {file_path}")
    print("   请将模板中的示例数据替换为实际的cookie数据")


def convert_cookie_string_to_json(cookie_string: str) -> list:
    """
    将cookie字符串转换为JSON格式

    Args:
        cookie_string: 浏览器cookie字符串（分号分隔的key=value对）

    Returns:
        JSON格式的cookie列表
    """
    cookies = []
    for item in cookie_string.split(';'):
        item = item.strip()
        if '=' in item:
            name, value = item.split('=', 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": "www.uompld.vip",
                "path": "/"
            })
    return cookies


def main():
    """主函数"""
    print("=" * 60)
    print("   Cookie 提取工具")
    print("   用于爬虫平台A的cookie登录")
    print("=" * 60)
    print()

    # 确定项目根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    target_path = os.path.join(project_root, 'data', 'platform_a_cookies.json')

    print(f"目标cookie文件: {target_path}")
    print()

    # 检查现有cookie文件
    if os.path.exists(target_path):
        print("📂 检测到现有cookie文件，正在验证...")
        if validate_cookie_file(target_path):
            print(f"\n✅ 现有cookie文件有效，可直接使用")
            print(f"   文件路径: {target_path}")
        else:
            print(f"\n⚠️  现有cookie文件无效，请重新导出")

        return

    # 选择操作
    print("请选择操作:")
    print("  1. 查看浏览器导出cookie教程")
    print("  2. 创建空模板文件（手动填写）")
    print("  3. 从cookie字符串转换")
    print("  4. 退出")

    choice = input("\n请输入选项 (1-4): ").strip()

    if choice == '1':
        print_chrome_instructions()
        print_firefox_instructions()

        input("\n按回车键返回主菜单...")
        main()

    elif choice == '2':
        create_template_cookie_file(target_path)

    elif choice == '3':
        print("\n请输入浏览器cookie字符串（从开发者工具中复制）:")
        print("格式: key1=value1; key2=value2; key3=value3")
        cookie_str = input("\nCookie字符串: ").strip()

        if cookie_str:
            cookies = convert_cookie_string_to_json(cookie_str)
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"✅ 已转换并保存 {len(cookies)} 个cookie到: {target_path}")

            # 验证
            validate_cookie_file(target_path)
        else:
            print("❌ 未输入cookie字符串")

    else:
        print("已退出")


if __name__ == "__main__":
    main()
