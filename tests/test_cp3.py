import math

import pytest

import app as app_module


@pytest.fixture
def client():
    return app_module.app.test_client()


def assert_rand_response(client, monkeypatch, value, expected):
    monkeypatch.setattr(app_module, "random", lambda: value)
    response = client.get("/rand")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == expected


def test_smaller(client, monkeypatch):
    assert_rand_response(client, monkeypatch, 0.0, "r=0.000 smaller")
    assert_rand_response(client, monkeypatch, 0.2, "r=0.200 smaller")
    assert_rand_response(client, monkeypatch, math.nextafter(0.3, 0.0), "r=0.300 smaller")


def test_medium(client, monkeypatch):
    assert_rand_response(client, monkeypatch, 0.3, "r=0.300 medium")
    assert_rand_response(client, monkeypatch, math.nextafter(0.3, 1.0), "r=0.300 medium")
    assert_rand_response(client, monkeypatch, 0.5, "r=0.500 medium")
    assert_rand_response(client, monkeypatch, math.nextafter(0.7, 0.0), "r=0.700 medium")
    assert_rand_response(client, monkeypatch, 0.7, "r=0.700 medium")


def test_upper(client, monkeypatch):
    assert_rand_response(client, monkeypatch, math.nextafter(0.7, 1.0), "r=0.700 larger")
    assert_rand_response(client, monkeypatch, math.nextafter(1.0, 0.0), "r=1.000 larger")
