import base64

import httpx
import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 16
GIF = b"GIF89a" + b"0" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 16


async def test_fetch_data_url(images_mod) -> None:
    payload = "data:image/png;base64," + base64.b64encode(PNG).decode()
    image = await images_mod.fetch_image({"url": payload})

    assert image.data == PNG
    assert image.filename == "image.png"
    assert image.content_type == "image/png"


async def test_fetch_base64_scheme(images_mod) -> None:
    payload = "base64://" + base64.b64encode(JPEG).decode()
    image = await images_mod.fetch_image({"file": payload})

    assert image.data == JPEG
    assert image.filename == "image.jpg"
    assert image.content_type == "image/jpeg"


async def test_fetch_local_file(images_mod, tmp_path) -> None:
    path = tmp_path / "cat.png"
    path.write_bytes(PNG)

    image = await images_mod.fetch_image({"file": str(path)})
    assert image.data == PNG
    assert image.filename == "cat.png"
    assert image.content_type == "image/png"


async def test_fetch_http_url(images_mod) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/cat.jpg"
        return httpx.Response(200, content=JPEG)

    image = await images_mod.fetch_image(
        {"url": "https://example.com/cat.jpg"},
        transport=httpx.MockTransport(handler),
    )
    assert image.data == JPEG
    assert image.filename == "cat.jpg"
    assert image.content_type == "image/jpeg"


async def test_fetch_gif_and_webp(images_mod) -> None:
    gif = await images_mod.fetch_image(
        {"url": "data:image/gif;base64," + base64.b64encode(GIF).decode()}
    )
    assert gif.content_type == "image/gif"

    webp = await images_mod.fetch_image(
        {"url": "data:image/webp;base64," + base64.b64encode(WEBP).decode()}
    )
    assert webp.content_type == "image/webp"


async def test_fetch_rejects_unsupported_or_oversized(images_mod) -> None:
    with pytest.raises(images_mod.ImageError, match="仅支持"):
        await images_mod.fetch_image(
            {"url": "data:image/png;base64," + base64.b64encode(b"hello").decode()}
        )

    with pytest.raises(images_mod.ImageError, match="图片过大"):
        await images_mod.fetch_image(
            {"url": "data:image/png;base64," + base64.b64encode(PNG).decode()},
            max_bytes=4,
        )


async def test_fetch_rejects_missing_source(images_mod) -> None:
    with pytest.raises(images_mod.ImageError, match="url/file"):
        await images_mod.fetch_image({})
