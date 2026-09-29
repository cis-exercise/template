from html.parser import HTMLParser
from itertools import cycle

import pytest
from flask.signals import template_rendered

import app as app_module


class TemplateDictParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.heading = ""
        self.unordered_lists = 0
        self.list_items = []
        self._capture = None
        self._current_item = None

    def handle_starttag(self, tag, attrs):
        if tag == "title" or tag == "h1":
            self._capture = tag
        elif tag == "ul":
            self.unordered_lists += 1
        elif tag == "li":
            self._current_item = {"text": "", "strong": False}
            self.list_items.append(self._current_item)
        elif tag == "strong" and self._current_item is not None:
            self._current_item["strong"] = True

    def handle_data(self, data):
        if self._capture == "title":
            self.title += data
        elif self._capture == "h1":
            self.heading += data
        elif self._current_item is not None:
            self._current_item["text"] += data

    def handle_endtag(self, tag):
        if tag == self._capture:
            self._capture = None
        if tag == "li":
            self._current_item = None


@pytest.fixture
def client():
    return app_module.app.test_client()


def parse_template_dict(body):
    parser = TemplateDictParser()
    parser.feed(body)
    for item in parser.list_items:
        item["text"] = item["text"].strip()
    return parser


def render_template_dict(title, classes, students):
    with app_module.app.app_context():
        return app_module.app.jinja_env.get_template("template_dict.html").render(
            title=title,
            classes=classes,
            students=students,
        )


def test_template_dict_route_renders_current_context_and_students(client, monkeypatch):
    assignments = cycle(("A", "B", "C"))
    monkeypatch.setattr(app_module, "choice", lambda options: next(assignments))
    rendered = {}

    def capture_template(sender, template, context, **extra):
        rendered["template"] = template
        rendered["title"] = context["title"]
        rendered["classes"] = context["classes"]
        rendered["students"] = context["students"]

    template_rendered.connect(capture_template, app_module.app)
    try:
        response = client.get("/template_dict")
    finally:
        template_rendered.disconnect(capture_template, app_module.app)

    page = parse_template_dict(response.get_data(as_text=True))
    assert response.status_code == 200
    assert rendered["template"].name == "template_dict.html"
    assert rendered["title"] == "学生ごとのクラス分け"
    assert page.title == rendered["title"]
    assert page.heading == rendered["title"]
    assert page.unordered_lists == 1
    assert len(rendered["students"]) == 100
    assert list(rendered["students"])[0] == "2xG2001"
    assert list(rendered["students"])[-1] == "2xG2100"
    expected_items = [
        (f"{student} - {class_name}クラス", class_name in rendered["classes"])
        for student, class_name in rendered["students"].items()
    ]
    actual_items = [(item["text"], item["strong"]) for item in page.list_items]
    assert actual_items == expected_items


def test_template_dict_tracks_changed_context_values():
    title = "受講者ごとの所属"
    classes = ["Gold", "Silver"]
    students = {"student-1": "Gold", "student-2": "Bronze", "student-3": "Silver"}

    page = parse_template_dict(render_template_dict(title, classes, students))

    assert page.title == title
    assert page.heading == title
    assert page.unordered_lists == 1
    assert [(item["text"], item["strong"]) for item in page.list_items] == [
        ("student-1 - Goldクラス", True),
        ("student-2 - Bronzeクラス", False),
        ("student-3 - Silverクラス", True),
    ]


def test_template_dict_shows_empty_state():
    page = parse_template_dict(render_template_dict("所属一覧", ["A"], {}))

    assert page.title == "所属一覧"
    assert page.heading == "所属一覧"
    assert page.unordered_lists == 1
    assert [(item["text"], item["strong"]) for item in page.list_items] == [("表示する情報がありません", False)]
