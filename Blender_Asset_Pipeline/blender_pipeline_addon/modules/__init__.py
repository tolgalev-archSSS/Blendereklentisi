# ============================================================================
# modules/__init__.py
# Modül yönlendirici (Router): Faz 2/3 modüllerini isimle bulur ve çalıştırır.
# Bu modüldeki fonksiyonlar HİÇBİR ZAMAN doğrudan bpy'ye dokunmaz; yalnızca
# modül nesnelerini döndürür. bpy işlemleri addon'un EXECUTION_QUEUE'si içinde,
# Blender ana thread'inde gerçekleştirilir.
# ============================================================================

from .base_module import (
    PipelineModule,
    MeshRepairModule,
    DecimatePolyModule,
    BakeNormalModule,
    MODULE_REGISTRY,
)


def get_available_modules():
    """Web arayüzünde listelenecek modüllerin metadata listesi."""
    return [
        {
            "name": m.name,
            "display_name": m.display_name,
            "description": m.description,
        }
        for m in MODULE_REGISTRY
    ]


def get_module_by_name(module_name):
    """İsme göre modül örneği döner; bulunamazsa None."""
    for m in MODULE_REGISTRY:
        if m.name == module_name:
            return m
    return None


def register_external_module(module_instance):
    """
    Faz 2/3'te yeni bir modül yazıldığında burada sisteme dahil edilir.
    Örnek:
        from my_new_module import MyNewModule
        register_external_module(MyNewModule())
    """
    if not isinstance(module_instance, PipelineModule):
        raise TypeError("Kaydedilen nesne PipelineModule sınıfından türemelidir.")
    # Aynı isimde modül varsa üzerine yaz
    for i, m in enumerate(MODULE_REGISTRY):
        if m.name == module_instance.name:
            MODULE_REGISTRY[i] = module_instance
            return module_instance
    MODULE_REGISTRY.append(module_instance)
    return module_instance


__all__ = [
    "PipelineModule",
    "MeshRepairModule",
    "DecimatePolyModule",
    "BakeNormalModule",
    "MODULE_REGISTRY",
    "get_available_modules",
    "get_module_by_name",
    "register_external_module",
]
