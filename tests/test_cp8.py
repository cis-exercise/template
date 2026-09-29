from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from werkzeug.exceptions import BadRequestKeyError

import app as app_module


class TaskTablesParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.heading = None
        self.tables = []
        self._heading_text = None
        self._table = None
        self._row = None
        self._cell_text = None

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self._heading_text = ""
        elif tag == "table":
            self._table = {"heading": self.heading, "rows": []}
        elif tag == "tr":
            self._row = []
        elif tag in ("th", "td"):
            self._cell_text = ""

    def handle_data(self, data):
        if self._heading_text is not None:
            self._heading_text += data
        elif self._cell_text is not None:
            self._cell_text += data

    def handle_endtag(self, tag):
        if tag == "h2":
            self.heading = self._heading_text.strip()
            self._heading_text = None
        elif tag in ("th", "td"):
            self._row.append(self._cell_text.strip())
            self._cell_text = None
        elif tag == "tr":
            self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table":
            self.tables.append(self._table)
            self._table = None


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def user_query(monkeypatch):
    query = Mock()
    with app_module.app.app_context():
        monkeypatch.setattr(app_module.User, "query", query)
    return query


@pytest.fixture
def authenticated_client(user_query):
    user = app_module.User(
        id="alice",
        password="secret",
        lastname="Test",
        firstname="Alice",
    )
    user_query.get.return_value = user

    client = app_module.app.test_client()
    response = client.post("/login", data={"id": user.id, "password": "secret"})
    assert response.status_code == 302

    return client, user


@pytest.fixture
def task_query(monkeypatch):
    query = Mock()
    with app_module.app.app_context():
        monkeypatch.setattr(app_module.Task, "query", query)
    return query


@pytest.fixture
def db_session(monkeypatch):
    session = Mock()
    monkeypatch.setattr(app_module.db, "session", session)
    return session


def make_task(task_id, user, name, is_shared=False):
    return SimpleNamespace(
        id=task_id,
        user=user,
        name=name,
        deadline="2030-01-02 03:04:00",
        is_shared=is_shared,
        created_at="2029-01-01 00:00:00",
    )


def test_index_shows_owned_and_shared_tasks(authenticated_client, task_query):
    client, user = authenticated_client
    other_user = SimpleNamespace(id="bob")
    own_tasks = [
        make_task(1, user, "My private task"),
        make_task(3, user, "My shared task", is_shared=True),
    ]
    shared_task_candidates = [
        make_task(2, other_user, "Shared task", is_shared=True),
        make_task(4, other_user, "Other user's private task"),
        make_task(5, user, "My shared task candidate", is_shared=True),
    ]
    filtered_user_ids = []

    def filter_by(**kwargs):
        filtered_user_ids.append(kwargs["user"].id)
        return own_tasks

    task_query.filter_by.side_effect = filter_by
    filter_expressions = []

    def filter_shared_tasks(expression):
        compiled = expression.compile()
        filter_expressions.append((str(compiled).lower(), compiled.params))
        return [task for task in shared_task_candidates if task.user.id != user.id and task.is_shared]

    task_query.filter.side_effect = filter_shared_tasks

    response = client.get("/")

    task_query.filter_by.assert_called_once()
    assert filtered_user_ids == [user.id]
    task_query.filter.assert_called_once()
    filter_sql, filter_params = filter_expressions[0]
    assert "tasks.user_id !=" in filter_sql
    assert "tasks.is_shared" in filter_sql
    assert user.id in filter_params.values()
    assert response.status_code == 200
    parser = TaskTablesParser()
    parser.feed(response.get_data(as_text=True))
    assert len(parser.tables) == 2

    own_table, shared_table = parser.tables
    assert own_table["heading"] == "私のタスク"
    assert own_table["rows"][0] == ["id", "タスク名", "締切日時", "共有", "作成日時", "操作"]
    assert [row[:5] for row in own_table["rows"][1:]] == [
        ["1", "My private task", "2030-01-02 03:04:00", "False", "2029-01-01 00:00:00"],
        ["3", "My shared task", "2030-01-02 03:04:00", "True", "2029-01-01 00:00:00"],
    ]
    assert shared_table["heading"] == "共有タスク"
    assert shared_table["rows"][0] == ["id", "ユーザ", "タスク名", "締切日時", "作成日時"]
    assert shared_table["rows"][1:] == [["2", "bob", "Shared task", "2030-01-02 03:04:00", "2029-01-01 00:00:00"]]
    assert b"Other user's private task" not in response.data
    assert b"My shared task candidate" not in response.data


@pytest.mark.parametrize("shared", [False, True])
def test_create_assigns_current_user_and_shared_flag(authenticated_client, db_session, shared):
    client, user = authenticated_client
    assigned_user_ids = []

    def capture_task(task):
        assigned_user_ids.append(task.user.id)

    db_session.add.side_effect = capture_task
    form_data = {"name": "New task", "deadline": "2030-03-04T05:06"}
    if shared:
        form_data["is_shared"] = "on"

    response = client.post("/create", data=form_data)

    task = db_session.add.call_args.args[0]
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert isinstance(task, app_module.Task)
    assert assigned_user_ids == [user.id]
    assert task.name == "New task"
    assert task.deadline == "2030-03-04T05:06"
    assert task.is_shared is shared
    db_session.add.assert_called_once_with(task)
    db_session.commit.assert_called_once_with()


@pytest.mark.parametrize("missing_field", ["name", "deadline"])
def test_create_rejects_missing_task_fields(authenticated_client, db_session, missing_field):
    client, _ = authenticated_client
    form_data = {"name": "New task", "deadline": "2030-03-04T05:06"}
    form_data.pop(missing_field)

    with pytest.raises(BadRequestKeyError) as error:
        client.post("/create", data=form_data)

    assert error.value.code == 400
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_update_get_shows_owned_task_and_share_state(authenticated_client, task_query):
    client, user = authenticated_client
    task_query.get.return_value = make_task(7, user, "Existing task", is_shared=True)

    response = client.get("/update/7")

    task_query.get.assert_called_once_with(7)
    assert response.status_code == 200
    assert b"Existing task" in response.data
    assert b'id="is_shared" checked' in response.data


@pytest.mark.parametrize("shared", [False, True])
def test_update_changes_task_and_share_state(authenticated_client, task_query, db_session, shared):
    client, user = authenticated_client
    task = make_task(7, user, "Existing task", is_shared=not shared)
    task_query.get.return_value = task
    form_data = {"name": "Updated task", "deadline": "2031-05-06T07:08"}
    if shared:
        form_data["is_shared"] = "on"

    response = client.post("/update/7", data=form_data)

    task_query.get.assert_called_once_with(7)
    assert task.name == "Updated task"
    assert task.deadline == "2031-05-06T07:08"
    assert task.is_shared is shared
    db_session.commit.assert_called_once_with()
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


@pytest.mark.parametrize("missing_field", ["name", "deadline"])
def test_update_rejects_missing_task_fields(authenticated_client, task_query, db_session, missing_field):
    client, user = authenticated_client
    task = make_task(7, user, "Existing task")
    task_query.get.return_value = task
    form_data = {"name": "Updated task", "deadline": "2031-05-06T07:08"}
    form_data.pop(missing_field)

    with pytest.raises(BadRequestKeyError) as error:
        client.post("/update/7", data=form_data)

    assert error.value.code == 400
    db_session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/update/7"),
        ("post", "/update/7"),
        ("get", "/delete/7"),
        ("post", "/delete/7"),
    ],
)
def test_other_users_task_cannot_be_accessed_or_changed(authenticated_client, task_query, db_session, method, path):
    client, _ = authenticated_client
    other_user = SimpleNamespace(id="bob")
    task = make_task(7, other_user, "Another user's task", is_shared=True)
    task_query.get.return_value = task

    if method == "get":
        response = client.get(path)
    else:
        response = client.post(
            path,
            data={"name": "Hijacked", "deadline": "2031-05-06T07:08", "is_shared": "on"},
        )

    task_query.get.assert_called_once_with(7)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert b"Another user's task" not in response.data
    assert task.name == "Another user's task"
    db_session.delete.assert_not_called()
    db_session.commit.assert_not_called()


def test_delete_removes_owned_task_and_commits(authenticated_client, task_query, db_session):
    client, user = authenticated_client
    task = make_task(9, user, "Task to delete")
    task_query.get.return_value = task

    response = client.post("/delete/9")

    task_query.get.assert_called_once_with(9)
    db_session.delete.assert_called_once_with(task)
    db_session.commit.assert_called_once_with()
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_delete_get_shows_confirmation_for_owned_task(authenticated_client, task_query):
    client, user = authenticated_client
    task_query.get.return_value = make_task(9, user, "Task to delete")

    response = client.get("/delete/9")

    task_query.get.assert_called_once_with(9)
    assert response.status_code == 200
    assert b"Task to delete" in response.data
    assert b'action="/delete/9"' in response.data
    assert "以下のデータを削除しますか" in response.get_data(as_text=True)


def test_login_success_redirects_to_home(client, user_query):
    user = app_module.User(
        id="alice",
        password="secret",
        lastname="Test",
        firstname="Alice",
    )
    user_query.get.return_value = user

    response = client.post("/login", data={"id": "alice", "password": "secret"})

    user_query.get.assert_called_once_with("alice")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert client.get("/login").headers["Location"] == "/"


def test_authenticated_user_visiting_login_is_redirected_home(authenticated_client):
    client, _ = authenticated_client

    response = client.get("/login")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_update_rejection_flashes_message_for_another_users_task(authenticated_client, task_query):
    client, _ = authenticated_client
    task_query.get.return_value = make_task(7, SimpleNamespace(id="bob"), "Another user's task", is_shared=True)

    response = client.get("/update/7")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    with client.session_transaction() as session:
        assert ("message", "存在しないタスクです") in session["_flashes"]


def test_update_post_rejection_flashes_message_for_another_users_task(authenticated_client, task_query, db_session):
    client, _ = authenticated_client
    task = make_task(7, SimpleNamespace(id="bob"), "Another user's task", is_shared=True)
    task_query.get.return_value = task

    response = client.post(
        "/update/7",
        data={"name": "Hijacked", "deadline": "2031-05-06T07:08", "is_shared": "on"},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert task.name == "Another user's task"
    db_session.commit.assert_not_called()
    with client.session_transaction() as session:
        assert ("message", "存在しないタスクです") in session["_flashes"]


def test_delete_rejection_flashes_message_for_missing_task(authenticated_client, task_query):
    client, _ = authenticated_client
    task_query.get.return_value = None

    response = client.post("/delete/999")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    with client.session_transaction() as session:
        assert ("message", "存在しないタスクです") in session["_flashes"]


def test_delete_post_rejection_flashes_message_for_another_users_task(authenticated_client, task_query, db_session):
    client, _ = authenticated_client
    task = make_task(7, SimpleNamespace(id="bob"), "Another user's task", is_shared=True)
    task_query.get.return_value = task

    response = client.post("/delete/7")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    db_session.delete.assert_not_called()
    db_session.commit.assert_not_called()
    with client.session_transaction() as session:
        assert ("message", "存在しないタスクです") in session["_flashes"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/"),
        ("post", "/create"),
        ("get", "/update/7"),
        ("post", "/update/7"),
        ("get", "/delete/7"),
        ("post", "/delete/7"),
        ("get", "/users"),
        ("get", "/follow/bob"),
        ("get", "/unfollow/bob"),
    ],
)
def test_protected_routes_require_login(client, method, path):
    request_method = getattr(client, method)
    response = request_method(
        path,
        data={"name": "Unauthenticated", "deadline": "2030-01-02T03:04"},
    )

    location = urlsplit(response.headers["Location"])
    assert response.status_code == 302
    assert location.path == "/login"
    assert parse_qs(location.query)["next"] == [path]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/update/7"),
        ("post", "/update/7"),
        ("get", "/delete/7"),
        ("post", "/delete/7"),
    ],
)
def test_missing_task_cannot_be_updated_or_deleted(authenticated_client, task_query, db_session, method, path):
    client, _ = authenticated_client
    task_query.get.return_value = None
    request_method = getattr(client, method)
    response = request_method(
        path,
        data={"name": "Missing task", "deadline": "2030-01-02T03:04"},
    )

    task_query.get.assert_called_once_with(7)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    db_session.delete.assert_not_called()
    db_session.commit.assert_not_called()


def test_index_shows_empty_states(authenticated_client, task_query):
    client, _ = authenticated_client
    task_query.filter_by.return_value = []
    task_query.filter.return_value = []

    response = client.get("/")

    assert response.status_code == 200
    parser = TaskTablesParser()
    parser.feed(response.get_data(as_text=True))
    assert [table["rows"][1] for table in parser.tables] == [
        ["表示する情報がありません"],
        ["表示する情報がありません"],
    ]


@pytest.mark.parametrize("missing_field", ["id", "password", "lastname", "firstname"])
def test_register_rejects_missing_fields(client, db_session, missing_field):
    form_data = {
        "id": "alice",
        "password": "secret",
        "lastname": "Test",
        "firstname": "Alice",
    }
    form_data[missing_field] = ""

    response = client.post("/register", data=form_data)

    assert response.status_code == 200
    assert "入力されていない項目があります" in response.get_data(as_text=True)
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_register_rejects_duplicate_user(client, user_query, db_session):
    user_query.get.return_value = app_module.User(
        id="alice",
        password="existing-secret",
        lastname="Existing",
        firstname="User",
    )

    response = client.post(
        "/register",
        data={"id": "alice", "password": "secret", "lastname": "Test", "firstname": "Alice"},
    )

    user_query.get.assert_called_once_with("alice")
    assert response.status_code == 200
    assert "ユーザを登録できません" in response.get_data(as_text=True)
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_register_creates_user_with_hashed_password(client, user_query, db_session):
    user_query.get.return_value = None

    response = client.post(
        "/register",
        data={"id": "alice", "password": "secret", "lastname": "Test", "firstname": "Alice"},
    )

    user = db_session.add.call_args.args[0]
    user_query.get.assert_called_once_with("alice")
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert user.id == "alice"
    assert user.verify_password("secret")
    assert user.password_hash != "secret"
    db_session.add.assert_called_once_with(user)
    db_session.commit.assert_called_once_with()


@pytest.mark.parametrize("existing_user", [False, True])
def test_login_rejects_unknown_user_or_wrong_password(client, user_query, existing_user):
    user = None
    if existing_user:
        user = app_module.User(
            id="alice",
            password="correct-password",
            lastname="Test",
            firstname="Alice",
        )
    user_query.get.return_value = user

    response = client.post(
        "/login",
        data={"id": "alice", "password": "wrong-password"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "ユーザIDかパスワードが誤っています" in response.get_data(as_text=True)
    assert client.get("/").headers["Location"].startswith("/login?")


def test_logout_ends_authenticated_session(authenticated_client):
    client, _ = authenticated_client

    response = client.get("/logout")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert client.get("/").headers["Location"].startswith("/login?")


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_crud_does_not_redirect_as_success_when_commit_fails(authenticated_client, task_query, db_session, operation):
    client, user = authenticated_client
    db_session.commit.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        if operation == "create":
            client.post(
                "/create",
                data={"name": "New task", "deadline": "2030-03-04T05:06"},
            )
        else:
            task_query.get.return_value = make_task(7, user, "Existing task")
            if operation == "update":
                client.post(
                    "/update/7",
                    data={"name": "Updated task", "deadline": "2031-05-06T07:08"},
                )
            else:
                client.post("/delete/7")

    db_session.commit.assert_called_once_with()
