from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import AsyncGenerator, List

import pytest
from py._path.local import LocalPath
from werkzeug.exceptions import NotFound

from quart import Blueprint, Quart, request
from quart.helpers import (
    flash,
    get_flashed_messages,
    make_response,
    safe_join,
    send_file,
    send_from_directory,
    stream_with_context,
    url_for,
)

SERVER_NAME = "localhost"

ROOT_PATH = Path(__file__).parents[0]


@pytest.fixture
def app() -> Quart:
    app = Quart(__name__)
    app.config["SERVER_NAME"] = SERVER_NAME
    app.secret_key = "secret"

    @app.route("/")
    async def index() -> str:
        return ""

    async def index_post() -> str:
        return ""

    app.add_url_rule("/post", view_func=index_post, methods=["POST"], endpoint="index_post")

    @app.route("/resource/<int:id>")
    async def resource(id: int) -> str:
        return str(id)

    return app


@pytest.fixture
def host_matched_app() -> Quart:
    app = Quart(__name__, host_matching=True, static_host="localhost")
    app.config["SERVER_NAME"] = SERVER_NAME

    @app.route("/")
    async def index() -> str:
        return ""

    @app.route("/", host="quart.com")
    async def host() -> str:
        return ""

    return app


@pytest.mark.asyncio
async def test_make_response(app: Quart) -> None:
    async with app.app_context():
        response = await make_response("foo", 202)
        assert response.status_code == 202
        assert b"foo" in (await response.get_data())  # type: ignore


@pytest.mark.asyncio
async def test_flash(app: Quart) -> None:
    async with app.test_request_context("/"):
        await flash("message")
        assert get_flashed_messages() == ["message"]
        assert get_flashed_messages() == ["message"]


@pytest.mark.asyncio
async def test_flash_category(app: Quart) -> None:
    async with app.test_request_context("/"):
        await flash("bar", "error")
        await flash("foo", "info")
        assert get_flashed_messages(with_categories=True) == [("error", "bar"), ("info", "foo")]
        assert get_flashed_messages(with_categories=True) == [("error", "bar"), ("info", "foo")]


@pytest.mark.asyncio
async def test_flash_category_filter(app: Quart) -> None:
    async with app.test_request_context("/"):
        await flash("bar", "error")
        await flash("foo", "info")
        assert get_flashed_messages(category_filter=["error"]) == ["bar"]
        assert get_flashed_messages(category_filter=["error"]) == ["bar"]


@pytest.mark.asyncio
async def test_url_for(app: Quart) -> None:
    async with app.test_request_context("/"):
        assert url_for("index") == "/"
        assert url_for("index_post", _method="POST") == "/post"
        assert url_for("resource", id=5) == "/resource/5"


@pytest.mark.asyncio
async def test_url_for_host_matching(host_matched_app: Quart) -> None:
    async with host_matched_app.app_context():
        assert url_for("index", _external=True) == "http:///"
        assert url_for("host", _external=True) == "http://quart.com/"


@pytest.mark.asyncio
async def test_url_for_external(app: Quart) -> None:
    async with app.test_request_context("/"):
        assert url_for("index") == "/"
        assert url_for("index", _external=True) == "http://localhost/"
        assert url_for("resource", id=5, _external=True) == "http://localhost/resource/5"
        assert url_for("resource", id=5, _external=False) == "/resource/5"

    async with app.app_context():
        assert url_for("index") == "http://localhost/"
        assert url_for("index", _external=False) == "/"


@pytest.mark.asyncio
async def test_url_for_scheme(app: Quart) -> None:
    async with app.test_request_context("/"):
        with pytest.raises(ValueError):
            url_for("index", _scheme="https")
        assert url_for("index", _scheme="https", _external=True) == "https://localhost/"
        assert (
            url_for("resource", id=5, _scheme="https", _external=True)
            == "https://localhost/resource/5"
        )


@pytest.mark.asyncio
async def test_url_for_anchor(app: Quart) -> None:
    async with app.test_request_context("/"):
        assert url_for("index", _anchor="&foo") == "/#%26foo"
        assert url_for("resource", id=5, _anchor="&foo") == "/resource/5#%26foo"


@pytest.mark.asyncio
async def test_url_for_blueprint_relative(app: Quart) -> None:
    blueprint = Blueprint("blueprint", __name__)

    @blueprint.route("/")
    def index() -> str:
        return ""

    app.register_blueprint(blueprint, url_prefix="/blue")

    async with app.test_request_context("/blue/"):
        assert url_for(".index") == "/blue/"
        assert url_for("index") == "/"


@pytest.mark.asyncio
async def test_url_for_root_path(app: Quart) -> None:
    async with app.test_request_context("/", root_path="/bob"):
        assert url_for("index") == "/bob/"
        assert url_for("index_post", _method="POST") == "/bob/post"
        assert url_for("resource", id=5) == "/bob/resource/5"


@pytest.mark.asyncio
async def test_stream_with_context() -> None:
    app = Quart(__name__)

    @app.route("/")
    async def index() -> AsyncGenerator[bytes, None]:
        @stream_with_context
        async def generator() -> AsyncGenerator[bytes, None]:
            yield request.method.encode()
            yield b" "
            yield request.path.encode()

        return generator()

    test_client = app.test_client()
    response = await test_client.get("/")
    result = await response.get_data(as_text=False)
    assert result == b"GET /"


def test_safe_join(tmpdir: LocalPath) -> None:
    directory = tmpdir.realpath()
    tmpdir.join("file.txt").write("something")
    assert safe_join(directory, "file.txt") == Path(directory, "file.txt")


@pytest.mark.parametrize("paths", [[".."], ["..", "other"], ["..", "safes", "file"]])
def test_safe_join_raises(paths: List[str], tmpdir: LocalPath) -> None:
    directory = tmpdir.mkdir("safe").realpath()
    tmpdir.mkdir("other")
    tmpdir.mkdir("safes").join("file").write("something")
    with pytest.raises(NotFound):
        safe_join(directory, *paths)


@pytest.mark.asyncio
async def test_send_from_directory_raises() -> None:
    with pytest.raises(NotFound):
        await send_from_directory(str(ROOT_PATH), "no_file.no")


@pytest.mark.asyncio
async def test_send_file_path(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    async with app.app_context():
        response = await send_file(Path(file_.realpath()))
    assert (await response.get_data(as_text=False)) == file_.read_binary()


@pytest.mark.asyncio
async def test_send_file_bytes_io() -> None:
    app = Quart(__name__)
    io_stream = BytesIO(b"something")
    async with app.app_context():
        response = await send_file(io_stream, mimetype="text/plain")
    assert (await response.get_data(as_text=False)) == b"something"


@pytest.mark.asyncio
async def test_send_file_no_mimetype() -> None:
    app = Quart(__name__)
    async with app.app_context():
        with pytest.raises(ValueError):
            await send_file(BytesIO(b"something"))


@pytest.mark.asyncio
async def test_send_file_as_attachment(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    async with app.app_context():
        response = await send_file(Path(file_.realpath()), as_attachment=True)
    assert response.headers["content-disposition"] == "attachment; filename=send.img"


@pytest.mark.asyncio
async def test_send_file_as_attachment_name(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    async with app.app_context():
        response = await send_file(
            Path(file_.realpath()), as_attachment=True, attachment_filename="send.html"
        )
    assert response.headers["content-disposition"] == "attachment; filename=send.html"


@pytest.mark.asyncio
async def test_send_file_mimetype(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.bob")
    file_.write("something")
    async with app.app_context():
        response = await send_file(Path(file_.realpath()), mimetype="application/bob")
    assert (await response.get_data(as_text=False)) == file_.read_binary()
    assert response.headers["Content-Type"] == "application/bob"


@pytest.mark.asyncio
async def test_send_file_last_modified(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    async with app.app_context():
        response = await send_file(str(file_.realpath()))
    mtime = datetime.fromtimestamp(file_.mtime(), tz=timezone.utc)
    mtime = mtime.replace(microsecond=0)
    assert response.last_modified == mtime


@pytest.mark.asyncio
async def test_send_file_last_modified_override(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    last_modified = datetime(2015, 10, 10, tzinfo=timezone.utc)
    async with app.app_context():
        response = await send_file(str(file_.realpath()), last_modified=last_modified)
    assert response.last_modified == last_modified


@pytest.mark.asyncio
async def test_send_file_max_age(tmpdir: LocalPath) -> None:
    app = Quart(__name__)
    file_ = tmpdir.join("send.img")
    file_.write("something")
    async with app.app_context():
        response = await send_file(str(file_.realpath()))
    assert response.cache_control.max_age == app.send_file_max_age_default.total_seconds()
