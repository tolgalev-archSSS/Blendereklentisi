# =====================================================================
# server.py - Gomulu HTTP REST API sunucusu (Threading, localhost:8123)
#
# KRITIK MIMARI KURALI: bpy thread-safe degildir. Bu sunucu hicbir
# zaman bpy.context / bpy.data uzerinde dogrudan islem YAPMAZ.
# Blender tarafinda yapilmasi gereken her sey EXECUTION_QUEUE uzerinden
# ana Blender thread'ine iletilir ve threading.Event ile senkronize
# sekilde sonucu beklenir.
#
# NOT: Bu sunucuda HICBIR FBX/OBJ export islemi yoktur. Eski "MLAO"
# loglari farkli bir v2.5 eklentisinden geliyordu; bu eklenti sadece
# isimlendirme + veritabani kaydeder, dosya disa aktarimi yapmaz.
# =====================================================================

import os
import re
import json
import uuid
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"
PORT = 8123
SERVER_URL = "http://%s:%d" % (HOST, PORT)

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")

_server_instance = None
_server_thread = None


# ---------------------------------------------------------------------
# Govev kuyruguna islem koyup sonucunu (senkron) bekleyen yardimci.
# task dict: {"action": str, "payload": dict}
# Timer callback bu sozluge "result" anahtari ile sonucu yazar ve
# event.set() cagirir.
# ---------------------------------------------------------------------
def dispatch_to_blender(action, payload, timeout=15.0):
    from . import EXECUTION_QUEUE  # gecici import: addon yuklendikten sonra

    ev = threading.Event()
    task = {"action": action, "payload": payload or {}, "event": ev, "result": None}
    EXECUTION_QUEUE.put(task)
    ok = ev.wait(timeout)
    if not ok:
        raise TimeoutError("Blender ana thread'i 15 sn icinde gorevi tamamlamadi.")
    return task.get("result") or {"status": "error", "message": "Sonuc uretilmedi"}


def _json_default(o):
    """Set/list gibi JSON'a cevrilemeyen tipleri güvenli hale getirir."""
    try:
        return list(o)
    except TypeError:
        return str(o)


class PipelineHandler(BaseHTTPRequestHandler):
    server_version = "AssetPipeline/1.0"
    protocol_version = "HTTP/1.1"

    # ---- CORS + temel basliklar -------------------------------------
    def _send(self, code, body_bytes, content_type="application/json; charset=utf-8"):
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body_bytes)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Istemci (tarayici sekmesi vb.) baglantiyi kapattiysa sessizce geç;
            # konsolda [WinError 10038] tarzı gürültü olusturma.
            pass

    def _send_json(self, obj, code=200):
        raw = json.dumps(obj, ensure_ascii=False, default=_json_default).encode("utf-8")
        self._send(code, raw)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):
        # Konsol gürültüsünü azalt: yalnızca hatali istekler loglanır.
        try:
            code = args[1]
            if str(code).startswith(("4", "5")):
                print("[PIPELINE-SUNUCU] %s %s -> %s" % (self.command, self.path, code))
        except IndexError:
            pass

    # ---- OPTIONS (CORS preflight) -----------------------------------
    def do_OPTIONS(self):
        self._send(204, b"")

    # ---- GET ---------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self._serve_ui()
            return

        if path == "/api/ping":
            self._send_json({"status": "ok", "server": SERVER_URL})
            return

        if path == "/api/scene":
            try:
                from . import SCENE_STATE

                self._send_json(dict(SCENE_STATE))
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/templates":
            try:
                from . import db_manager

                self._send_json({"status": "ok", "templates": db_manager.get_templates()})
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/suggest":
            prefix = (qs.get("prefix") or [""])[0].strip().upper()
            try:
                from . import db_manager

                self._send_json({"status": "ok", **db_manager.suggest_numbers(prefix)})
            except ValueError as e:
                self._send_json({"status": "error", "message": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/assets":
            category = (qs.get("category") or [None])[0]
            search = (qs.get("search") or [None])[0]
            try:
                from . import db_manager

                self._send_json(
                    {
                        "status": "ok",
                        "assets": db_manager.get_assets(category_filter=category, search_query=search),
                        "stats": db_manager.asset_stats(),
                    }
                )
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        self._send_json({"status": "error", "message": "Bilinmeyen yol: %s" % path}, 404)

    # ---- POST --------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        if path == "/api/templates":
            try:
                from . import db_manager

                res = db_manager.add_template(
                    body.get("category_code"),
                    body.get("category_name"),
                    body.get("schema"),
                )
                self._send_json({"status": "ok", "template": res})
            except ValueError as e:
                self._send_json({"status": "error", "message": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/select_object":
            name = str(body.get("object_name") or "").strip()
            if not name:
                self._send_json({"status": "error", "message": "object_name bos."}, 400)
                return
            try:
                res = dispatch_to_blender("select_object", {"object_name": name})
                self._send_json(res)
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/apply_code":
            try:
                full_code = str(body.get("full_code") or "").strip().upper()
                if not re.fullmatch(r"[A-Z0-9]{6}2\d{4}", full_code):
                    self._send_json(
                        {"status": "error", "message": "Gecersiz kod formati (11 hane olmali): %s" % full_code},
                        400,
                    )
                    return
                asset_uuid = str(body.get("uuid") or uuid.uuid4())
                payload = {
                    "full_code": full_code,
                    "uuid": asset_uuid,
                    "category": body.get("category"),
                    "p1": body.get("p1"),
                    "p2": body.get("p2"),
                    "p3": body.get("p3"),
                    "p4": body.get("p4"),
                    "model_no": body.get("model_no"),
                    "version_no": body.get("version_no"),
                    "labels": body.get("labels") or {},
                }
                res = dispatch_to_blender("apply_code", payload)
                self._send_json(res)
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        if path == "/api/run_module":
            module_name = str(body.get("module_name") or "").strip()
            params = body.get("params") or {}
            if not module_name:
                self._send_json({"status": "error", "message": "module_name bos."}, 400)
                return
            try:
                res = dispatch_to_blender("run_module", {"module_name": module_name, "params": params})
                self._send_json(res)
            except Exception as e:  # noqa: BLE001
                self._send_json({"status": "error", "message": str(e)}, 500)
            return

        self._send_json({"status": "error", "message": "Bilinmeyen yol: %s" % path}, 404)

    # ---- UI ------------------------------------------------------------
    def _serve_ui(self):
        index_path = os.path.join(UI_DIR, "index.html")
        if not os.path.isfile(index_path):
            self._send_json({"status": "error", "message": "ui/index.html bulunamadi"}, 404)
            return
        with open(index_path, "rb") as f:
            data = f.read()
        self._send(200, data, content_type="text/html; charset=utf-8")


# ---------------------------------------------------------------------
# Sunucu yasam dongusu
# ---------------------------------------------------------------------
def _port_in_use(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def start_server():
    """Sunucuyu arka planda başlatır (idempotent)."""
    global _server_instance, _server_thread
    if _server_instance is not None:
        return {"status": "running", "url": SERVER_URL}
    if _port_in_use(HOST, PORT):
        return {
            "status": "conflict",
            "url": SERVER_URL,
            "message": (
                "%s portunda baska bir sunucu calisiyor. Eski 'Model v2.5/MLAO' "
                "eklentinizi veya onceki Blender oturumunu kapatip yeniden deneyin." % PORT
            ),
        }
    try:
        _server_instance = ThreadingHTTPServer((HOST, PORT), PipelineHandler)
    except OSError as e:
        _server_instance = None
        return {"status": "error", "message": "Sunucu baslatilamadi: %s" % e}
    _server_instance.daemon_threads = True
    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()
    print("[ASSET-PIPELINE] HTTP sunucusu hazir: %s" % SERVER_URL)
    return {"status": "started", "url": SERVER_URL}


def stop_server():
    global _server_instance, _server_thread
    if _server_instance is None:
        return {"status": "stopped", "message": "Zaten durmustu."}
    srv, _server_instance = _server_instance, None
    _server_thread = None
    try:
        srv.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        srv.server_close()
    except Exception:  # noqa: BLE001
        pass
    print("[ASSET-PIPELINE] HTTP sunucusu durduruldu.")
    return {"status": "stopped"}


def server_running():
    return _server_instance is not None
