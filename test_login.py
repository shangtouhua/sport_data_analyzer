#!/usr/bin/env python3
"""
测试脚本：验证平台A的登录和验证码识别功能
"""

import asyncio
import logging
import sys
import os

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

async def test_platform_a_login():
    """测试平台A的登录功能"""

    # 加载配置文件
    try:
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return False

    # 创建平台A解析器实例
    spider_config = config  # 传递完整配置
    parser = PlatformAParser(spider_config, logger)

    # 使用异步上下文管理器
    async with parser:
        # 测试登录功能
        logger.info("开始测试登录功能...")

        # 检查配置：优先使用cookie登录
        cookie_config = config.get('spider', {}).get('platforms', {}).get('platform_a', {}).get('cookie_login', {})
        has_cookie = cookie_config.get('enabled', False) and parser.is_logged_in

        if not has_cookie:
            credentials = parser.credentials
            if not credentials.get('username') or not credentials.get('password'):
                logger.error("缺少登录凭证，也未配置cookie登录")
                logger.info("请选择以下方式之一:")
                logger.info("1. 在config.yaml中配置正确的登录凭证（用户名/密码）")
                logger.info("2. 在浏览器登录后导出cookie，运行以下命令生成cookie文件:")
                logger.info("   python tools/extract_cookies.py")
                logger.info("")
                logger.info("配置示例:")
                logger.info("""
            spider:
              platforms:
                platform_a:
                  credentials:
                    username: "你的用户名"
                    password: "你的密码"
                """)
                return False
        else:
            logger.info("检测到cookie文件，将使用cookie登录")

        # 执行登录测试
        login_success = await parser._ensure_login()

        if login_success:
            logger.info("✅ 登录测试成功！")

            # 测试登录状态检查
            status_check = await parser.check_login_status()
            if status_check:
                logger.info("✅ 登录状态检查正常")
            else:
                logger.warning("⚠️  登录状态检查失败")

            # 测试数据爬取
            logger.info("开始测试数据爬取...")
            platform_config = config.get('spider', {}).get('platforms', {}).get('platform_a', {})
            matches = await parser.crawl_matches(platform_config)

            if matches:
                logger.info(f"✅ 成功爬取 {len(matches)} 场比赛数据")
                # 显示前3场比赛的信息
                for i, match in enumerate(matches[:3]):
                    logger.info(f"比赛 {i+1}: {match.get('home_team', '未知')} vs {match.get('away_team', '未知')}")
            else:
                logger.warning("⚠️  未获取到比赛数据，可能需要调整页面解析逻辑")

            return True
        else:
            logger.error("❌ 登录测试失败")
            return False

async def main():
    """主测试函数"""
    logger.info("=" * 50)
    logger.info("开始平台A登录和爬虫功能测试")
    logger.info("=" * 50)

    try:
        success = await test_platform_a_login()

        if success:
            logger.info("\n✅ 所有测试通过！")
            logger.info("平台A爬虫已准备就绪")
        else:
            logger.error("\n❌ 测试失败")
            logger.info("请检查以下内容:")
            logger.info("1. 配置文件(config.yaml)中的登录凭证(用户名/密码)是否正确")
            logger.info("2. 可在浏览器中手动访问 https://www.uompld.vip:7988 验证是否能正常登录")
            logger.info("3. 该平台登录采用JSON API方式 (/site/api/v1/user/login)，请确认网络代理是否正常")
            logger.info("4. 如密码包含特殊字符，尝试在浏览器登录后检查是否正确")

    except Exception as e:
        logger.error(f"测试过程中发生异常: {e}")
        import traceback
        logger.error(traceback.format_exc())

    logger.info("=" * 50)
    logger.info("测试完成")
    logger.info("=" * 50)

if __name__ == "__main__":
    # 运行测试
    asyncio.run(main())