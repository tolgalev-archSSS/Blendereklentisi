# ============================================================================
# db_manager.py
# SQLite veritabanı katmanı ve 11 haneli akıllı numaralandırma motoru.
# Harici paket gerektirmez (yalnızca standart kütüphane: sqlite3, json, os).
# ============================================================================

import os
import re
import json
import sqlite3
import threading

# --- Dinamik yol çözümü -----------------------------------------------------
# Bu dosya: <PROJE_KOKU>/blender_pipeline_addon/db_manager.py
# Veritabanı: <PROJE_KOKU>/database/assets.db
_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_ADDON_DIR)
DB_DIR = os.path.join(_PROJECT_ROOT, "database")
DB_PATH = os.path.join(DB_DIR, "assets.db")

_db_lock = threading.Lock()


def _get_connection():
    """Her çağrıda yeni bir bağlantı döner (thread-safe kullanım için)."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


# --- Varsayılan şablonlar (seed) ---------------------------------------------
AY_TEMPLATE_SCHEMA = {
    "P1": {
        "group_name": "Kitle",
        "options": {
            "K": "Kadın",
            "G": "Kız Çocuk",
            "E": "Erkek",
            "C": "Erkek Çocuk",
            "U": "Unisex",
        },
    },
    "P2": {
        "group_name": "Tür",
        "options": {
            "S": "Spor",
            "B": "Bot",
            "C": "Çizme",
            "A": "Sandalet",
            "R": "Terlik",
            "O": "Oxford",
            "T": "Topuklu",
            "F": "Babet/Flat",
            "M": "Mary Jane",
        },
    },
    "P3": {
        "group_name": "Topuk Yüksekliği",
        "options": {
            "D": "Düz/Topuksuz",
            "A": "Alçak",
            "Y": "Yüksek",
            "P": "Platform",
        },
    },
    "P4": {
        "group_name": "Topuk Tipi",
        "options": {
            "K": "Kalın",
            "I": "İnce",
            "D": "Diğer/Yok",
        },
    },
}

HY_TEMPLATE_SCHEMA = {
    "P1": {
        "group_name": "Yaş Grubu",
        "options": {
            "E": "Yetişkin",
            "Y": "Yavru/Juvenile",
        },
    },
    "P2": {
        "group_name": "Tür",
        "options": {
            "K": "Kedi",
            "I": "Köpek",
            "A": "At",
            "B": "Kuş",
            "S": "Sürüngen",
            "M": "Memeli (Diğer)",
        },
    },
    "P3": {
        "group_name": "Detay Seviyesi",
        "options": {
            "L": "Low Poly",
            "M": "Mid Poly",
            "H": "High Poly",
        },
    },
    "P4": {
        "group_name": "Poza",
        "options": {
            "S": "Statik/Duruyor",
            "R": "Rekor/Oturuyor",
            "Y": "Yatıyor",
            "W": "Yürüme Animasyonu",
        },
    },
}


def init_db():
    """Tabloları oluşturur; templates tablosu boşsa AY ve HY şablonlarını tohumlar."""
    with _db_lock:
        conn = _get_connection()
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_code TEXT UNIQUE NOT NULL,
                category_name TEXT NOT NULL,
                schema_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT UNIQUE NOT NULL,
                full_code TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                p1 TEXT NOT NULL,
                p2 TEXT NOT NULL,
                p3 TEXT NOT NULL,
                p4 TEXT NOT NULL,
                model_no INTEGER NOT NULL,
                version_no INTEGER NOT NULL,
                original_name TEXT,
                poly_count INTEGER,
                vertex_count INTEGER,
                blend_file_path TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("SELECT COUNT(*) AS c FROM templates")
        if cur.fetchone()["c"] == 0:
            cur.execute(
                "INSERT OR IGNORE INTO templates (category_code, category_name, schema_json) VALUES (?, ?, ?)",
                ("AY", "Ayakkabı", json.dumps(AY_TEMPLATE_SCHEMA, ensure_ascii=False)),
            )
            cur.execute(
                "INSERT OR IGNORE INTO templates (category_code, category_name, schema_json) VALUES (?, ?, ?)",
                ("HY", "Hayvan", json.dumps(HY_TEMPLATE_SCHEMA, ensure_ascii=False)),
            )
        conn.commit()
        conn.close()


def get_templates():
    """Tüm şablonları JSON parse edilmiş olarak döner."""
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM templates ORDER BY category_code")
    result = []
    for row in cur.fetchall():
        try:
            schema = json.loads(row["schema_json"])
        except (json.JSONDecodeError, TypeError):
            schema = {}
        result.append(
            {
                "id": row["id"],
                "category_code": row["category_code"],
                "category_name": row["category_name"],
                "schema": schema,
            }
        )
    conn.close()
    return result


def add_template(category_code, category_name, schema_dict):
    """Yeni kategori şablonu ekler/günceller. Dönüş: {'status', 'message'}"""
    code = str(category_code or "").strip().upper()
    name = str(category_name or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{2}", code):
        return {"status": "error", "message": "Kategori kodu tam 2 haneli olmalıdır (örn: AY, HY)."}
    if not name:
        return {"status": "error", "message": "Kategori adı boş olamaz."}
    if not isinstance(schema_dict, dict):
        return {"status": "error", "message": "Şema yapısı geçersiz (JSON object olmalı)."}
    # Şemayı normalize et: P1..P4 grup isimleri + options
    normalized = {}
    for key in ("P1", "P2", "P3", "P4"):
        grp = schema_dict.get(key) or {}
        options = grp.get("options") or {}
        clean_opts = {}
        for k, v in options.items():
            k = str(k).strip().upper()
            if len(k) == 1 and k.isalnum():
                clean_opts[k] = str(v)
        normalized[key] = {
            "group_name": str(grp.get("group_name") or key),
            "options": clean_opts,
        }
    with _db_lock:
        conn = _get_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO templates (category_code, category_name, schema_json)
                VALUES (?, ?, ?)
                ON CONFLICT(category_code) DO UPDATE SET
                    category_name = excluded.category_name,
                    schema_json = excluded.schema_json
                """,
                (code, name, json.dumps(normalized, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
    return {"status": "success", "message": f"'{code} - {name}' şablonu kaydedildi.", "template": {"category_code": code, "category_name": name, "schema": normalized}}


def suggest_numbers(prefix):
    """
    prefix: örn. 'AYKBYK' (kategori + P1..P4 = 6 karakter).
    Dönüş sözlüğü:
      next_new_model : yeni model için önerilen MM (int)
      next_version   : yeni model için önerilen VV (int, daima 1)
      existing_models: [{"model_no": int, "latest_version": int, "next_version": int}, ...]
    """
    prefix = str(prefix or "").strip().upper()
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT model_no, version_no FROM assets
        WHERE substr(full_code, 1, ?) = ?
        """,
        (len(prefix), prefix),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return {
            "prefix": prefix,
            "next_new_model": 1,
            "next_version": 1,
            "existing_models": [],
        }

    per_model = {}
    for r in rows:
        m = int(r["model_no"])
        v = int(r["version_no"])
        if m not in per_model or v > per_model[m]:
            per_model[m] = v

    max_model = max(per_model.keys())
    existing_models = [
        {
            "model_no": m,
            "latest_version": per_model[m],
            "next_version": min(per_model[m] + 1, 99),
        }
        for m in sorted(per_model.keys())
    ]
    return {
        "prefix": prefix,
        "next_new_model": min(max_model + 1, 99),
        "next_version": 1,
        "existing_models": existing_models,
    }


def save_asset(data_dict):
    """
    İsimlendirilen modeli kaydeder; aynı uuid veya full_code varsa günceller (upsert).
    Beklenen anahtarlar: uuid, full_code, category, p1, p2, p3, p4,
                         model_no, version_no, original_name,
                         poly_count, vertex_count, blend_file_path
    """
    required = ("uuid", "full_code", "category", "p1", "p2", "p3", "p4", "model_no", "version_no")
    for key in required:
        if key not in data_dict:
            return {"status": "error", "message": f"Eksik alan: {key}"}

    with _db_lock:
        conn = _get_connection()
        cur = conn.cursor()
        try:
            # uuid varsa -> onun satırını bul; full_code başka bir satırda ise çakışmayı bildir
            cur.execute("SELECT id, full_code FROM assets WHERE uuid = ?", (data_dict["uuid"],))
            by_uuid = cur.fetchone()
            cur.execute("SELECT id, uuid FROM assets WHERE full_code = ?", (data_dict["full_code"],))
            by_code = cur.fetchone()

            if by_uuid:
                if by_code and by_code["id"] != by_uuid["id"]:
                    return {
                        "status": "error",
                        "message": f"'{data_dict['full_code']}' kodu başka bir varlığa ait. Lütfen farklı bir model/versiyon numarası seçin.",
                    }
                cur.execute(
                    """
                    UPDATE assets SET
                        full_code=?, category=?, p1=?, p2=?, p3=?, p4=?,
                        model_no=?, version_no=?, original_name=?,
                        poly_count=?, vertex_count=?, blend_file_path=?
                    WHERE id=?
                    """,
                    (
                        data_dict["full_code"], data_dict["category"],
                        data_dict["p1"], data_dict["p2"], data_dict["p3"], data_dict["p4"],
                        int(data_dict["model_no"]), int(data_dict["version_no"]),
                        data_dict.get("original_name"),
                        int(data_dict.get("poly_count") or 0),
                        int(data_dict.get("vertex_count") or 0),
                        data_dict.get("blend_file_path"),
                        by_uuid["id"],
                    ),
                )
                asset_id = by_uuid["id"]
                action = "updated"
            elif by_code:
                return {
                    "status": "error",
                    "message": f"'{data_dict['full_code']}' kodu zaten kayıtlı. Versiyon eklemek için mevcut modele versiyon seçin.",
                }
            else:
                cur.execute(
                    """
                    INSERT INTO assets
                        (uuid, full_code, category, p1, p2, p3, p4, model_no, version_no,
                         original_name, poly_count, vertex_count, blend_file_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data_dict["uuid"], data_dict["full_code"], data_dict["category"],
                        data_dict["p1"], data_dict["p2"], data_dict["p3"], data_dict["p4"],
                        int(data_dict["model_no"]), int(data_dict["version_no"]),
                        data_dict.get("original_name"),
                        int(data_dict.get("poly_count") or 0),
                        int(data_dict.get("vertex_count") or 0),
                        data_dict.get("blend_file_path"),
                    ),
                )
                asset_id = cur.lastrowid
                action = "created"
            conn.commit()
        finally:
            conn.close()

    return {"status": "success", "action": action, "asset_id": asset_id, "record": get_asset_by_id(asset_id)}


def get_asset_by_id(asset_id):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_assets(category_filter=None, search_query=None):
    """Kayıtlı tüm modelleri filtreleyerek döner."""
    sql = "SELECT * FROM assets WHERE 1=1"
    params = []
    if category_filter:
        sql += " AND category = ?"
        params.append(str(category_filter).strip().upper())
    if search_query:
        q = f"%{str(search_query).strip()}%"
        sql += " AND (full_code LIKE ? OR original_name LIKE ?)"
        params.extend([q, q])
    sql += " ORDER BY created_at DESC, id DESC"

    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    total = len(get_assets_all_count())
    conn.close()
    return {"assets": rows, "total": total}


def get_assets_all_count():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM assets")
    rows = cur.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
    print("Veritabanı hazır:", DB_PATH)
    print("Şablonlar:", json.dumps(get_templates(), ensure_ascii=False, indent=2)[:400])
    print("Öneri (AYKBYK):", suggest_numbers("AYKBYK"))
