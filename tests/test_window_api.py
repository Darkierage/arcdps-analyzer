import inspect
import sys
import types

from wvw_analyzer import main


def test_js_api_exposes_only_methods(monkeypatch):
    """pywebview walks every public attribute of js_api, recursively, on each page load
    (webview/util.py get_functions). A public `window` attribute made it walk the WinForms /
    WebView2 object tree from a background thread, and the packaged app deadlocked on start.
    Only methods may be public on the API object, also after the window is opened."""
    created = {}

    def create_window(*args, **kwargs):
        created.update(kwargs)
        return object()  # stands in for the pywebview Window

    fake = types.SimpleNamespace(create_window=create_window, start=lambda: None)
    monkeypatch.setitem(sys.modules, "webview", fake)

    api = main.WindowApi()
    assert main._open_window("http://127.0.0.1:8765", api) is True
    assert created["js_api"] is api and api._window is not None
    public = [n for n in dir(api) if not n.startswith("_")]
    assert public == ["pick_folder"]
    assert all(inspect.ismethod(getattr(api, n)) for n in public)
