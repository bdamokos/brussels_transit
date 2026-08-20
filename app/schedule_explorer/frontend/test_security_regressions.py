from pathlib import Path


FRONTEND_JS = Path(__file__).parent / "js"


def test_fetch_error_uses_a_constant_console_format_string():
    source = (FRONTEND_JS / "app.js").read_text(encoding="utf-8")

    assert "console.error('Error fetching URL: %s', url, error);" in source
    assert "console.error(`Error fetching ${url}:`, error);" not in source


def test_stop_explorer_encodes_dom_provider_value_before_html_rendering():
    source = (FRONTEND_JS / "stop_explorer.js").read_text(encoding="utf-8")
    render_start = source.index("routesContainer.innerHTML = results.map")
    render_end = source.index("} catch (error)", render_start)
    render_source = source[render_start:render_end]

    assert (
        "const safeProviderId = escapeHtml(encodeURIComponent(providerSelect.value));"
        in source
    )
    assert render_source.count("${safeProviderId}") == 2
    assert "${providerSelect.value}" not in render_source
