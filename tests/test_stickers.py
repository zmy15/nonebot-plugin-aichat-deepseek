from pathlib import Path

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def test_is_sticker_image() -> None:
    from nonebot_plugin_aichat_deepseek.stickers import is_sticker_image

    assert is_sticker_image({"sub_type": 1})
    assert is_sticker_image({"subType": "1"})
    assert is_sticker_image({"sub_type": "3"})
    assert is_sticker_image({"summary": "[动画表情]"})
    assert is_sticker_image({"emoji_id": "123"})
    assert is_sticker_image({"file": "a.png"}, text="记住这个表情包")
    assert is_sticker_image({"file": "a.png"}, text="这个表情不错")

    assert not is_sticker_image({"sub_type": 0, "summary": "[图片]"})
    assert not is_sticker_image({"file": "a.png"}, text="看看这张照片")


def test_save_sticker_payload_deduplicates(
    stickers_mod, store_cls, tmp_path, monkeypatch
) -> None:
    from nonebot_plugin_aichat_deepseek.config import plugin_config

    monkeypatch.setattr(
        plugin_config, "deepseek_sticker_dir", str(tmp_path / "stickers")
    )
    store = store_cls()
    payload = stickers_mod.ImagePayload(PNG, "sticker.png", "image/png")

    first = stickers_mod.save_sticker_payload(store, "1:2", payload)
    second = stickers_mod.save_sticker_payload(store, "1:2", payload)

    assert first["created"] is True
    assert second["created"] is False
    assert first["id"] == second["id"]
    assert len(store.search_stickers("1:2")) == 1

    path = Path(first["file_path"])
    assert path.exists()
    assert path.read_bytes() == PNG
    assert path.parent == (tmp_path / "stickers").resolve()
    store.close()


def test_add_sticker_keeps_description_on_duplicate(
    store_cls, tmp_path
) -> None:
    store = store_cls()
    first = store.add_sticker(
        "1:2",
        "a" * 64,
        tmp_path / "a.png",
        description="无语",
        tags="无语,翻白眼",
    )
    second = store.add_sticker("1:2", "a" * 64, tmp_path / "a.png")

    assert second["id"] == first["id"]
    assert second["created"] is False
    assert second["description"] == "无语"
    assert second["tags"] == "无语,翻白眼"
    store.close()


def test_sticker_search_update_and_usage(store_cls, tmp_path) -> None:
    store = store_cls()
    first = store.add_sticker(
        "1:2",
        "a" * 64,
        tmp_path / "a.png",
        description="无语",
        tags="翻白眼,无语",
    )
    store.add_sticker(
        "1:2",
        "b" * 64,
        tmp_path / "b.png",
        description="开心",
    )
    store.add_sticker(
        "1:3",
        "a" * 64,
        tmp_path / "a.png",
        description="别的用户的表情包",
    )

    found = store.search_stickers("1:2", keyword="无语")
    assert [row["id"] for row in found] == [first["id"]]

    assert store.update_sticker_description(
        "1:2", first["id"], "嘲笑", "嘲讽,嘲笑"
    )
    updated = store.get_sticker("1:2", first["id"])
    assert updated is not None
    assert updated["description"] == "嘲笑"
    assert updated["tags"] == "嘲讽,嘲笑"

    assert store.record_sticker_used("1:2", first["id"])
    used = store.get_sticker("1:2", first["id"])
    assert used is not None
    assert used["use_count"] == 1

    assert store.get_sticker("1:3", first["id"]) is None
    assert store.delete_sticker("1:2", first["id"])
    assert store.get_sticker("1:2", first["id"]) is None
    store.close()


async def test_send_sticker_image_falls_back_to_base64(
    stickers_mod, tmp_path
) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []
            self.fail_first = True

        async def call_api(self, api: str, **kwargs):
            self.calls.append((api, kwargs))
            if self.fail_first:
                self.fail_first = False
                raise RuntimeError("file uri unsupported")
            return {}

    path = tmp_path / "sticker.png"
    path.write_bytes(PNG)
    bot = FakeBot()

    method = await stickers_mod.send_sticker_image(bot, 2, path)

    assert method == "base64"
    assert len(bot.calls) == 2
    assert bot.calls[0][1]["message"][0]["data"]["file"].startswith("file://")
    assert bot.calls[1][1]["message"][0]["data"]["file"].startswith(
        "base64://"
    )


async def test_send_sticker_image_success_and_missing_file(
    stickers_mod, tmp_path
) -> None:
    class FakeBot:
        async def call_api(self, api: str, **kwargs):
            self.message = kwargs["message"]
            return {}

    path = tmp_path / "sticker.png"
    path.write_bytes(PNG)
    bot = FakeBot()

    assert await stickers_mod.send_sticker_image(bot, 2, path) == "file_uri"
    assert bot.message[0]["type"] == "image"

    with pytest.raises(stickers_mod.StickerError, match="不存在"):
        await stickers_mod.send_sticker_image(
            bot, 2, tmp_path / "missing.png"
        )
