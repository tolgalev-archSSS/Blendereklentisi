# ============================================================================
# base_module.py
# Faz 2 / Faz 3 genişleme altyapısı: PipelineModule temel sınıfı ve örnek
# kanca (hook) fonksiyonları (mesh_repair, decimate_poly, bake_normal).
# ============================================================================


class PipelineModule:
    """
    Tüm pipeline modüllerinin temel sınıfı.

    Kullanım (Faz 2'de kendi kodunuzu entegre ederken):
        class MyDecimate(PipelineModule):
            name = "decimate_poly"
            def run(self, obj, params):
                # bpy API çağrıları BURADA ana Blender thread'inde çalışır
                ...
                return self.success("İşlem tamam")

    ÖNEMLİ: run() metodu her zaman EXECUTION_QUEUE üzerinden Blender'ın ana
    thread'inde çağrılır. Asla arka plan thread'inden bpy.data üzerinde
    değişiklik yapmayın.
    """

    name = "base"
    display_name = "Temel Modül"
    description = "Diğer modüller için temel sınıf."

    def validate_object(self, obj):
        """Seçili objenin geçerli tek parça bir MESH olup olmadığını kontrol eder."""
        if obj is None:
            return False, "Blender'da seçili bir obje bulunamadı. Lütfen önce bir mesh seçin."
        if getattr(obj, "type", "") != "MESH":
            return False, f"'{obj.name}' bir mesh objesi değil (tip: {obj.type})."
        return True, "OK"

    def success(self, message, extra=None):
        payload = {"status": "success", "message": message}
        if extra:
            payload.update(extra)
        return payload

    def error(self, message):
        return {"status": "error", "message": message}

    def run(self, obj, params=None):
        """Alt sınıflar bu metodu override eder."""
        return self.error(f"'{self.name}' modülü henüz uygulanmadı.")


# ----------------------------------------------------------------------------
# Örnek kancalar (Faz 2 gerçek implementasyonlar buraya yazılacak)
# ----------------------------------------------------------------------------

FAZE2_MESSAGE = "Modül altyapısı hazır. Faz 2 kodu buraya entegre edilecek."


class MeshRepairModule(PipelineModule):
    name = "mesh_repair"
    display_name = "Açıkları Kapat (Repair)"
    description = "Manifold olmayan kenarları tespit edip kapatır (Faz 2)."

    def run(self, obj, params=None):
        ok, msg = self.validate_object(obj)
        if not ok:
            return self.error(msg)
        # TODO Faz 2: non-manifold edge cleanup / hole filling kodu
        print(f"[AssetPipeline][mesh_repair] Açık kapatma işlemi tetiklendi -> obje: {obj.name}")
        return self.success(FAZE2_MESSAGE, {"module": self.name, "object": obj.name})


class DecimatePolyModule(PipelineModule):
    name = "decimate_poly"
    display_name = "Poligon Düşür (Decimate)"
    description = "Decimate modifier ile poligon sayısını düşürür (Faz 2)."

    def run(self, obj, params=None):
        ok, msg = self.validate_object(obj)
        if not ok:
            return self.error(msg)
        ratio = (params or {}).get("ratio", 0.5)
        # TODO Faz 2: obj.modifiers.new(type='DECIMATE') implementasyonu
        print(f"[AssetPipeline][decimate_poly] Poligon düşürme tetiklendi -> obje: {obj.name}, oran: {ratio}")
        return self.success(FAZE2_MESSAGE, {"module": self.name, "object": obj.name})


class BakeNormalModule(PipelineModule):
    name = "bake_normal"
    display_name = "Normal Map Bake"
    description = "High-poly detayları normal map'e bakar (Faz 3)."

    def run(self, obj, params=None):
        ok, msg = self.validate_object(obj)
        if not ok:
            return self.error(msg)
        # TODO Faz 3: Cycles bake (NORMAL) operatör çağrıları
        print(f"[AssetPipeline][bake_normal] Normal map bake tetiklendi -> obje: {obj.name}")
        return self.success(FAZE2_MESSAGE, {"module": self.name, "object": obj.name})


# Kayıt listesi — modules/__init__.py bunu kullanır
MODULE_REGISTRY = [
    MeshRepairModule(),
    DecimatePolyModule(),
    BakeNormalModule(),
]
