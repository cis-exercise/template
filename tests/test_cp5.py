from html.parser import HTMLParser

import pytest
from flask.signals import template_rendered

import app as app_module


class TemplateListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.heading = ""
        self.list_items = []
        self.unordered_lists = 0
        self._capture = None

    def handle_starttag(self, tag, attrs):
        if tag == "title" or tag == "h1":
            self._capture = tag
        elif tag == "ul":
            self.unordered_lists += 1
        elif tag == "li":
            self.list_items.append("")
            self._capture = "li"

    def handle_data(self, data):
        if self._capture == "title":
            self.title += data
        elif self._capture == "h1":
            self.heading += data
        elif self._capture == "li":
            self.list_items[-1] += data

    def handle_endtag(self, tag):
        if tag == self._capture:
            self._capture = None


@pytest.fixture
def client():
    return app_module.app.test_client()


def parse_template_list(body):
    parser = TemplateListParser()
    parser.feed(body)
    return parser


def render_template_list(title, students):
    with app_module.app.app_context():
        return app_module.app.jinja_env.get_template("template_list.html").render(
            title=title,
            students=students,
        )


def test_template_list_route_renders_context_and_students(client):
    rendered = {}

    def capture_template(sender, template, context, **extra):
        rendered["template"] = template
        rendered["title"] = context["title"]
        rendered["students"] = context["students"]

    template_rendered.connect(capture_template, app_module.app)
    try:
        response = client.get("/template_list")
    finally:
        template_rendered.disconnect(capture_template, app_module.app)

    page = parse_template_list(response.get_data(as_text=True))
    assert response.status_code == 200
    assert rendered["template"].name == "template_list.html"
    assert page.title == rendered["title"]
    assert page.heading == rendered["title"]
    assert page.unordered_lists == 1
    assert len(rendered["students"]) == 100
    assert rendered["students"][0] == "2xG2001"
    assert rendered["students"][-1] == "2xG2100"
    assert page.list_items == rendered["students"]


def test_template_list_tracks_title_and_student_data():
    title = "受講者一覧"
    students = ["2xG001", "2xG002", "2xG003"]
    page = parse_template_list(render_template_list(title, students))

    assert page.title == title
    assert page.heading == title
    assert page.unordered_lists == 1
    assert page.list_items == students


def test_template_list_shows_empty_state():
    title = "受講者一覧"
    students = []
    page = parse_template_list(render_template_list(title, students))

    assert page.title == title
    assert page.heading == title
    assert page.unordered_lists == 1
    assert page.list_items == ["表示する情報がありません"]
