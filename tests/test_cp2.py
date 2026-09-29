import pytest

import app as app_module


@pytest.fixture
def client():
    return app_module.app.test_client()


def test_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "Hello!"
