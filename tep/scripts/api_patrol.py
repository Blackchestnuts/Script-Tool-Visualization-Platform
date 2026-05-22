# API 接口可用性巡检脚本
# 用法: python api_patrol.py [--base_url=http://xxx --count=5]

import time
import json
import sys
import urllib.request
import urllib.error


def check_api(url, name, method="GET", expected_code=200, timeout=10):
    """检查单个 API 接口"""
    start = time.time()
    try:
        req = urllib.request.Request(url, method=method)
        req.add_header("User-Agent", "TEP-Patrol/1.1")
        resp = urllib.request.urlopen(req, timeout=timeout)
        status_code = resp.getcode()
        elapsed = round((time.time() - start) * 1000)
        result = {
            "name": name,
            "url": url,
            "status_code": status_code,
            "elapsed_ms": elapsed,
            "pass": status_code == expected_code,
        }
    except urllib.error.HTTPError as e:
        elapsed = round((time.time() - start) * 1000)
        result = {
            "name": name,
            "url": url,
            "status_code": e.code,
            "elapsed_ms": elapsed,
            "pass": False,
            "error": str(e),
        }
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        result = {
            "name": name,
            "url": url,
            "status_code": -1,
            "elapsed_ms": elapsed,
            "pass": False,
            "error": str(e),
        }
    return result


def main():
    # 解析参数
    base_url = "https://httpbin.org"
    count = 3

    for arg in sys.argv[1:]:
        if arg.startswith("--base_url="):
            base_url = arg.split("=", 1)[1]
        elif arg.startswith("--count="):
            count = int(arg.split("=", 1)[1])

    print("=" * 50)
    print("  API 接口巡检")
    print(f"  基础URL: {base_url}")
    print(f"  巡检轮次: {count}")
    print("=" * 50)
    print()

    # 定义巡检接口列表
    api_list = [
        {"url": f"{base_url}/get", "name": "GET 接口", "method": "GET"},
        {"url": f"{base_url}/status/200", "name": "状态码200", "method": "GET"},
        {"url": f"{base_url}/status/404", "name": "状态码404", "method": "GET", "expected_code": 404},
        {"url": f"{base_url}/delay/1", "name": "延迟1秒接口", "method": "GET"},
    ]

    total = 0
    passed = 0
    failed = 0

    for round_num in range(1, count + 1):
        print(f"--- 第 {round_num}/{count} 轮 ---")
        for api in api_list:
            expected = api.get("expected_code", 200)
            result = check_api(api["url"], api["name"], api.get("method", "GET"), expected)
            total += 1
            status = "PASS" if result["pass"] else "FAIL"
            if result["pass"]:
                passed += 1
            else:
                failed += 1
            print(f"  [{status}] {result['name']} - "
                  f"HTTP {result['status_code']} - {result['elapsed_ms']}ms")
        if round_num < count:
            time.sleep(2)
        print()

    # 汇总
    print("=" * 50)
    print(f"  巡检完毕！总计: {total}, 通过: {passed}, 失败: {failed}")
    rate = round(passed / total * 100, 1) if total > 0 else 0
    print(f"  通过率: {rate}%")
    print("=" * 50)

    # 返回退出码
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
