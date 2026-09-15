"""Trusted local registration CLI. The browser never supplies executable argv."""
import argparse
from pathlib import Path
from . import settings


def register(name, adapter, model, effort="medium", max_calls=240, command=None):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 48
            or adapter not in ("codex", "command") or not isinstance(model, str)
            or not 1 <= len(model.strip()) <= 120
            or effort not in ("minimal", "low", "medium", "high", "xhigh")
            or type(max_calls) is not int or not 1 <= max_calls <= 2000):
        raise ValueError("Invalid connection name, adapter, model, effort or budget.")
    entry = {"adapter": adapter, "model": model.strip(), "effort": effort, "max_calls": max_calls}
    if adapter == "command":
        from .driver import _command_json
        if command is None:
            raise ValueError("A trusted command wrapper is required.")
        import json
        entry["command"] = json.loads(_command_json(command))
    saved = settings.load_settings()
    if saved is None and Path(settings.SETTINGS_PATH).exists():
        raise ValueError("Settings are damaged; preserve and repair them before registering.")
    saved = saved or {}
    connections = saved.setdefault("agent_connections", {})
    if not isinstance(connections, dict):
        raise ValueError("Invalid connection registry.")
    connections[name.strip()] = entry
    settings.save_settings(saved, trusted=True)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Register a trusted local game Agent connection; no model call.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--adapter", choices=("codex", "command"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--max-calls", type=int, default=240)
    parser.add_argument("--command", help="Trusted JSON argv wrapper (command adapter only)")
    args = parser.parse_args()
    register(**vars(args))
    print("Connection registered. Refresh the browser; check the connection before playing. / 已登记，刷新网页后可检查连接。")


if __name__ == "__main__":
    main()
