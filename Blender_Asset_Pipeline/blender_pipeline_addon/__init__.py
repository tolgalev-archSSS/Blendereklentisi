# ============================================================================
# blender_pipeline_addon/__init__.py
# Blender Addon kaydı (bl_info), N-Panel "Asset Pipeline" sekmesi ve
# Timer / Queue yöneticisi.
#
# MİMARİ: HTTP sunucusu ayrı thread'lerde çalışır; bpy çağrıları içeren tüm
# görevler EXECUTION_QUEUE üzerinden 0.1 sn'de bir çalışan timer ile Blender'ın
# ANA THREAD'İNDE yürütülür. Böylece thread-safety ihlali olmaz.
# ============================================================================

import queue
import threading

import bpy

bl_info = {
    "name": "Asset Pipeline - 11 Haneli Kodlama Sistemi",
    "author": "Kıdemli Geliştirici (Faz 1)",
    "description": "Seçili objeleri 11 karakterlik özel koda göre isimlendirir, "
                   "SQLite veritabanına kaydeder ve localhost REST API + web arayüzü sunar.",
    "blender": (3, 0, 0),
    "version": (1, 0, 0),
    "location": "View 3D > Sidebar (N) > Asset Pipeline",
    "warning": "",
    "doc_url": "",
    "category": "3D View",
}

try:
    from . import server, db_manager
except ImportError:  # pragma: no cover - doğrudan script olarak çalıştırılırsa
    import server
    import db_manager

# ----------------------------------------------------------------------------
# Global durum / kuyruk
# ----------------------------------------------------------------------------
EXECUTION_QUEUE = queue.Queue()
SCENE_STATE = {}
QUEUE_AVAILABLE = True  # server.py bu bayrağı kontrol eder

_TIMER_ENABLED = False


def _safe_str(value):
    """IDPropertyArray / UUID gibi değerleri JSON'a uygun metne çevirir."""
    try:
        return str(value)
    except Exception:
        return ""


def get_scene_state_snapshot():
    """
    SCENE_STATE sözlüğünün bir kopyasını döner. Sunucu thread'i tarafından
    yalnızca okuma amaçlı kullanılır; yazmalar daima ana thread'de olur.
    """
    snapshot = dict(SCENE_STATE)
    return snapshot


# ----------------------------------------------------------------------------
# Ana döngü (Blender main thread) — her 0.1 saniyede çalışır
# ----------------------------------------------------------------------------
def timer_callback():
    global _TIMER_ENABLED
    if not _TIMER_ENABLED:
        return None  # timer'ı durdur

    # 1) Kuyruktaki görevleri işle (obje seçme, isim değiştirme, modül vb.)
    processed = 0
    while not EXECUTION_QUEUE.empty() and processed < 50:
        processed += 1
        try:
            task = EXECUTION_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            task.result = task.handler()
        except Exception as exc:  # görev hata fırlatsa da event set edilmeli
            task.result = {"status": "error", "message": f"Blender görev hatası: {exc}"}
        finally:
            task.event.set()

    # 2) Sahne durumunu güncelle (salt okunur toplama)
    try:
        refresh_scene_state()
    except Exception as exc:
        print(f"[AssetPipeline] Sahne durumu okunamadı: {exc}")

    return 0.1  # sonraki çağrı aralığı (saniye)


def refresh_scene_state():
    """Sahnedeki mesh objelerini ve aktif seçimi SCENE_STATE'e yazar."""
    meshes = []
    active_name = None
    try:
        active_obj = bpy.context.view_layer.objects.active
    except Exception:
        active_obj = None

    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        entry = {
            "name": obj.name,
            "is_selected": bool(obj.select_get()),
            "is_active": active_obj is not None and obj.name == active_obj.name,
            "poly_count": len(obj.data.polygons),
            "vertex_count": len(obj.data.vertices),
            "asset_code": _safe_str(obj.get("asset_code")) or None,
            "asset_uuid": _safe_str(obj.get("asset_uuid")) or None,
        }
        meshes.append(entry)
        if entry["is_active"]:
            active_name = obj.name

    SCENE_STATE.update(
        {
            "blend_file_path": bpy.data.filepath or "",
            "blend_file_name": (bpy.path.basename(bpy.data.filepath) if bpy.data.filepath else "(kaydedilmemiş)"),
            "mesh_objects": meshes,
            "active_object": active_name,
            "server_running": server.is_running(),
            "timestamp": __import__("time").time(),
        }
    )


# ----------------------------------------------------------------------------
# Başlat / Durdur yardımcıları
# ----------------------------------------------------------------------------
def start_pipeline(_context=None):
    """Veritabanını hazırlar, sunucuyu başlatır, timer'ı kaydeder."""
    global _TIMER_ENABLED
    db_manager.init_db()

    result = server.start_server()
    if result.get("status") != "success":
        print(f"[AssetPipeline] {result.get('message')}")
        return result

    if not _TIMER_ENABLED:
        bpy.app.timers.register(timer_callback, first_interval=0.1, persistent=True)
        _TIMER_ENABLED = True

    print(f"[AssetPipeline] {result.get('message')}")
    return result


def stop_pipeline(_context=None):
    """Sunucuyu ve timer'ı durdurur."""
    global _TIMER_ENABLED
    result = server.stop_server()
    if _TIMER_ENABLED:
        try:
            bpy.app.timers.unregister(timer_callback)
        except Exception:
            pass
        _TIMER_ENABLED = False
    print(f"[AssetPipeline] {result.get('message')}")
    return result


# ----------------------------------------------------------------------------
# Operatörler
# ----------------------------------------------------------------------------
class PIPELINE_OT_toggle_server(bpy.types.Operator):
    """Gömülü REST API sunucusunu başlatır veya durdurur"""

    bl_idname = "pipeline.toggle_server"
    bl_label = "Sunucuyu Başlat / Durdur"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if server.is_running():
            stop_pipeline(context)
            self.report({"INFO"}, "Sunucu durduruldu.")
        else:
            result = start_pipeline(context)
            if result.get("status") == "success":
                self.report({"INFO"}, result.get("message", "Sunucu çalışıyor."))
            else:
                self.report({"ERROR"}, result.get("message", "Sunucu başlatılamadı."))
        return {"FINISHED"}


class PIPELINE_OT_open_webui(bpy.types.Operator):
    """Varsayılan tarayıcıda web arayüzünü açar"""

    bl_idname = "pipeline.open_webui"
    bl_label = "Web Arayüzünü Aç"

    def execute(self, context):
        if not server.is_running():
            start_pipeline(context)
        import webbrowser

        webbrowser.open("http://127.0.0.1:8123")
        self.report({"INFO"}, "http://127.0.0.1:8123 adresi tarayıcıda açıldı.")
        return {"FINISHED"}


# ----------------------------------------------------------------------------
# N-Panel UI
# ----------------------------------------------------------------------------
class PIPELINE_PT_asset_pipeline(bpy.types.Panel):
    """View3D sidebar (N paneli) içindeki 'Asset Pipeline' sekmesi."""

    bl_label = "Asset Pipeline"
    bl_idname = "PIPELINE_PT_asset_pipeline"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Asset Pipeline"

    def draw(self, context):
        layout = self.layout
        running = server.is_running()

        # Sunucu durumu etiketi
        status_row = layout.row()
        icon = "CANCEL" if not running else "CHECKMARK"
        status_row.label(text=f"Sunucu Durumu: {'ÇALIŞIYOR' if running else 'DURMUŞ'}", icon=icon)
        box = layout.box()
        box.label(text=f"http://127.0.0.1:{server.PORT}", icon="URL")
        if running:
            box.label(text=f"Sahnede {len(SCENE_STATE.get('mesh_objects', []))} mesh obje izleniyor")

        layout.separator()
        layout.operator(PIPELINE_OT_toggle_server.bl_idname,
                        text="Sunucuyu Durdur" if running else "Sunucuyu Başlat",
                        icon="PLAY" if not running else "PAUSE")
        layout.operator(PIPELINE_OT_open_webui.bl_idname, text="Web Arayüzünü Aç", icon="WINDOW")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Aktif Obje:", icon="OUTLINER_DATA_MESH")
        active = SCENE_STATE.get("active_object") or "(seçim yok)"
        col.label(text=active)


# ----------------------------------------------------------------------------
# Kayıt (register / unregister)
# ----------------------------------------------------------------------------
classes = (
    PIPELINE_OT_toggle_server,
    PIPELINE_OT_open_webui,
    PIPELINE_PT_asset_pipeline,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    print("[AssetPipeline] Eklenti kaydedildi. N paneli -> 'Asset Pipeline' sekmesi hazır.")


def unregister():
    stop_pipeline()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("[AssetPipeline] Eklenti kaldırıldı.")


if __name__ == "__main__":
    register()
