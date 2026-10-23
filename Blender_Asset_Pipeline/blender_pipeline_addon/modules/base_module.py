# =====================================================================
# modules/base_module.py - Faz 2/3 genisleme tabani
# Poligon dusurme, delik kapatma (manifold repair), normal map bake gibi
# islemler bu sinifin alt siniflar olarak eklenmesiyle entegre olur.
#
# KURAL: run() yalnizca ana Blender thread'inden cagrilir (timer
# callback uzerinden). Dolayisiyla bpy API kullanimi burada GUVENLIDIR.
# =====================================================================

import bpy


class PipelineModule:
    """Tum pipeline modulleri icin temel sinif.

    Yeni modul eklemek icin:
      1. Bu dosyaya (veya modules/ altina yeni bir dosyaya) PipelineModule
         subclass'i yazin ya da create_module() ile fonksiyon kancasi tanimlayin.
      2. modules/__init__.py icindeki MODUL_REGISTRY'ye kaydedin.
    """

    name = "base"
    label = "Temel Modul"
    description = ""

    def get_selected_mesh(self):
        meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
        if len(meshes) != 1:
            return None, "Lutfen tam olarak tek bir Mesh objesi secin (simdi: %d)." % len(meshes)
        return meshes[0], None

    def run(self, params=None):
        params = params or {}
        obj, err = self.get_selected_mesh()
        if err:
            return {"status": "error", "message": err}
        # Varsayilan: hicbir sey yapma, altyapi hazir mesajini don
        print("[ASSET-PIPELINE] Modul tetiklendi: %s -> obje: %s" % (self.name, obj.name))
        return {
            "status": "success",
            "message": "Modul altyapisi hazir. Faz 2 kodu buraya entegre edilecek.",
            "module": self.name,
            "object": obj.name,
        }


def create_module(name, label, func):
    """Fonksiyon kancasindan hizlica PipelineModule instance uretir."""

    class _Hook(PipelineModule):
        pass

    _Hook.name = name
    _Hook.label = label
    inst = _Hook()
    inst.run = lambda params=None: func(inst, params or {})
    return inst


# ---------------------------------------------------------------------
# Hazir kancalar (Faz 2'de gercek implementasyonlarla degistirilecek)
# ---------------------------------------------------------------------
def mesh_repair(module, params):
    obj, err = module.get_selected_mesh()
    if err:
        return {"status": "error", "message": err}
    print("[ASSET-PIPELINE] mesh_repair tetiklendi -> %s" % obj.name)
    return {
        "status": "success",
        "message": "Modul altyapisi hazir. Faz 2 kodu buraya entegre edilecek. (mesh_repair)",
        "module": "mesh_repair",
        "object": obj.name,
    }


def decimate_poly(module, params):
    obj, err = module.get_selected_mesh()
    if err:
        return {"status": "error", "message": err}
    ratio = float(params.get("ratio", 0.5))
    print("[ASSET-PIPELINE] decimate_poly tetiklendi -> %s (ratio=%s)" % (obj.name, ratio))
    return {
        "status": "success",
        "message": "Modul altyapisi hazir. Faz 2 kodu buraya entegre edilecek. (decimate_poly)",
        "module": "decimate_poly",
        "object": obj.name,
    }


def bake_normal(module, params):
    obj, err = module.get_selected_mesh()
    if err:
        return {"status": "error", "message": err}
    print("[ASSET-PIPELINE] bake_normal tetiklendi -> %s" % obj.name)
    return {
        "status": "success",
        "message": "Modul altyapisi hazir. Faz 2 kodu buraya entegre edilecek. (bake_normal)",
        "module": "bake_normal",
        "object": obj.name,
    }


MODULES = {
    "mesh_repair": create_module("mesh_repair", "Aciklari Kapat (Repair)", mesh_repair),
    "decimate_poly": create_module("decimate_poly", "Poligon Dusur (Decimate)", decimate_poly),
    "bake_normal": create_module("bake_normal", "Normal Map Bake", bake_normal),
}
