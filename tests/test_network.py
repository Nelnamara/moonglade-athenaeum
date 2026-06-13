"""Tests for network-layer functions with mocked requests.Session."""
import json
import pytest

import pixai_gallery_backup as core


def _make_response(mocker, status_code=200, json_body=None, text="", raises=None):
    """Build a fake requests.Response-like mock."""
    resp = mocker.MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = ValueError("no json")
    if raises:
        resp.raise_for_status.side_effect = raises
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# gql()
# ---------------------------------------------------------------------------

class TestGql:
    def test_returns_data_on_success(self, mock_session):
        payload = {"data": {"user": {"taskSummaries": {"edges": [], "pageInfo": {}}}}}
        mock_session.get.return_value = _make_response(
            pytest.importorskip("unittest.mock"), json_body=payload
        )
        # Re-mock properly
        mock_session.get.return_value.status_code = 200
        mock_session.get.return_value.json.return_value = payload
        result = core.gql(mock_session, {"last": 10, "userId": "u1"})
        assert result == payload["data"]

    def test_raises_on_401(self, mock_session, mocker):
        resp = _make_response(mocker, status_code=401, json_body={})
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="401"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_on_non_json(self, mock_session, mocker):
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.text = "not json at all"
        resp.json.side_effect = ValueError("no json")
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="non-JSON"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_on_graphql_errors(self, mock_session, mocker):
        payload = {"errors": [{"message": "something broke"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="GraphQL error"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})

    def test_raises_persisted_query_not_found(self, mock_session, mocker):
        payload = {"errors": [{"message": "PersistedQueryNotFound"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        with pytest.raises(core.PixAIError, match="hash not recognized"):
            core.gql(mock_session, {"last": 10, "userId": "u1"})


# ---------------------------------------------------------------------------
# resolve_media()
# ---------------------------------------------------------------------------

class TestResolveMedia:
    def test_picks_public_variant(self, mock_session, mocker):
        obj = {
            "urls": [
                {"variant": "THUMBNAIL", "url": "https://thumb.example.com/t"},
                {"variant": "PUBLIC", "url": "https://cdn.example.com/full"},
            ],
            "width": 512,
            "height": 768,
            "type": "IMAGE",
        }
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp

        url, info = core.resolve_media(mock_session, "mid123")
        assert url == "https://cdn.example.com/full"
        assert info["width"] == 512

    def test_returns_none_on_request_error(self, mock_session, mocker):
        import requests
        mock_session.get.side_effect = requests.RequestException("timeout")
        url, info = core.resolve_media(mock_session, "mid123")
        assert url is None
        assert info == {}

    def test_falls_back_when_no_public(self, mock_session, mocker):
        obj = {
            "urls": [{"variant": "THUMBNAIL", "url": "https://thumb.example.com/t"}],
            "width": 100,
            "height": 100,
            "type": "IMAGE",
        }
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        url, info = core.resolve_media(mock_session, "mid456")
        assert url is not None

    def test_returns_none_on_empty_urls(self, mock_session, mocker):
        obj = {"urls": [], "width": None, "height": None, "type": ""}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = obj
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        url, info = core.resolve_media(mock_session, "mid789")
        assert url is None


# ---------------------------------------------------------------------------
# _quick_count() — verify it returns 0 on PixAIError without raising
# ---------------------------------------------------------------------------

class TestQuickCount:
    def test_returns_zero_on_api_error(self, mock_session, mocker):
        payload = {"errors": [{"message": "INTERNAL_SERVER_ERROR"}]}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        result = core._quick_count(mock_session, page_size=10)
        assert result == 0

    def test_counts_single_page(self, mock_session, mocker):
        conn_data = {
            "edges": [
                {"node": {"mediaId": "m1", "batchMediaIds": None}},
                {"node": {"mediaId": "m2", "batchMediaIds": ["m2", "m3"]}},
            ],
            "pageInfo": {"hasPreviousPage": False, "startCursor": None},
        }
        payload = {"data": {"user": {"taskSummaries": conn_data}}}
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        mock_session.get.return_value = resp
        # edge 1 → 1 id, edge 2 → 2 ids  (m2 deduped + m3)
        result = core._quick_count(mock_session, page_size=10)
        assert result == 3
