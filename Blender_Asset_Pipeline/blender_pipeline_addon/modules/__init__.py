# =====================================================================
# modules/__init__.py - Modul yonlendirici (Router)
# Sunucu/Blender timer'i run_module_by_name() uzerinden erisir.
# Faz 2/3'te yeni modul eklemek icin base_module.MODULS sozlugune
# girmek veya buraya import edip MODUL_REGISTRY'ye kaydetmek yeterlidir.
# =====================================================================

from .base_module import PipelineModule, MODULES as BASE_MODULES

MODUL_REGISTRY = dict(BASE_MODULES)


def list_modules():
    """Web arayuzunde buton olarak goruntulenebilecek modul listesi."""
    return [
        {"name": m.name, "label": m.label}
        for m in MODUL_REGISTRY.values()
    ]


def get_module(name):
    return MODUL_REGISTRY.get(str(name or "").strip())


def run_module_by_name(name, params=None):
    mod = get_module(name)
    if mod is None:
        return None
    try:
        return mod.run(params or {})
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": "Modul calisma hatasi (%s): %s" % (name, e)}
