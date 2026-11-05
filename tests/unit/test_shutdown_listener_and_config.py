import sys

import pytest

from sentinel.agent.config import ApiSettings, ResourceSettings, SchedulerSettings, Settings
from sentinel.oslayer.shutdown_listener import (
    ENDSESSION_LOGOFF,
    WM_ENDSESSION,
    WM_QUERYENDSESSION,
    ShutdownListener,
)


def make_listener(done=True):
    calls = []
    listener = ShutdownListener(lambda kind: calls.append(kind), lambda timeout: done, wait_seconds=0.01)
    return listener, calls


def test_query_end_session_never_blocks_windows_shutdown():
    listener, calls = make_listener()
    assert listener.handle_message(WM_QUERYENDSESSION, 0, 0) == 1
    assert calls == []


def test_end_session_requests_clean_stop_and_distinguishes_logoff():
    listener, calls = make_listener()
    assert listener.handle_message(WM_ENDSESSION, 1, 0) == 0
    assert listener.handle_message(WM_ENDSESSION, 1, ENDSESSION_LOGOFF) == 0
    assert calls == ["shutdown", "logoff"]


def test_cancelled_end_session_is_ignored():
    listener, calls = make_listener()
    assert listener.handle_message(WM_ENDSESSION, 0, 0) == 0  # wParam 0: desligamento cancelado
    assert calls == []


def test_other_messages_use_default_handling():
    listener, _ = make_listener()
    assert listener.handle_message(0x0001, 0, 0) is None


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows a janela é criada de fato")
def test_listener_is_noop_outside_windows():
    listener, _ = make_listener()
    assert listener.start() is False
    listener.stop()


def test_api_must_stay_on_loopback():
    for host in ("127.0.0.1", "::1", "localhost"):
        ApiSettings(host=host)
    with pytest.raises(ValueError, match="127.0.0.1"):
        ApiSettings(host="0.0.0.0")


def test_cross_section_validation():
    with pytest.raises(ValueError, match="max_load_factor"):
        Settings(resources=ResourceSettings(severe_load_factor=8), scheduler=SchedulerSettings(max_load_factor=4))
    with pytest.raises(ValueError, match="disk_free_critical"):
        Settings.model_validate({"alerts": {"disk_free_critical_percent": 20, "disk_free_warning_percent": 10}})
