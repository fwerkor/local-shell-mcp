from types import SimpleNamespace

from local_shell_mcp import controller_restart


def test_reject_restart_when_server_missing_or_not_ready():
    controller_restart.clear_active_server()
    assert not controller_restart.restart_available()
    assert controller_restart.request_controller_restart() is False

    server = SimpleNamespace(started=False, should_exit=False)
    controller_restart.set_active_server(server)
    assert not controller_restart.restart_requested()
    assert not controller_restart.restart_available()
    assert controller_restart.request_controller_restart() is False

    server.started = True
    server.should_exit = True
    assert not controller_restart.restart_available()
    assert controller_restart.request_controller_restart() is False
    controller_restart.clear_active_server()


def test_request_graceful_restart_and_reset_for_next_server():
    server = SimpleNamespace(started=True, should_exit=False)
    controller_restart.set_active_server(server)
    assert controller_restart.restart_available()
    assert controller_restart.request_controller_restart()
    assert server.should_exit
    assert controller_restart.restart_requested()
    assert not controller_restart.request_controller_restart()

    controller_restart.clear_active_server()
    next_server = SimpleNamespace(started=True, should_exit=False)
    controller_restart.set_active_server(next_server)
    assert not controller_restart.restart_requested()
    assert controller_restart.restart_available()
    controller_restart.clear_active_server()
