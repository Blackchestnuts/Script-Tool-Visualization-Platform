"""
示例 Pytest 测试文件
用于演示 TEP 平台的执行和报告功能
"""
import pytest
import time


@pytest.mark.smoke
def test_health_check():
    """健康检查接口 - 应该通过"""
    # 模拟 API 调用
    time.sleep(0.1)
    response_status = 200
    assert response_status == 200, "健康检查接口应返回 200"


@pytest.mark.smoke
def test_api_version():
    """版本号接口 - 应该通过"""
    time.sleep(0.1)
    api_version = "1.0.0"
    assert api_version is not None, "版本号不应为空"
    assert api_version.startswith("1."), "版本号应以 1. 开头"


@pytest.mark.regression
def test_login_success():
    """登录成功场景 - 应该通过"""
    time.sleep(0.2)
    # 模拟登录请求
    response = {
        "code": 0,
        "message": "登录成功",
        "data": {"token": "eyJhbGciOiJIUzI1NiJ9.test"}
    }
    assert response["code"] == 0, f"登录应成功，实际 code={response['code']}"
    assert "token" in response["data"], "登录成功应返回 token"


@pytest.mark.regression
def test_login_wrong_password():
    """密码错误场景 - 应该通过"""
    time.sleep(0.1)
    response = {
        "code": 1001,
        "message": "用户名或密码错误"
    }
    assert response["code"] == 1001, "密码错误时应返回 1001"


@pytest.mark.regression
def test_create_user():
    """创建用户 - 应该通过"""
    time.sleep(0.3)
    response = {
        "code": 0,
        "message": "创建成功",
        "data": {"user_id": 1001, "username": "testuser01"}
    }
    assert response["code"] == 0
    assert response["data"]["user_id"] > 0


@pytest.mark.regression
def test_create_duplicate_user():
    """重复用户名创建 - 应该通过"""
    time.sleep(0.1)
    response = {
        "code": 2001,
        "message": "用户名已存在"
    }
    assert response["code"] == 2001


def test_order_create():
    """创建订单 - 应该通过"""
    time.sleep(0.2)
    response = {
        "code": 0,
        "message": "下单成功",
        "data": {"order_id": "ORD20240001"}
    }
    assert response["code"] == 0
    assert response["data"]["order_id"].startswith("ORD")


def test_order_insufficient_stock():
    """库存不足 - 应该通过"""
    time.sleep(0.1)
    response = {
        "code": 3001,
        "message": "库存不足"
    }
    assert response["code"] == 3001


@pytest.mark.smoke
def test_database_connection():
    """数据库连接检查 - 应该通过"""
    time.sleep(0.1)
    # 模拟数据库连接
    is_connected = True
    assert is_connected, "数据库连接应正常"


@pytest.mark.slow
def test_large_dataset_query():
    """大数据量查询 - 慢测试"""
    time.sleep(1.0)
    # 模拟大数据量查询
    total_records = 10000
    assert total_records > 0, "查询结果不应为空"


# 以下是一个故意失败的测试，用于演示失败报告
# 如果需要看失败效果，取消注释即可
# def test_intentional_failure():
#     """故意失败的测试 - 演示失败报告"""
#     assert 1 == 2, "这是一个预期会失败的测试"
