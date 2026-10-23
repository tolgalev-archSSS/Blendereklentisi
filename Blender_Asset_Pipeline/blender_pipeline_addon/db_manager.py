# =====================================================================
# db_manager.py - SQLite veritabani ve akilli numaralandirma motoru
# Harici paket gerektirmez (yerlesik sqlite3).
# Veritabani: <proje_koku>/database/assets.db (dinamik yol cozumu)
# =====================================================================

import os
import re
import json
import sqlite3
import threading

DB_FILENAME = "assets.db"

# 11 haneli sabit pozisyonlu kod deseni: KK P1 P2 P3 P4 2 MM VV
CODE_RE = re.compile(r"^[A-Z0-9]{6}2\d{4}$")

_local = threading.local()

DEFAULT_TEMPLATES = [
    {
        "category_code": "AY",
        "category_name": "Ayakkabi",
        "schema": {
            "P1": {
                "group": "Kitle",
                "options": {
                    "K": "Kadin",
                    "G": "Kiz Cocuk",
                    "E": "Erkek",
                    "C": "Erkek Cocuk",
                    "U": "Unisex",
                },
            },
            "P2": {
                "group": "Tur",
                "options": {
                    "S": "Spor",
                    "B": "Bot",
                    "C": "Cizme",
                    "A": "Sandalet",
                    "R": "Terlik",
                    "O": "Oxford",
                    "T": "Topuklu",
                    "F": "Babet/Flat",
                    "M": "Mary Jane",
                },
            },
            "P3": {
                "group": "Topuk Yuksekligi",
                "options": {
                    "D": "Duz/Topuksuz",
                    "A": "Alcak",
                    "Y": "Yuksek",
                    "P": "Platform",
                },
            },
            "P4": {
                "group": "Topuk Tipi",
                "options": {
                    "K": "Kalin",
                    "I": "Ince",
                    "D": "Diger/Yok",
                },
            },
        },
    },
    {
        "category_code": "HY",
        "category_name": "Hayvan",
        "schema": {
            "P1": {
                "group": "Sinif",
                "options": {
                    "K": "Kedi",
                    "I": "Kopek",
                    "A": "Kus",
                    "B": "Arilik",
                    "S": "Surungen",
                },
            },
            "P2": {
                "group": "Boyut",
                "options": {
                    "K": "Kucuk",
                    "O": "Orta",
                    "B": "Buyuk",
                },
            },
            "P3": {
                "group": "Detay",
                "options": {
                    "L": "Low Poly",
                    "H": "High Poly",
                    "G": "Game Ready",
                },
            },
            "P4": {
                "group": "Stil",
                "options": {
                    "R": "Realistik",
                    "C": "Cartoon",
                    "S": "Stilize",
                },
            },
        },
    },
]


def project_root():
    """Proje kok dizinini dinamik olarak cozer.

    .../Blender_Asset_Pipeline/blender_pipeline_addon/db_manager.py
    -> .../Blender_Asset_Pipeline
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)


def db_path():
    return os.path.join(project_root(), "database", DB_FILENAME)


def _conn():
    """Her thread icin ayri sqlite3 baglantisi (check_same_thread guvenligi)."""
    c = getattr(_local, "conn", None)
    if c is None:
        path = db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        c = sqlite3.connect(path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


def init_db():
    """Tablolari olusturur; templates bos ise AY ve HY sablonlarini tohumlar."""
    c = _conn()
    c.executescript(
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
    cur = c.execute("SELECT COUNT(*) AS n FROM templates")
    if cur.fetchone()["n"] == 0:
        for t in DEFAULT_TEMPLATES:
            c.execute(
                "INSERT INTO templates (category_code, category_name, schema_json) VALUES (?,?,?)",
                (t["category_code"], t["category_name"], json.dumps(t["schema"], ensure_ascii=False)),
            )
    c.commit()


def get_templates():
    """Tum sablonlari JSON parse edilmis sekilde donerür."""
    c = _conn()
    rows = c.execute("SELECT * FROM templates ORDER BY category_code").fetchall()
    out = []
    for r in rows:
        try:
            schema = json.loads(r["schema_json"])
        except (ValueError, TypeError):
            schema = {}
        out.append(
            {
                "id": r["id"],
                "category_code": r["category_code"],
                "category_name": r["category_name"],
                "schema": schema,
            }
        )
    return out


def add_template(category_code, category_name, schema_dict):
    """Yeni kategori sablonu ekler/gunceller. Zaten varsa overwrite edilir."""
    code = str(category_code or "").strip().upper()
    name = str(category_name or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{2}", code):
        raise ValueError("Kategori kodu tam 2 hane olmali (or: AY, HY).")
    if not name:
        raise ValueError("Kategori adi bos olamaz.")
    if not isinstance(schema_dict, dict) or not schema_dict:
        raise ValueError("Schema bos olmayan bir sozluk olmali.")
    c = _conn()
    c.execute(
        """INSERT INTO templates (category_code, category_name, schema_json)
           VALUES (?,?,?)
           ON CONFLICT(category_code) DO UPDATE SET
             category_name=excluded.category_name,
             schema_json=excluded.schema_json""",
        (code, name, json.dumps(schema_dict, ensure_ascii=False)),
    )
    c.commit()
    return {"category_code": code, "category_name": name}


def suggest_numbers(prefix):
    """Orn: prefix='AYKBYK' (6 karakter) icin akilli numaralandirma onerisi.

    Doner:
      next_new_model : yeni model icin onerilen MM (max_model+1)
      next_version   : o yeni modelin versiyonu (hep 1)
      existing_models: [{model_no, last_version, next_version}, ...]
    """
    prefix = str(prefix or "").strip().upper()
    if len(prefix) != 6:
        raise ValueError("Prefix tam 6 karakter olmali (KK + P1..P4).")
    c = _conn()
    rows = c.execute(
        "SELECT model_no, version_no FROM assets WHERE substr(full_code,1,6)=?",
        (prefix,),
    ).fetchall()
    if not rows:
        return {
            "next_new_model": 1,
            "next_version": 1,
            "existing_models": [],
        }
    by_model = {}
    for r in rows:
        m = int(r["model_no"])
        v = int(r["version_no"])
        by_model[m] = max(by_model.get(m, 0), v)
    max_model = max(by_model.keys())
    existing_models = [
        {
            "model_no": m,
            "last_version": by_model[m],
            "next_version": min(by_model[m] + 1, 99),
        }
        for m in sorted(by_model.keys())
    ]
    return {
        "next_new_model": min(max_model + 1, 99),
        "next_version": 1,
        "existing_models": existing_models,
    }


def save_asset(data_dict):
    """Asset kaydeder veya ayni uuid/full_code varsa gunceller (upsert)."""
    required = ("uuid", "full_code", "category", "p1", "p2", "p3", "p4", "model_no", "version_no")
    missing = [k for k in required if data_dict.get(k) in (None, "")]
    if missing:
        raise ValueError("Eksik alan(lar): %s" % ", ".join(missing))
    full_code = str(data_dict["full_code"]).strip().upper()
    if not CODE_RE.match(full_code):
        raise ValueError("Gecersiz 11 haneli kod: %s" % full_code)
    c = _conn()
    try:
        c.execute(
            """
            INSERT INTO assets
              (uuid, full_code, category, p1, p2, p3, p4,
               model_no, version_no, original_name, poly_count, vertex_count, blend_file_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(uuid) DO UPDATE SET
              full_code=excluded.full_code,
              category=excluded.category,
              p1=excluded.p1, p2=excluded.p2, p3=excluded.p3, p4=excluded.p4,
              model_no=excluded.model_no, version_no=excluded.version_no,
              original_name=excluded.original_name,
              poly_count=excluded.poly_count,
              vertex_count=excluded.vertex_count,
              blend_file_path=excluded.blend_file_path
            """,
            (
                str(data_dict["uuid"]),
                full_code,
                str(data_dict["category"]).upper(),
                str(data_dict["p1"]).upper(),
                str(data_dict["p2"]).upper(),
                str(data_dict["p3"]).upper(),
                str(data_dict["p4"]).upper(),
                int(data_dict["model_no"]),
                int(data_dict["version_no"]),
                data_dict.get("original_name"),
                data_dict.get("poly_count"),
                data_dict.get("vertex_count"),
                data_dict.get("blend_file_path"),
            ),
        )
    except sqlite3.IntegrityError:
        # Ayni full_code farkli bir uuid ile kayitli -> cagiran tarafa net soyle
        raise ValueError("Bu kod (%s) baska bir varlik kaydiyla cakisiyor." % full_code)
    # full_codecakismasi kontrolu (farkli uuid ile ayni kod engellenir)
    row = c.execute(
        "SELECT id, uuid FROM assets WHERE full_code=?", (full_code,)
    ).fetchone()
    c.commit()
    return {"status": "saved", "full_code": full_code, "uuid": str(data_dict["uuid"]), "id": row["id"] if row else None}


def get_assets(category_filter=None, search_query=None):
    """Kayitlari filtreleyerek donerür."""
    sql = "SELECT * FROM assets"
    conds = []
    args = []
    if category_filter:
        conds.append("category = ?")
        args.append(str(category_filter).upper())
    if search_query:
        q = "%%%s%%" % str(search_query)
        conds.append("(full_code LIKE ? OR original_name LIKE ?)")
        args.extend([q, q])
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC, id DESC"
    c = _conn()
    rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def asset_stats():
    c = _conn()
    total = c.execute("SELECT COUNT(*) AS n FROM assets").fetchone()["n"]
    cats = c.execute(
        "SELECT category, COUNT(*) AS n FROM assets GROUP BY category ORDER BY n DESC"
    ).fetchall()
    return {"total": total, "by_category": [dict(r) for r in cats]}
