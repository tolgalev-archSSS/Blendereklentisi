# ============================================================================
# server.py
# Gömülü HTTP REST API sunucusu — ThreadingHTTPServer ile arka planda çalışır.
#
# KRİTİK KURAL: Bu modül asla doğrudan bpy.context / bpy.data üzerinde işlem
# YAPMAZ. Blender'da değişiklik gerektiren tüm istekler EXECUTION_QUEUE'ye
# görev olarak atılır ve threading.Event ile sonucu beklenir (senkron yanıt).
# ============================================================================

import os
import sys
import json
import queue
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:
    # Eklenti paketi içinde çalışırken (Blender)
    from . import db_manager
except ImportError:
    # Bağımsız test / autostart senaryosu
    import db_manager

HOST = "127.0.0.1"
PORT = 8123
REQUEST_TIMEOUT = 10.0  # saniye — kuyruk görevinin tamamlanma bekleme limiti

_UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")

_server_instance = None
_server_thread = None


class Task:
    """
    EXECUTION_QUEUE üzerinden Blender ana thread'ine gönderilen görev.

    handler: callable() -> dict  (Blender ana thread'inde çalıştırılır)
    event  : threading.Event     (işlem tamamlandığında set edilir)
    result : dict                (handler'ın dönüş değeri)
    """

    def __init__(self, handler):
        self.handler = handler
        self.event = threading.Event()
        self.result = {"status": "error", "message": "Görev Blender tarafından işlenemedi."}

    def wait(self, timeout=REQUEST_TIMEOUT):
        finished = self.event.wait(timeout)
        if not finished:
            return {"status": "error", "message": "Zaman aşımı: Blender görevi 10 sn içinde tamamlamadı."}
        return self.result


def _get_queue():
    """
    Addon paketindeki EXECUTION_QUEUE'ye runtime'da erişir.
    Döngüsel import riski sys.modules üzerinden çözülür; bağımsız testte
    (addon hiç yüklenmemişse) None döner.
    """
    addon_mod = sys.modules.get("blender_pipeline_addon")
    if addon_mod is None:
        try:
            import blender_pipeline_addon as addon_mod  # noqa: F401
        except Exception:
            return None
    return getattr(addon_mod, "EXECUTION_QUEUE", None)


def _enqueue(handler):
    """Görevi kuyruğa atar ve sonucunu bekler. Sunucu thread'i için güvenli."""
    execution_queue = _get_queue()
    if execution_queue is None:
        return {"status": "error", "message": "Blender eklentisi yüklü değil veya görev kuyruğu erişilemiyor."}

    task = Task(handler)
    execution_queue.put(task)
    return task.wait()


class PipelineRequestHandler(BaseHTTPRequestHandler):
    server_version = "BlenderAssetPipeline/1.0"

    # ------------------------------------------------------------------ utils
    def log_message(self, fmt, *args):
        print(f"[AssetPipeline][HTTP] {self.address_string()} - {fmt % args}")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors()
        self.end_headers()
        self.wfile.write(body)

    def _add_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._add_cors()
        self.end_headers()

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        try:
            if route == "/":
                return self._serve_index()

            if route == "/api/scene":
                return self._handle_get_scene()

            if route == "/api/templates":
                return self._send_json({"status": "success", "templates": db_manager.get_templates()})

            if route == "/api/suggest":
                prefix = (qs.get("prefix") or [""])[0]
                return self._send_json({"status": "success", **db_manager.suggest_numbers(prefix)})

            if route == "/api/assets":
                category = (qs.get("category") or [None])[0]
                search = (qs.get("search") or [None])[0]
                return self._send_json({"status": "success", **db_manager.get_assets(category, search)})

            if route == "/api/modules":
                try:
                    from .modules import get_available_modules
                except ImportError:
                    from modules import get_available_modules
                return self._send_json({"status": "success", "modules": get_available_modules()})

            return self._send_json({"status": "error", "message": f"Bilinmeyen yol: {route}"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json({"status": "error", "message": str(exc)}, 500)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        body = self._read_body()

        try:
            if route == "/api/templates":
                result = db_manager.add_template(
                    body.get("category_code"),
                    body.get("category_name"),
                    body.get("schema") or {},
                )
                return self._send_json(result, 200 if result.get("status") == "success" else 400)

            if route == "/api/select_object":
                return self._handle_select_object(body)

            if route == "/api/apply_code":
                return self._handle_apply_code(body)

            if route == "/api/run_module":
                return self._handle_run_module(body)

            return self._send_json({"status": "error", "message": f"Bilinmeyen yol: {route}"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._send_json({"status": "error", "message": str(exc)}, 500)

    # -------------------------------------------------------------- handlers
    def _serve_index(self):
        index_path = os.path.join(_UI_DIR, "index.html")
        if not os.path.isfile(index_path):
            return self._send_json({"status": "error", "message": "ui/index.html bulunamadı."}, 404)
        with open(index_path, "r", encoding="utf-8") as fh:
            content = fh.read().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors()
        self.end_headers()
        self.wfile.write(content)

    def _handle_get_scene(self):
        """SCENE_STATE'i Blender ana thread'inden taze verilerle okur."""

        def job():
            addon_mod = sys.modules.get("blender_pipeline_addon")
            if addon_mod is None or not hasattr(addon_mod, "get_scene_state_snapshot"):
                # Addon yoksa (bağımsız test) boş durum döner
                return {"status": "success", "scene": {}}
            return {"status": "success", "scene": addon_mod.get_scene_state_snapshot()}

        result = _enqueue(job)
        return self._send_json(result)

    def _handle_select_object(self, body):
        object_name = str(body.get("object_name") or "").strip()
        if not object_name:
            return self._send_json({"status": "error", "message": "'object_name' alanı zorunludur."}, 400)

        def job():
            import bpy
            target = bpy.data.objects.get(object_name)
            if target is None:
                return {"status": "error", "message": f"'{object_name}' adında bir obje bulunamadı."}
            # Tüm seçimleri temizle, hedefi seç ve aktif yap
            for ob in bpy.context.view_layer.objects:
                ob.select_set(False)
            target.select_set(True)
            bpy.context.view_layer.objects.active = target
            return {
                "status": "success",
                "message": f"'{object_name}' Blender'da seçildi.",
                "object_name": target.name,
            }

        return self._send_json(_enqueue(job))

    def _handle_apply_code(self, body):
        required = ("full_code", "category", "p1", "p2", "p3", "p4", "model_no", "version_no")
        for key in required:
            if key not in body:
                return self._send_json({"status": "error", "message": f"Eksik alan: {key}"}, 400)

        full_code = str(body["full_code"]).strip().upper()
        if len(full_code) != 11:
            return self._send_json({"status": "error", "message": "Kod tam 11 karakter olmalıdır."}, 400)

        def job():
            import uuid as _uuid
            import bpy

            selected = list(bpy.context.selected_objects)
            active = bpy.context.view_layer.objects.active
            candidates = [o for o in selected if o.type == "MESH"]
            if active is not None and active.type == "MESH" and active not in candidates:
                candidates.append(active)

            if len(candidates) == 0:
                return {"status": "error", "message": "Seçili tek parça MESH obje bulunamadı."}
            if len(candidates) > 1:
                names = ", ".join(o.name for o in candidates)
                return {"status": "error", "message": f"Birden fazla mesh seçili ({names}). Lütfen tek bir mesh seçin."}

            obj = candidates[0]
            original_name = obj.name
            asset_uuid = str(body.get("asset_uuid") or "").strip() or str(_uuid.uuid4())

            # Custom property'de UUID zaten varsa onu koru (aynı objeye tekrar kayıt)
            existing_uuid = str(obj.get("asset_uuid") or "").strip()
            if existing_uuid:
                asset_uuid = existing_uuid

            # 1-4: İsimlendirme + custom property (ana thread'de)
            obj.name = full_code
            obj.data.name = full_code
            obj["asset_code"] = full_code
            obj["asset_uuid"] = asset_uuid

            record = {
                "uuid": asset_uuid,
                "full_code": full_code,
                "category": str(body["category"]).upper(),
                "p1": str(body["p1"]).upper(),
                "p2": str(body["p2"]).upper(),
                "p3": str(body["p3"]).upper(),
                "p4": str(body["p4"]).upper(),
                "model_no": int(body["model_no"]),
                "version_no": int(body["version_no"]),
                "original_name": original_name,
                "poly_count": len(obj.data.polygons),
                "vertex_count": len(obj.data.vertices),
                "blend_file_path": bpy.data.filepath or "",
            }

            # 5: Veritabanına kaydet
            db_result = db_manager.save_asset(record)
            return {**db_result, "record": record, "object_name": full_code}

        result = _enqueue(job)
        status = 200 if result.get("status") == "success" else 400
        return self._send_json(result, status)

    def _handle_run_module(self, body):
        module_name = str(body.get("module_name") or "").strip()
        params = body.get("params") or {}
        if not module_name:
            return self._send_json({"status": "error", "message": "'module_name' alanı zorunludur."}, 400)

        def job():
            import bpy
            try:
                from .modules import get_module_by_name
            except ImportError:
                from modules import get_module_by_name

            module = get_module_by_name(module_name)
            if module is None:
                return {"status": "error", "message": f"'{module_name}' adında bir modül kayıtlı değil."}

            active = bpy.context.view_layer.objects.active
            selected_meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
            target = active if (active is not None and active.type == "MESH") else (
                selected_meshes[0] if len(selected_meshes) == 1 else None
            )
            return module.run(target, params)

        result = _enqueue(job)
        status = 200 if result.get("status") == "success" else 400
        return self._send_json(result, status)


# ---------------------------------------------------------------------- kontrol
def start_server(host=HOST, port=PORT):
    """Sunucuyu arka plan thread'inde başlatır. Zaten açıksa tekrar açmaz."""
    global _server_instance, _server_thread
    if _server_instance is not None:
        return {"status": "success", "message": f"Sunucu zaten çalışıyor: http://{HOST}:{PORT}"}
    try:
        _server_instance = ThreadingHTTPServer((host, port), PipelineRequestHandler)
    except OSError as exc:
        _server_instance = None
        return {"status": "error", "message": f"Port açılamadı ({host}:{port}): {exc}"}

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True, name="AssetPipelineHTTP")
    _server_thread.start()
    return {"status": "success", "message": f"REST API sunucusu başladı: http://{host}:{port}"}


def stop_server():
    """Sunucuyu durdurur."""
    global _server_instance, _server_thread
    if _server_instance is None:
        return {"status": "success", "message": "Zaten durmuş olan bir sunucu yok."}
    _server_instance.shutdown()
    _server_instance.server_close()
    _server_instance = None
    _server_thread = None
    return {"status": "success", "message": "Sunucu durduruldu."}


def is_running():
    return _server_instance is not None


if __name__ == "__main__":
    # Bağımsız smoke-test (Blender olmadan): sadece DB uçları çalışır,
    # Blender gerektiren uçlar hata mesajı döner.
    db_manager.init_db()
    print("Test sunucusu http://%s:%d üzerinde başlatılıyor (Ctrl+C ile durdurun)" % (HOST, PORT))
    srv = ThreadingHTTPServer((HOST, PORT), PipelineRequestHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.server_close()
