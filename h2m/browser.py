"""Client DevTools (CDP) minimal et lancement de Chromium."""
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request

from h2m.ui import die


class CDP:
    def __init__(self, ws_url):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=180, suppress_origin=True)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(f"{method} : {msg['error'].get('message')}")
                return msg.get("result", {})

    def ev(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or "erreur JS")
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return json.loads(opener.open(url, timeout=timeout).read())


def stop_chrome(proc):
    """Arrête Chromium et tous ses processus enfants."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def launch_chrome(exe, tmp, width, height):
    """Lance Chromium headless, retourne (process, port)."""
    reports = []
    for n, mode in enumerate(("--headless=new", "--headless")):
        port = free_port()
        log_path = tmp / f"chrome{n}.log"
        cmd = [
            exe, mode,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={tmp / ('profile' + str(n))}",
            "--no-sandbox", "--no-zygote", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-extensions", "--disable-component-update",
            "--hide-scrollbars", "--mute-audio",
            "--no-first-run", "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--force-device-scale-factor=1",
            "--autoplay-policy=no-user-gesture-required",
            f"--window-size={width},{height}",
            "about:blank",
        ]
        with open(log_path, "wb") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < 90:  # le démarrage peut être lent sous proot
            if proc.poll() is not None:
                break
            try:
                http_json(f"http://127.0.0.1:{port}/json/version", 1)
                return proc, port
            except Exception:
                time.sleep(0.5)
        code = proc.poll()
        stop_chrome(proc)
        try:
            lines = [l for l in log_path.read_text(errors="ignore").splitlines()
                     if "dbus" not in l and "udev" not in l and l.strip()]
        except Exception:
            lines = []
        reports.append(f"  {mode} : {'arrêté (code ' + str(code) + ')' if code is not None else 'ne répond pas'}\n    "
                       + "\n    ".join(lines[-5:]))
    die("Chromium n'a pas démarré.\n" + "\n".join(reports))


def page_ws_url(port):
    for _ in range(60):
        try:
            for t in http_json(f"http://127.0.0.1:{port}/json/list", 2):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    die("Impossible de se connecter à Chromium (DevTools).")
