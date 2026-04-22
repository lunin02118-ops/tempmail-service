from windows_widget.settings import WidgetSettings, load_saved_settings, normalize_widget_url, resolve_settings, save_settings


def test_normalize_widget_url_adds_native_flag():
    assert normalize_widget_url("https://tempmail-web.onrender.com/widget") == (
        "https://tempmail-web.onrender.com/widget?native=1"
    )


def test_normalize_widget_url_preserves_existing_query():
    assert normalize_widget_url("https://tempmail-web.onrender.com/widget?foo=bar") == (
        "https://tempmail-web.onrender.com/widget?foo=bar&native=1"
    )


def test_resolve_settings_prefers_overrides():
    saved = {
        "url": "https://example.com/widget",
        "width": 420,
        "height": 780,
        "hide_from_taskbar": True,
    }

    settings = resolve_settings(
        saved,
        {
            "width": 520,
            "always_on_top": True,
            "hide_from_taskbar": False,
        },
    )

    assert settings == WidgetSettings(
        url="https://example.com/widget?native=1",
        width=520,
        height=780,
        x=None,
        y=None,
        always_on_top=True,
        pin_desktop=False,
        hide_from_taskbar=False,
        debug=False,
        close_after=0.0,
    )


def test_save_and_load_settings_roundtrip(tmp_path):
    settings = WidgetSettings(url="https://example.com/widget?native=1", width=444, height=666, x=12, y=34)
    target = tmp_path / "settings.json"

    save_settings(settings, path=target)
    loaded = load_saved_settings(target)

    assert loaded["url"] == "https://example.com/widget?native=1"
    assert loaded["width"] == 444
    assert loaded["height"] == 666
    assert loaded["x"] == 12
    assert loaded["y"] == 34
