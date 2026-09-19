"""Embedded Windows edition: no external browser or separate launcher window."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import tempfile
import threading
import time

import webview

from desktop_app import DesktopController, data_directory
from native_connection import NativeConnectionAPI


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    temporary = tempfile.TemporaryDirectory(prefix='h0-native-test-', ignore_cleanup_errors=True) if args.smoke_test else None
    directory = Path(temporary.name) if temporary else data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    controller = None
    lock = threading.RLock()
    tested = False
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
    window = None
    bridge = NativeConnectionAPI(lambda: window, lambda: controller, lambda physical: connect(physical, switching=True))
    window = webview.create_window('H0 Control Desk', html='<html><body style="font-family:Segoe UI;padding:40px"><h1>H0 Control Desk</h1><p>Starting your railway workspace…</p></body></html>', width=1400, height=950, min_size=(800, 600), hidden=bool(args.smoke_test), js_api=bridge)

    def notice(title, message):
        window.create_confirmation_dialog(title, message)

    def stop():
        nonlocal controller
        if controller is not None:
            controller.close()
            controller = None

    def connect(physical=False, *, switching=False):
        nonlocal controller
        with lock:
            try:
                saved_layout = None
                if switching and controller is not None:
                    with controller.app._lock:
                        controller.app.command({"type": "track_power", "enabled": False})
                        saved_layout = controller.app.save_layout()["layout_id"]
                stop()
                controller = DesktopController(directory, physical=physical, port=0)
                if saved_layout:
                    controller.app.load_layout(saved_layout)
                window.set_title('H0 Control Desk — ' + ('Z21' if physical else 'Simulation'))
                window.load_url(controller.url + ('/#settings' if switching else ''))
            except Exception as error:
                if controller is not None:
                    notice('Controller needs attention', str(error))
                else:
                    window.load_html('<html><body style="font-family:Segoe UI;padding:40px"><h1>Controller could not start</h1><p>' + html.escape(str(error)) + '</p><p>Close and reopen this app to retry in simulation. Close any other desktop edition using the same data.</p></body></html>')
                if switching:
                    raise

    def closing():
        with lock:
            stop()
            return True

    def check_embedded_page():
        nonlocal tested
        if not args.smoke_test or tested or controller is None:
            return
        if not str(window.get_current_url() or '').startswith(controller.url):
            return
        tested = True
        result = {'passed': False}
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ready = window.evaluate_js("document.querySelector('#settings-save-status')?.textContent.includes('up to date') || false")
                if ready:
                    break
                time.sleep(.1)
            assert ready, 'Embedded frontend did not load controller settings'
            window.evaluate_js("document.querySelector('[data-workspace=\"settings\"]').click()")
            assert window.evaluate_js("getComputedStyle(document.querySelector('.dashboard')).display") == 'none'
            window.evaluate_js("const theme=document.querySelector('#setting-theme');theme.value='dark';theme.dispatchEvent(new Event('change',{bubbles:true}))")
            assert window.evaluate_js("document.documentElement.dataset.theme") == 'dark'
            window.evaluate_js("document.querySelector('[data-workspace=\"trains\"]').click(); [...document.querySelectorAll('.train-row')].find(x=>x.textContent.includes('ICE 3')).click();document.querySelector('#direction-reverse').click()")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and window.evaluate_js("document.querySelector('#direction-reverse').getAttribute('aria-pressed')") != 'true':
                time.sleep(.1)
            assert window.evaluate_js("document.querySelector('#direction-reverse').getAttribute('aria-pressed')") == 'true'
            window.evaluate_js("document.querySelector('[data-workspace=\"layout\"]').click()")
            assert window.evaluate_js("getComputedStyle(document.querySelector('#layout-info-panel')).display") != 'none'
            assert window.evaluate_js("document.querySelector('#layout-info-metrics').textContent.includes('Route operations')")
            assert not window.evaluate_js("document.querySelector('#block-id').readOnly")
            window.evaluate_js("document.querySelector('[data-workspace=\"settings\"]').click()")
            assert window.evaluate_js("typeof window.pywebview.api.switch_mode") == "function"
            assert not window.evaluate_js("document.querySelector('#settings-connect-z21').disabled")
            assert not window.evaluate_js("document.querySelector('#setting-z21-wlan').checked")
            assert window.evaluate_js("document.querySelector('#setting-z21-wlan-help').textContent.includes('does not join Wi-Fi')")
            window.evaluate_js("document.querySelector('#setting-z21-wlan').click()")
            assert window.evaluate_js("document.querySelector('#setting-z21-wlan').checked")
            assert window.evaluate_js("document.querySelector('#settings-connect-z21').disabled")
            window.evaluate_js("document.querySelector('#settings-discard').click()")
            assert not window.evaluate_js("document.querySelector('#setting-z21-wlan').checked")
            previous_url = controller.url
            original_dialog = window.create_confirmation_dialog
            try:
                window.create_confirmation_dialog = lambda *args: False
                assert bridge.switch_mode("z21").get("cancelled")
                assert controller.url == previous_url
                window.create_confirmation_dialog = lambda *args: True
                assert bridge.switch_mode("simulation")["accepted"]
            finally:
                window.create_confirmation_dialog = original_dialog
            assert controller.url != previous_url
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                ready = window.evaluate_js("document.querySelector('#settings-save-status')?.textContent.includes('up to date') || false")
                if ready and str(window.get_current_url()).startswith(controller.url):
                    break
                time.sleep(.1)
            assert ready, "Settings did not reload after switching modes"
            assert all(float(train.get("speed", 0)) == 0 for train in controller.app.trains)
            result = {'passed': True, 'embedded_window': True, 'renderer': 'edgechromium', 'settings': True, 'wlan_settings': True, 'theme': True, 'direction': True, 'layout_info': True, 'editable_block_id': True, 'settings_connection_bridge': True, 'physical_connect_cancelled': True, 'simulation_switch_preserves_stopped_layout': True, 'external_browser': False}
        except Exception as error:
            result['error'] = str(error)
        finally:
            args.smoke_test.write_text(json.dumps(result), encoding='utf-8')
            window.destroy()

    window.events.closing += closing
    window.events.loaded += check_embedded_page
    menu = []
    try:
        webview.start(lambda: connect(False), gui='edgechromium', menu=menu, private_mode=False, storage_path=str(directory / 'webview'))
    finally:
        with lock:
            stop()
        if temporary:
            # WebView2 child processes release profile files asynchronously.
            time.sleep(.5)
            temporary.cleanup()


if __name__ == '__main__':
    main()
