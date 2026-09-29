import app as app_module
import pytest
from flask.signals import template_rendered
from markupsafe import escape


@pytest.fixture
def client():
    return app_module.app.test_client()


def request_template(client):
    rendered = {}

    def capture_template(sender, template, context, **extra):
        rendered["template"] = template
        rendered["greeting"] = context["greeting"]

    template_rendered.connect(capture_template, app_module.app)
    try:
        response = client.get("/template")
    finally:
        template_rendered.disconnect(capture_template, app_module.app)

    return response, rendered


def test_template_renders_current_context(client):
    response, rendered = request_template(client)

    assert response.status_code == 200
    assert rendered["template"].name == "template.html"
    body = response.get_data(as_text=True)
    assert str(escape(rendered["greeting"])) in body


def test_template_route_uses_default_context(client):
    response, rendered = request_template(client)

    assert response.status_code == 200
    assert rendered["greeting"] == "hello"
    assert rendered["title"] == "あいさつ"


def test_template_renders_changed_context_values():
    greeting = "app.pyのgreetingを変更した場合"

    with app_module.app.app_context():
        body = app_module.app.jinja_env.get_template("template.html").render(
            greeting=greeting,
        )

    assert f"<h1>あいさつ</h1>" in body
    assert f"<li>{escape(greeting)}</li>" in body


def test_template_matches_current_html(client):
    response, rendered = request_template(client)
    greeting = escape(rendered["greeting"])
    expected = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Template</title>
</head>
<body>
    <h1>あいさつ</h1>
    <ul>
        <li>{greeting}</li>
    </ul>
</body>
</html>""".strip()

    assert response.status_code == 200
    assert response.get_data(as_text=True) == expected
