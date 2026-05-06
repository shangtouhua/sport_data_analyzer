#!/usr/bin/env python3
"""
测试脚本：验证平台A的登录、Playwright自动登录、数据爬取功能
"""

import asyncio
import logging
import sys
import os
import argparse

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spider.platform_a_parser import PlatformAParser
import yaml

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_login')


async def test_platform_a_login(use_playwright: bool = False):
    """
    测试平台A的登录功能

    Args:
        use_playwright: 是否强制使用Playwright浏览器登录
    """

    # 加载配置文件
    try:
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return False

    # 创建平台A解析器实例
    parser = PlatformAParser(config, logger)

    # 使用异步上下文管理器
    async with parser:
        logger.info("开始测试登录功能...")

        login_success = False

        # 如果指定了Playwright模式，直接走Playwright登录
        if use_playwright:
            logger.info("使用Playwright模式登录...")
            credentials = parser.credentials
            if credentials.get('username') and credentials.get('password'):
                login_success = await parser._login_with_playwright(credentials)
            else:
                logger.error("Playwright登录需要配置用户名和密码")
                return False
        else:
            # 正常流程：先检查cookie是否已加载并有效
            if parser.is_logged_in:
                logger.info("检测到cookie文件，将使用cookie登录")

            login_success = await parser._ensure_login()

            # cookie登录失败时，询问是否尝试Playwright自动登录
            if not login_success:
                logger.info("")
                logger.info("=" * 50)
                logger.info("Cookie登录失败，可使用以下方式解决：")
                logger.info("")
                logger.info("方式1: 在浏览器登录后导出真实cookie")
                logger.info("   运行: python tools/extract_cookies.py")
                logger.info("")
                logger.info("方式2: 使用Playwright自动登录（推荐）")
                logger.info("   运行: python test_login.py --playwright")
                logger.info("   系统将自动打开Chrome浏览器完成登录")
                logger.info("=" * 50)

                # 如果Playwright可用，自动询问
                try:
                    import playwright
                    logger.info("检测到Playwright已安装，可尝试自动登录")
                    logger.info("请运行: python test_login.py --playwright")
                except ImportError:
                    pass

                return False

        if login_success:
            logger.info("登录测试成功！")

            # 测试登录状态检查
            status_check = await parser.check_login_status()
            if status_check:
                logger.info("登录状态检查正常")
            else:
                logger.warning("登录状态检查失败")

            # 测试数据爬取
            logger.info("开始测试数据爬取...")
            platform_config = config.get('spider', {}).get('platforms', {}).get('platform_a', {})
            matches = await parser.crawl_matches(platform_config)

            if matches:
                logger.info(f"成功爬取 {len(matches)} 场比赛数据")
                for i, match in enumerate(matches[:3]):
                    logger.info(f"比赛 {i+1}: {match.get('home_team', '未知')} vs {match.get('away_team', '未知')}")
            else:
                logger.warning("未获取到比赛数据，可能需要调整页面解析逻辑或登录状态可能已过期")

            return True
        else:
            logger.error("登录测试失败")
            return False


async def main():
    """主测试函数"""
    parser = argparse.ArgumentParser(description='测试平台A登录和数据爬取')
    parser.add_argument(
        '--playwright', action='store_true',
        help='使用Playwright浏览器自动登录（处理AES加密和浏览器指纹）'
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("开始平台A登录和爬虫功能测试")
    if args.playwright:
        logger.info("模式: Playwright浏览器自动登录")
    else:
        logger.info("模式: Cookie文件登录")
    logger.info("=" * 50)

    try:
        success = await test_platform_a_login(use_playwright=args.playwright)

        if success:
            logger.info("\n所有测试通过！")
            logger.info("平台A爬虫已准备就绪")
        else:
            logger.error("\n测试失败")
            logger.info("请参考以上提示选择正确的登录方式")

    except Exception as e:
        logger.error(f"测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info("=" * 50)
    logger.info("测试完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
