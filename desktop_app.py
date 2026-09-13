"""Windows desktop launcher. Persistent data never lives in the executable bundle."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import urllib.request
import webbrowser

from backend.api.server import ControllerApplication, make_server, startup_z21_endpoint
from backend.infrastructure.settings import SQLiteSettingsRepository


def data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "H0 Control Desk"


class DesktopController:
    def __init__(self, directory: Path, *, physical: bool = False, port: int = 8765):
        directory.mkdir(parents=True, exist_ok=True)
        self.instance_lock = (directory / 'controller.lock').open('a+b')
        if os.name == 'nt':
            import msvcrt
            self.instance_lock.seek(0, 2)
            if self.instance_lock.tell() == 0:
                self.instance_lock.write(b'0')
                self.instance_lock.flush()
            self.instance_lock.seek(0)
            try:
                msvcrt.locking(self.instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.instance_lock.close()
                raise RuntimeError('This app-data directory already has a running controller. Open its existing window instead.') from None
        try:
            self._start(directory, physical=physical, port=port)
        except Exception:
            self.instance_lock.close()
            raise

    def _start(self, directory: Path, *, physical: bool, port: int):
        database = directory / "controller.sqlite3"
        settings = SQLiteSettingsRepository(database)
        try:
            host, z21_port = startup_z21_endpoint(settings.load(), {"H0_TRACK_SYSTEM": "z21" if physical else "simulation"})
        finally:
            settings.close()
        feedback_map = {}
        if physical:
            for entry in os.environ.get('H0_Z21_FEEDBACK_MAP', '').split(','):
                if not entry.strip():
                    continue
                contact, block = entry.strip().split('=')
                module, input_number = map(int, contact.split(':'))
                feedback_map[(module, input_number)] = block.strip()
        self.app = ControllerApplication.sample(database_path=str(database), z21_host=host, z21_port=z21_port, feedback_map=feedback_map)
        try:
            self.server = make_server(port=port, application=self.app)
        except Exception:
            self.app.close()
            raise
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        with self.app._lock:
            self.app.runtime.dispatcher.emergency_stop()
            result = self.app.runtime.track.set_power(False)
            if not result.accepted:
                raise RuntimeError("Track power-off could not be confirmed. Check the Z21 and stop trains physically before exiting.")
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.app.close()
        self.instance_lock.close()


def smoke_test(destination: Path):
    """Exercise the actual frozen imports, Tcl/Tk, assets, database and HTTP server."""
    root = tk.Tk()
    root.withdraw()
    try:
        with tempfile.TemporaryDirectory(prefix="h0-exe-test-") as directory:
            controller = DesktopController(Path(directory), port=0)
            try:
                if os.name == 'nt':
                    try:
                        duplicate = DesktopController(Path(directory), port=0)
                    except RuntimeError:
                        pass
                    else:
                        duplicate.close()
                        raise AssertionError('Duplicate controller was allowed')
                with urllib.request.urlopen(controller.url, timeout=5) as response:
                    html = response.read().decode()
                    assert 'direction-forward' in html and 'settings-page' in html
                with urllib.request.urlopen(controller.url + '/minimal.css', timeout=5) as response:
                    assert b'.direction-control' in response.read()
                with urllib.request.urlopen(controller.url + '/api/settings', timeout=5) as response:
                    settings = json.load(response)
                    assert settings['runtime']['connection_mode'] == 'simulation'
                destination.write_text(json.dumps({'passed': True, 'frozen_assets': True, 'tk': root.tk.call('info', 'patchlevel'), 'simulation': True}), encoding='utf-8')
            finally:
                controller.close()
    finally:
        root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test(args.smoke_test)
        return
    root = tk.Tk()
    root.title('H0 Control Desk')
    root.geometry('480x320')
    root.resizable(False, False)
    pane = ttk.Frame(root, padding=28)
    pane.pack(fill='both', expand=True)
    ttk.Label(pane, text='H0 Control Desk', font=('Segoe UI', 22)).pack(anchor='w')
    ttk.Label(pane, text='Your railway controller · Windows edition').pack(anchor='w', pady=(5, 22))
    mode = tk.StringVar(value='Simulation')
    selector = ttk.Combobox(pane, textvariable=mode, values=('Simulation', 'Z21 · saved IP address'), state='readonly')
    selector.pack(fill='x')
    status = tk.StringVar(value='Ready. Simulation never connects to physical trains.')
    ttk.Label(pane, textvariable=status, wraplength=420).pack(anchor='w', pady=16)
    controller = None

    def start():
        nonlocal controller
        if controller:
            webbrowser.open(controller.url)
            return
        physical = mode.get() != 'Simulation'
        if physical and not messagebox.askyesno('Connect to Z21?', 'Connect to the saved Z21 IP address? Verify the layout, decoder addresses and feedback configuration before operating trains.', parent=root):
            return
        try:
            controller = DesktopController(data_directory(), physical=physical)
            selector.configure(state='disabled')
            status.set(f"{'Z21' if physical else 'Simulation'} running. Keep this window open.\n{controller.url}")
            start_button.configure(text='Open control desk')
            webbrowser.open(controller.url)
        except Exception as error:
            messagebox.showerror('Controller could not start', str(error), parent=root)

    def quit_app():
        if controller:
            try:
                controller.close()
            except Exception as error:
                messagebox.showerror('Stop needs attention', str(error), parent=root)
                return
        root.destroy()

    start_button = ttk.Button(pane, text='Start controller', command=start)
    start_button.pack(fill='x', pady=4)
    ttk.Button(pane, text='Stop controller and exit', command=quit_app).pack(fill='x', pady=4)
    root.protocol('WM_DELETE_WINDOW', quit_app)
    root.mainloop()


if __name__ == '__main__':
    main()
