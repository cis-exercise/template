from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app as app_module


@pytest.fixture
def client():
    return app_module.app.test_client()


@pytest.fixture
def mocked_task_query(monkeypatch):
    query = Mock()
    with app_module.app.app_context():
        monkeypatch.setattr(app_module.Task, "query", query)
    return query


@pytest.fixture
def mocked_db_session(monkeypatch):
    session = Mock()
    monkeypatch.setattr(app_module.db, "session", session)
    return session


def test_index_reads_tasks_from_mocked_db(client, mocked_task_query):
    tasks = [
        SimpleNamespace(id=1, name="Task one", deadline="2030-01-02 03:04:00", created_at="2029-01-01"),
        SimpleNamespace(id=2, name="Task two", deadline="2030-02-03 04:05:00", created_at="2029-01-02"),
    ]
    mocked_task_query.all.return_value = tasks

    response = client.get("/")

    mocked_task_query.all.assert_called_once_with()
    assert response.status_code == 200
    assert b"Task one" in response.data
    assert b"Task two" in response.data


def test_create_adds_task_and_commits(client, mocked_db_session):
    response = client.post(
        "/create",
        data={"name": "New task", "deadline": "2030-03-04T05:06"},
    )

    task = mocked_db_session.add.call_args.args[0]
    assert response.status_code == 200
    assert isinstance(task, app_module.Task)
    assert task.name == "New task"
    assert task.deadline == "2030-03-04T05:06"
    mocked_db_session.add.assert_called_once_with(task)
    mocked_db_session.commit.assert_called_once_with()


def test_update_get_shows_task_from_mocked_db(client, mocked_task_query):
    task = SimpleNamespace(id=7, name="Existing task", deadline="2030-04-05 06:07:00")
    mocked_task_query.get.return_value = task

    response = client.get("/update/7")

    mocked_task_query.get.assert_called_once_with(7)
    assert response.status_code == 200
    assert b"Existing task" in response.data
    assert b"/update/7" in response.data


def test_update_post_changes_task_and_commits(client, mocked_task_query, mocked_db_session):
    task = SimpleNamespace(id=7, name="Existing task", deadline="2030-04-05 06:07:00")
    mocked_task_query.get.return_value = task

    response = client.post(
        "/update/7",
        data={"name": "Updated task", "deadline": "2031-05-06T07:08"},
    )

    mocked_task_query.get.assert_called_once_with(7)
    assert task.name == "Updated task"
    assert task.deadline == "2031-05-06T07:08"
    mocked_db_session.commit.assert_called_once_with()
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_delete_get_shows_task_from_mocked_db(client, mocked_task_query):
    task = SimpleNamespace(id=9, name="Task to delete", deadline="2030-06-07 08:09:00")
    mocked_task_query.get.return_value = task

    response = client.get("/delete/9")

    mocked_task_query.get.assert_called_once_with(9)
    assert response.status_code == 200
    assert b"Task to delete" in response.data
    assert b"/delete/9" in response.data


def test_delete_post_deletes_task_and_commits(client, mocked_task_query, mocked_db_session):
    task = SimpleNamespace(id=9, name="Task to delete", deadline="2030-06-07 08:09:00")
    mocked_task_query.get.return_value = task

    response = client.post("/delete/9")

    mocked_task_query.get.assert_called_once_with(9)
    mocked_db_session.delete.assert_called_once_with(task)
    mocked_db_session.commit.assert_called_once_with()
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
