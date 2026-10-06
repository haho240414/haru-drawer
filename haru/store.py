"""SQLite 저장소. 대시보드(Flask)와 데몬이 같이 쓰므로 WAL 모드."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config
from .timeutil import iso, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  ts TEXT NOT NULL,
  source TEXT NOT NULL,        -- kakao | share | inbox
  kind TEXT NOT NULL,          -- link | image | text | video | file | audio
  text TEXT,
  url TEXT,
  url_key TEXT,
  media TEXT,                  -- MEDIA 아래 상대 경로
  meta TEXT,                   -- 링크·이미지에서 가져온 정보 (JSON)
  analysis TEXT,               -- AI 분석 결과 (JSON)
  status TEXT NOT NULL DEFAULT 'new',   -- new | enriched | analyzed | error | hidden
  error TEXT,
  origin TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_day ON items(day);
CREATE INDEX IF NOT EXISTS idx_items_urlkey ON items(url_key);
CREATE TABLE IF NOT EXISTS digests(
  day TEXT PRIMARY KEY,
  version INTEGER NOT NULL DEFAULT 0,
  data TEXT,
  item_sig TEXT,
  generated_at TEXT,
  published_at TEXT,
  published_sig TEXT
);
CREATE TABLE IF NOT EXISTS imports(
  id TEXT PRIMARY KEY, name TEXT, platform TEXT, at TEXT, stats TEXT
);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, msg TEXT
);
CREATE TABLE IF NOT EXISTS todos_done(
  key TEXT PRIMARY KEY, at TEXT
);
"""

_local = threading.local()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    return con


def db() -> sqlite3.Connection:
    key = str(config.DB_PATH)
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "key", None) != key:
        con = connect()
        _local.con, _local.key = con, key
    return con


def reset_connection() -> None:
    con = getattr(_local, "con", None)
    if con is not None:
        con.close()
    _local.con = None


@contextmanager
def tx():
    con = db()
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("meta", "analysis", "data", "stats"):
        if k in d and isinstance(d[k], str) and d[k]:
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


# ---------- items ----------
def upsert_item(item: dict) -> str:
    """새 항목이면 넣고 'new', 이미 있으면 비어 있던 사진만 채우고 'dup' (또는 'media')."""
    con = db()
    cur = con.execute("SELECT id, media, status FROM items WHERE id=?", (item["id"],)).fetchone()
    t = iso(now())
    if cur is None:
        con.execute(
            "INSERT INTO items(id, day, ts, source, kind, text, url, url_key, media, meta, analysis, status, origin,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item["day"], item["ts"], item["source"], item["kind"], item.get("text"), item.get("url"),
             item.get("url_key"), item.get("media"), json.dumps(item.get("meta") or {}, ensure_ascii=False),
             None, "new", item.get("origin"), t, t))
        return "new"
    if item.get("media") and not cur["media"]:
        con.execute("UPDATE items SET media=?, status='new', analysis=NULL, updated_at=? WHERE id=?",
                    (item["media"], t, item["id"]))
        return "media"
    return "dup"


def get_item(item_id: str) -> dict | None:
    return _row(db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())


def items_for_day(day: str, include_hidden: bool = False) -> list[dict]:
    q = "SELECT * FROM items WHERE day=?" + ("" if include_hidden else " AND status!='hidden'") + " ORDER BY ts, id"
    return [_row(r) for r in db().execute(q, (day,)).fetchall()]


def items_by_status(statuses: tuple[str, ...], day: str | None = None) -> list[dict]:
    q = f"SELECT * FROM items WHERE status IN ({','.join('?' * len(statuses))})"
    args: list = list(statuses)
    if day:
        q += " AND day=?"
        args.append(day)
    return [_row(r) for r in db().execute(q + " ORDER BY ts", args).fetchall()]


def update_item(item_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = iso(now())
    sets, args = [], []
    for k, v in fields.items():
        if k in ("meta", "analysis") and v is not None and not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k}=?")
        args.append(v)
    args.append(item_id)
    db().execute(f"UPDATE items SET {', '.join(sets)} WHERE id=?", args)


def find_analyzed_by_url(url_key: str, exclude_id: str) -> dict | None:
    """같은 링크를 전에 분석한 적 있으면 재사용 (다른 날 또 보낸 링크)."""
    r = db().execute(
        "SELECT * FROM items WHERE url_key=? AND id!=? AND status='analyzed' ORDER BY updated_at DESC LIMIT 1",
        (url_key, exclude_id)).fetchone()
    return _row(r)


def days_with_items(limit: int = 120) -> list[dict]:
    rows = db().execute(
        "SELECT d.day, COUNT(i.id) n, SUM(i.status='analyzed') analyzed"
        " FROM (SELECT day FROM items WHERE status!='hidden' UNION SELECT day FROM digests) d"
        " LEFT JOIN items i ON i.day=d.day AND i.status!='hidden'"
        " GROUP BY d.day ORDER BY MAX(d.day) DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        dg = db().execute("SELECT version, generated_at, published_at FROM digests WHERE day=?", (r["day"],)).fetchone()
        out.append({"day": r["day"], "count": r["n"], "analyzed": r["analyzed"] or 0,
                    "digest_version": dg["version"] if dg else 0,
                    "generated_at": dg["generated_at"] if dg else None,
                    "published_at": dg["published_at"] if dg else None})
    return out


# ---------- digests ----------
def get_digest(day: str) -> dict | None:
    return _row(db().execute("SELECT * FROM digests WHERE day=?", (day,)).fetchone())


def save_digest(day: str, data: dict, item_sig: str) -> int:
    con = db()
    cur = con.execute("SELECT version FROM digests WHERE day=?", (day,)).fetchone()
    ver = (cur["version"] if cur else 0) + 1
    data["version"] = ver
    con.execute(
        "INSERT INTO digests(day, version, data, item_sig, generated_at) VALUES(?,?,?,?,?)"
        " ON CONFLICT(day) DO UPDATE SET version=excluded.version, data=excluded.data,"
        " item_sig=excluded.item_sig, generated_at=excluded.generated_at",
        (day, ver, json.dumps(data, ensure_ascii=False), item_sig, iso(now())))
    return ver


def mark_published(day: str, sig: str) -> None:
    db().execute("UPDATE digests SET published_at=?, published_sig=? WHERE day=?", (iso(now()), sig, day))


# ---------- kv / events ----------
def kv_get(k: str, default=None):
    r = db().execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    if r is None:
        return default
    try:
        return json.loads(r["v"])
    except json.JSONDecodeError:
        return r["v"]


def kv_set(k: str, v) -> None:
    db().execute("INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (k, json.dumps(v, ensure_ascii=False)))


def log_event(kind: str, msg: str) -> None:
    con = db()
    con.execute("INSERT INTO events(at, kind, msg) VALUES(?,?,?)", (iso(now()), kind, msg))
    con.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 500 FROM events)")


def recent_events(n: int = 40) -> list[dict]:
    return [dict(r) for r in db().execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()]


def record_import(imp_id: str, name: str, platform: str, stats: dict) -> None:
    db().execute("INSERT OR REPLACE INTO imports(id, name, platform, at, stats) VALUES(?,?,?,?,?)",
                 (imp_id, name, platform, iso(now()), json.dumps(stats, ensure_ascii=False)))


def recent_imports(n: int = 20) -> list[dict]:
    return [_row(r) for r in db().execute("SELECT * FROM imports ORDER BY at DESC LIMIT ?", (n,)).fetchall()]


def set_todo_done(key: str, done: bool) -> None:
    if done:
        db().execute("INSERT OR REPLACE INTO todos_done(key, at) VALUES(?, ?)", (key, iso(now())))
    else:
        db().execute("DELETE FROM todos_done WHERE key=?", (key,))


def todos_done() -> set[str]:
    return {r["key"] for r in db().execute("SELECT key FROM todos_done").fetchall()}


def days_for_todo(key: str) -> list[str]:
    if not key:
        return []
    rows = db().execute("SELECT day, data FROM digests WHERE data LIKE ?", (f"%{key}%",)).fetchall()
    return [r["day"] for r in rows if any(t.get("key") == key for t in json.loads(r["data"]).get("todos", []))]
