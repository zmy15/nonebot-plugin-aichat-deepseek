import pytest
from nonebug import App


@pytest.mark.asyncio
async def test_plugin_imports(app: App) -> None:
    import nonebot_plugin_aichat_deepseek as plugin

    assert plugin.private_chat is not None
    assert plugin.__plugin_meta__.name == "DeepSeek 对话"
