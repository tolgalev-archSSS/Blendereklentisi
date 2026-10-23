# =====================================================================
# __init__.py - Blender Asset Pipeline Eklentisi (Faz 1)
#
# Mimari:
#   - HTTP sunucusu (server.py) ayri thread'te calisir, bpy'ye DOKUNMAZ.
#   - Sunucu ihtiyac oldugunda EXECUTION_QUEUE'ye gorev koyar.
#   - Ana Blender thread'inde calisan persistent timer (0.1 sn) bu
#     kuyrugu bosaltir, sonuclari task["result"] icine yazar ve
#     task["event"].set() ile HTTP thread'ini uyandirir.
#   - Ayni timer SCENE_STATE'i (sahne ozeti) sürekli taze tutar;
#     web arayuzu sadece bu sozlugu okur.
#
# ONEMLI: Bu eklentide HICBIR FBX/OBJ export islemi YOKTUR. Eskiden
# gorunen "[MLAO]" loglari "Model v2.5" adli BASKA bir eklentiden
# geliyordu. Port cakismasini onlemek icin baslangicta 8123 portunu
# kontrol eder ve cakisma varsa net uyari verir.
# =====================================================================

import re
import uuid
import queue
import sqlite3
import threading

import bpy

from . import db_manager
from . import server
from .modules import get_module

bl_info = {
    "name": "Asset Pipeline (Faz 1)",
    "author": "Asset Pipeline Team",
    "description": "11 haneli kodlama ile secili mesh objeleri isimlendirir, SQLite'e kaydeder. Localhost web paneli (port 8123). Export yapmaz.",
    "author_note": "",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View 3D > N Paneli > Asset Pipeline",
    "warning": "",
    "doc_url": "",
    "category": "3D View",
}

# ---------------------------------------------------------------------
# Global thread-safe yapi lar
# ---------------------------------------------------------------------
EXECUTION_QUEUE = queue.Queue()
SCENE_STATE = {
    "connected": True,
    "addon": "Asset Pipeline Faz 1",
    "blend_file": "",
    "active_object": None,
    "mesh_objects": [],
    "last_error": None,
}

_timer_installed = False


# ---------------------------------------------------------------------
# Gorev isleyicileri (YALNIZCA ana Blender thread'inde calisir)
# ---------------------------------------------------------------------
def _get_selected_mesh(context):
    """Secili TEK mesh objesini donerür; kosul saglanmiyorsa (None, hata)."""
    meshes = [o for o in context.selected_objects if o.type == "MESH"]
    if len(meshes) != 1:
        return None, ("Lutfen tam olarak tek bir Mesh objesi secin. Simdiki secim: %d mesh." % len(meshes))
    return meshes[0], None


def _task_select_object(payload):
    name = payload.get("object_name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        return {"status": "error", "message": "Obje bulunamadi: %s" % name}
    try:
        context = bpy.context
        for o in list(context.selected_objects):
            o.select_set(False)
        obj.hide_viewport = False
        obj.hide_set(False)
        # view_layer.objects.active atamasi Blender'in bekledigi RNA ref
        # karsilastirmasi yapar; bu yuzden dogrudan (try/except ile) denenir,
        # basarisiz olursa secim yine de gecerli sayilir.
        try:
            context.view_layer.objects.active = obj
        except Exception:  # noqa: BLE001
            pass
        obj.select_set(True)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": "Secim hatasi: %s" % e}
    return {"status": "ok", "selected": obj.name}


def _task_apply_code(payload):
    """11 haneli kodu secili tek mesh objeye uygular + DB kaydi."""
    full_code = str(payload.get("full_code") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6}2\d{4}", full_code):
        return {"status": "error", "message": "Gecersiz kod formati: %s" % full_code}

    obj, err = _get_selected_mesh(bpy.context)
    if err:
        return {"status": "error", "message": err}

    original_name = obj.name
    asset_uuid = str(payload.get("uuid") or obj.get("asset_uuid") or uuid.uuid4())

    obj.name = full_code
    obj.data.name = full_code
    obj["asset_code"] = full_code
    obj["asset_uuid"] = asset_uuid

    record = {
        "uuid": asset_uuid,
        "full_code": full_code,
        "category": payload.get("category") or full_code[:2],
        "p1": payload.get("p1") or full_code[2],
        "p2": payload.get("p2") or full_code[3],
        "p3": payload.get("p3") or full_code[4],
        "p4": payload.get("p4") or full_code[5],
        "model_no": int(payload.get("model_no") or int(full_code[7:9])),
        "version_no": int(payload.get("version_no") or int(full_code[9:11])),
        "original_name": original_name,
        "poly_count": len(obj.data.polygons),
        "vertex_count": len(obj.data.vertices),
        "blend_file_path": bpy.data.filepath or "",
    }
    try:
        db_res = db_manager.save_asset(record)
    except sqlite3.IntegrityError as e:
        # Ayni full_code baska bir uuid ile kayitliysa (ornegin obje kopyalandi)
        # yeni uuid uretip kaydi ayri bir asset olarak dene.
        if "full_code" not in str(e).lower() and "unique" not in str(e).lower():
            return {"status": "error", "message": "Veritabani hatasi: %s" % e}
        record["uuid"] = str(uuid.uuid4())
        try:
            db_res = db_manager.save_asset(record)
            obj["asset_uuid"] = record["uuid"]
        except Exception as e2:  # noqa: BLE001
            return {"status": "error", "message": "Veritabani reddetti: %s" % e2}
    except ValueError as e:
        return {"status": "error", "message": "Veritabani reddetti: %s" % e}

    print("[ASSET-PIPELINE] Isimlendirildi: %s -> %s (%d poly)" % (original_name, full_code, record["poly_count"]))
    return {"status": "ok", "message": "Isim degistirildi ve veritabanina kaydedildi.", "asset": record, "db": db_res}


def _task_run_module(payload):
    from .modules import run_module_by_name

    name = payload.get("module_name")
    params = payload.get("params") or {}
    result = run_module_by_name(name, params)
    if result is None:
        return {"status": "error", "message": "Modül bulunamadi: %s" % name}
    return result


TASK_HANDLERS = {
    "select_object": _task_select_object,
    "apply_code": _task_apply_code,
    "run_module": _task_run_module,
}


# ---------------------------------------------------------------------
# Sahne durumu (read-only bpy erisimi - ana thread'de guvenli)
# ---------------------------------------------------------------------
def _refresh_scene_state():
    try:
        objects = []
        active_name = None
        try:
            active = bpy.context.view_layer.objects.active
            active_name = active.name if active else None
        except Exception:  # noqa: BLE001
            active = None
            active_name = None

        selected_names = set(o.name for o in bpy.context.selected_objects) if hasattr(bpy.context, "selected_objects") else set()

        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            entry = {
                "name": obj.name,
                "poly_count": len(obj.data.polygons),
                "vertex_count": len(obj.data.vertices),
                "selected": obj.name in selected_names,
                "active": obj.name == active_name,
                "asset_code": str(obj.get("asset_code") or ""),
                "asset_uuid": str(obj.get("asset_uuid") or ""),
            }
            objects.append(entry)

        SCENE_STATE["connected"] = True
        SCENE_STATE["blend_file"] = bpy.data.filepath or "(kaydedilmemis)"
        SCENE_STATE["active_object"] = active_name
        SCENE_STATE["mesh_objects"] = objects
        SCENE_STATE["last_error"] = None
    except Exception as e:  # noqa: BLE001
        SCENE_STATE["last_error"] = str(e)


# ---------------------------------------------------------------------
# Persistent timer: kuyruk + sahne durumu
# ---------------------------------------------------------------------
def timer_callback():
    # 1) Bekleyen görevleri güvenli sekilde yürüt
    while True:
        try:
            task = EXECUTION_QUEUE.get_nowait()
        except queue.Empty:
            break
        handler = TASK_HANDLERS.get(task.get("action"))
        try:
            if handler is None:
                task["result"] = {"status": "error", "message": "Bilinmeyen gorev: %s" % task.get("action")}
            else:
                task["result"] = handler(task.get("payload") or {})
        except Exception as e:  # noqa: BLE001
            task["result"] = {"status": "error", "message": "Gorev hatasi: %s" % e}
        finally:
            ev = task.get("event")
            if isinstance(ev, threading.Event):
                ev.set()

    # 2) Sahne durumunu tazele
    _refresh_scene_state()

    return 0.1  # tekrar çağırılma aralığı (sn)


# ---------------------------------------------------------------------
# Operatorlar
# ---------------------------------------------------------------------
class PIPELINE_OT_start_server(bpy.types.Operator):
    bl_idname = "pipeline.start_server"
    bl_label = "Sunucuyu Baslat / Durdur"
    bl_description = "Localhost:8123 uzerindeki gomulu HTTP sunucusunu acar/kapatir"

    def execute(self, context):
        if server.server_running():
            server.stop_server()
            self.report({"INFO"}, "HTTP sunucusu durduruldu.")
        else:
            res = server.start_server()
            if res.get("status") in ("started", "running"):
                self.report({"INFO"}, "HTTP sunucusu calisiyor: %s" % res.get("url"))
            else:
                self.report({"ERROR"}, res.get("message", "Sunucu baslatilamadi"))
        return {"FINISHED"}


class PIPELINE_OT_open_web(bpy.types.Operator):
    bl_idname = "pipeline.open_web"
    bl_label = "Web Arayuzunu Ac"
    bl_description = "http://127.0.0.1:8123 adresini tarayicida acar"

    def execute(self, context):
        import webbrowser

        if not server.server_running():
            server.start_server()
        webbrowser.open(server.SERVER_URL)
        return {"FINISHED"}


# ---------------------------------------------------------------------
# N Paneli UI
# ---------------------------------------------------------------------
class PIPELINE_PT_main(bpy.types.Panel):
    bl_label = "Asset Pipeline"
    bl_idname = "PIPELINE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Asset Pipeline"

    def draw(self, context):
        layout = self.layout
        running = server.server_running()

        row = layout.row()
        col = row.column()
        icon = "PROP_ON" if running else "CANCELLED"
        col.label(text="Sunucu: %s" % ("CALISIYOR (:%d)" % server.PORT if running else "KAPALI"), icon=icon)
        col.label(text="Adres: %s" % server.SERVER_URL)

        layout.operator(PIPELINE_OT_start_server.bl_idname, text=("Sunucuyu Durdur" if running else "Sunucuyu Baslat"), icon="PLAY" if not running else "PAUSE")
        layout.operator(PIPELINE_OT_open_web.bl_idname, text="Web Arayuzunu Ac", icon="URL")

        box = layout.box()
        box.label(text="Sahne Ozeti:", icon="OUTLINER_DATA_MESH")
        box.label(text="Mesh Obje: %d" % len(SCENE_STATE.get("mesh_objects", [])))
        act = SCENE_STATE.get("active_object")
        box.label(text="Aktif: %s" % (act if act else "-"))
        blend = SCENE_STATE.get("blend_file") or "-"
        box.label(text="Dosya: %s" % blend.replace("\\", "/").rsplit("/", 1)[-1])


CLASSES = (
    PIPELINE_OT_start_server,
    PIPELINE_OT_open_web,
    PIPELINE_PT_main,
)


# ---------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------
def register():
    global _timer_installed
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    db_manager.init_db()

    res = server.start_server()
    if res.get("status") == "conflict":
        print("[ASSET-PIPELINE] UYARI: %s" % res.get("message"))
    elif res.get("status") == "error":
        print("[ASSET-PIPELINE] UYARI: %s" % res.get("message"))

    if not _timer_installed:
        try:
            bpy.app.timers.unregister(timer_callback)
        except (ValueError, RuntimeError):
            pass
        bpy.app.timers.register(timer_callback, first_interval=0.5, persistent=True)
        _timer_installed = True


def unregister():
    global _timer_installed
    if _timer_installed:
        try:
            bpy.app.timers.unregister(timer_callback)
        except (ValueError, RuntimeError):
            pass
        _timer_installed = False

    server.stop_server()

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
