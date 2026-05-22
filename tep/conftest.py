"""
Pytest 配置文件
支持 --env 参数来切换执行环境
"""
import pytest
import yaml
from pathlib import Path


def pytest_addoption(parser):
    """添加自定义命令行参数"""
    parser.addoption(
        "--env",
        action="store",
        default="test_env",
        help="执行环境: test_env 或 staging_env",
    )


@pytest.fixture(scope="session")
def env_config(request):
    """根据 --env 参数加载对应环境配置"""
    env = request.config.getoption("--env")
    config_path = Path(__file__).parent / "config.yaml"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            all_configs = yaml.safe_load(f)
        if env in all_configs:
            return all_configs[env]
        else:
            pytest.fail(f"环境 {env} 不存在，可选: {list(all_configs.keys())}")
    else:
        # 无配置文件时返回默认值
        return {
            "base_url": "http://localhost:8080",
            "timeout": 30,
        }


@pytest.fixture(scope="session")
def base_url(env_config):
    """返回当前环境的基础 URL"""
    return env_config.get("base_url", "http://localhost:8080")


@pytest.fixture(scope="session")
def timeout(env_config):
    """返回当前环境的超时时间"""
    return env_config.get("timeout", 30)
