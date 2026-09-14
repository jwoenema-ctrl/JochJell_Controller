"""Narrow desktop bridge: explicit, confirmed switching from the local Settings page."""
from urllib.parse import urlsplit
from threading import Lock


class NativeConnectionAPI:
    def __init__(self, window, controller, switch):
        self._window = window
        self._controller = controller
        self._switch = switch
        self._lock = Lock()

    def switch_mode(self, mode):
        if mode not in ("z21", "simulation"):
            return {"accepted": False, "error": "Unknown connection mode"}
        window, controller = self._window(), self._controller()
        if window is None or controller is None:
            return {"accepted": False, "error": "Controller is not ready"}
        current, expected = urlsplit(window.get_current_url() or ""), urlsplit(controller.url)
        if (current.scheme, current.netloc, current.path.rstrip("/")) != (expected.scheme, expected.netloc, ""):
            return {"accepted": False, "error": "Only the local controller page can switch connection"}
        if not self._lock.acquire(blocking=False):
            return {"accepted": False, "error": "A connection change is already in progress"}
        try:
            message = ("Stop all trains, switch track power off and save the current layout before changing mode? "
                       "Connecting to Z21 uses the address last saved in Settings. "
                       "Verify decoder addresses and feedback wiring before operating physical trains.")
            if not window.create_confirmation_dialog("Connect to Z21?" if mode == "z21" else "Use simulation?", message):
                return {"accepted": False, "cancelled": True}
            switch_result = self._switch(mode == "z21")
            response = {"accepted": True, "mode": mode}
            if isinstance(switch_result, dict):
                response.update(switch_result)
                response["accepted"] = True
            active_controller = self._controller()
            app = getattr(active_controller, "app", None)
            if app is not None and callable(getattr(app, "settings_payload", None)):
                payload = app.settings_payload()
                runtime = payload.get("runtime", {}) if isinstance(payload, dict) else {}
                if isinstance(runtime, dict):
                    response["mode"] = runtime.get("connection_mode", mode)
                    response["transport_profile"] = runtime.get("transport_profile")
                    response["transport_status"] = runtime.get("transport_status")
            return response
        except Exception as error:
            return {"accepted": False, "error": str(error)}
        finally:
            self._lock.release()
