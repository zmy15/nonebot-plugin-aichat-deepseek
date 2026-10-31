import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")


@pytest.fixture
def ds():
    """在 NoneBot 初始化完成后再导入插件子模块。"""
    import nonebot_plugin_aichat_deepseek.data_source as module

    return module


@pytest.fixture
def store_cls():
    from nonebot_plugin_aichat_deepseek.history import ConversationStore

    return ConversationStore

