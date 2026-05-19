from fastapi.testclient import TestClient

from app.schedule_explorer.frontend.static import SCHEDULE_EXPLORER_API_URL, app


def test_template_routes_render_with_current_starlette_signature():
    client = TestClient(app)

    for path in ("/", "/stop_explorer.html", "/get_gtfs_data.html"):
        response = client.get(path)

        assert response.status_code == 200
        assert f'window.API_BASE_URL = "{SCHEDULE_EXPLORER_API_URL}"' in response.text
