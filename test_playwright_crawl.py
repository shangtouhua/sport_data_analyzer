"""
Playwright 完整采集测试
直接测试 IframeDataExtractor 是否能从 YBTY 页面抓到赛事数据
"""
import asyncio
import sys
import json
import logging

sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('test_crawl')

async def main():
    from spider.iframe_network_interceptor import IframeDataExtractor

    import yaml
    with open('config/config.yaml') as f:
        config = yaml.safe_load(f)

    extractor = IframeDataExtractor(config, logger)

    logger.info("=" * 60)
    logger.info("开始 Playwright 完整采集测试")
    logger.info("=" * 60)

    matches = await extractor.extract_from_page(
        provider_code="YBTY",
        cookie_path="data/platform_a_cookies.json",
        headless=False,
        capture_duration=25000,
    )

    print("\n")
    print("=" * 60)
    print(f"采集完成! 共获取 {len(matches)} 场比赛")
    print("=" * 60)

    if matches:
        for i, m in enumerate(matches):
            print(f"\n--- 赛事 {i + 1} ---")

            print(f"  联赛: {m.get('league_name', 'N/A')}")
            print(f"  主队: {m.get('home_team', 'N/A')}")
            print(f"  客队: {m.get('away_team', 'N/A')}")
            print(f"  时间: {m.get('match_time', 'N/A')}")
            print(f"  状态: {m.get('match_status', 'N/A')}")
            print(f"  主胜: {m.get('home_win_odds', 'N/A')}")
            print(f"  平局: {m.get('draw_odds', 'N/A')}")
            print(f"  客胜: {m.get('away_win_odds', 'N/A')}")
            print(f"  大球: {m.get('big_ball_odds', 'N/A')}")
            print(f"  小球: {m.get('small_ball_odds', 'N/A')}")
            print(f"  盘口: {m.get('handicap', 'N/A')}")
    else:
        print("\n未获取到任何比赛数据")
        print("可能原因: cookie过期、页面结构变化、网络问题")
        print("请检查浏览器窗口观察是否正常加载了体育页面")

    return matches


if __name__ == '__main__':
    asyncio.run(main())
