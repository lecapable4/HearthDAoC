"""Test helper: build a small fake OfflineDAoC release (split ZIP + manifest), and a fake upstream
game patch on it, and serve them over HTTP with Range support, so the fetch code can be tested
without the network."""
import hashlib
import http.server
import io
import json
import os
import random
import threading
import zipfile

ROOT = "OfflineDAoC-vtest/"
PATCH_ROOT = "OfflineDAoC-vtest-patch/"
PATCH_NAME = "game-patch.zip"
# Any base file can stand for upstream's patch identity (runtime/OfflineDAoC.dll).
IDENTITY = "runtime/server/config/logconfig.xml"


def _blob(seed, size):
    return random.Random(seed).randbytes(size)  # incompressible, so the archive spans several parts


DEFAULT_FILES = {
    "runtime/data/opendaoc.sqlite3.db": _blob(1, 3000),
    "editions/0.34-no-custom-class/runtime/data/opendaoc.sqlite3.db": _blob(2, 3500),
    "editions/0.34-no-custom-class/runtime/client-opendaoc/app/game.dll": _blob(3, 2500),
    "runtime/client-opendaoc/app/game.dll": _blob(4, 2600),
    "runtime/client-opendaoc/app/connect.exe": _blob(5, 900),
    "runtime/client-opendaoc/app/paths.dat": b"[paths]\r\nsettings=OfflineDAoC034",
    "runtime/client-opendaoc/app/ui/new_window.xml": b"<window/>" * 40,
    "runtime/server/navmesh/zone001.nav": _blob(6, 5000),
    "runtime/server/navmesh/zone002.nav": _blob(7, 7000),
    "runtime/server/config/logconfig.xml": b"<nlog/>",
    "runtime/server/classic-quests.json": b'{"Quests": {}}',
    "runtime/server/classic-quest-guides.json": b'{"Guides": {}}',
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def build(directory, files=None, part_size=4096, tamper=None, extra_names=()):
    """Write parts to directory/parts and return (lock_without_urls, files).

    tamper: {rel: wrong_sha} written into the manifest instead of the real hash.
    extra_names: raw archive names added as tiny entries (for path-safety tests).
    """
    files = dict(DEFAULT_FILES if files is None else files)
    tamper = tamper or {}
    manifest = "".join(f"{tamper.get(rel, hashlib.sha256(data).hexdigest())}  {rel}\n"
                       for rel, data in sorted(files.items())).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(ROOT, b"")  # directory entry, must be ignored
        for rel, data in sorted(files.items()):
            z.writestr(ROOT + rel, data)
        z.writestr(ROOT + "PACKAGE MANIFEST.sha256", manifest)
        for name in extra_names:
            z.writestr(name, b"x")
    blob = buf.getvalue()
    parts_dir = os.path.join(directory, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    parts = []
    for i in range(0, len(blob), part_size):
        name = f"release.zip.{len(parts) + 1:03d}"
        chunk = blob[i:i + part_size]
        with open(os.path.join(parts_dir, name), "wb") as f:
            f.write(chunk)
        parts.append({"name": name, "size": len(chunk)})
    lock = {
        "version": "test",
        "root_folder": ROOT,
        "parts": parts,
        "manifest_path": "PACKAGE MANIFEST.sha256",
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "client_prefix": "runtime/client-opendaoc/app/",
        "navmesh_prefix": "runtime/server/navmesh/",
        "config_prefix": "runtime/server/config/",
        "server_prefix": "runtime/server/",
        "server_files": ["classic-quests.json", "classic-quest-guides.json"],
        "editions": {
            "b": {"world_db": "runtime/data/opendaoc.sqlite3.db",
                  "game_dll": "runtime/client-opendaoc/app/game.dll"},
            "classic": {"world_db": "editions/0.34-no-custom-class/runtime/data/opendaoc.sqlite3.db",
                        "game_dll": "editions/0.34-no-custom-class/runtime/client-opendaoc/app/game.dll"},
        },
    }
    return lock, files


def build_patch(directory, lock, base_files, files=None, remove=(), updates=None, version="test.1",
                identity_from=None, tamper=None):
    """Write directory/parts/game-patch.zip, a fake upstream game patch on the release build() made, and
    return (lock with its "patch" object, {rel: bytes} of the patch's files).

    files: {rel: bytes} the patch adds or replaces (under files/ in the zip, listed in patch.json "Files").
    remove: rels patch.json "Remove" lists.
    updates: {lock edition: (patch.json "Database" key, file name, world update dict)}, at the zip's root.
    identity_from: the hashes patch.json says its Identity file may have (default: the base's).
    tamper: {rel: wrong_sha} written into patch.json instead of the file's real hash.
    """
    files = dict(files or {})
    tamper = tamper or {}
    updates = updates or {}
    meta = {
        "Version": version, "Kind": "game", "Title": f"test {version} update",
        "Identity": {"Path": IDENTITY, "To": _sha(b"new identity"),
                     "From": [_sha(base_files[IDENTITY])] if identity_from is None else identity_from},
        "Files": [{"Path": rel, "Sha256": tamper.get(rel, _sha(data)), "Bytes": len(data),
                   "From": [_sha(base_files[rel])] if rel in base_files else []}
                  for rel, data in sorted(files.items())],
        "Remove": [{"Path": rel, "From": [_sha(base_files[rel])]} for rel in remove],
        "Database": {key: name for key, name, _ in updates.values()},
    }
    meta_bytes = json.dumps(meta, indent=1).encode()
    update_bytes = {name: json.dumps(update).encode() for _, name, update in updates.values()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(PATCH_ROOT, b"")  # directory entry, must be ignored
        z.writestr(PATCH_ROOT + "patch.json", meta_bytes)
        for name, data in sorted(update_bytes.items()):
            z.writestr(PATCH_ROOT + name, data)
        for rel, data in sorted(files.items()):
            z.writestr(PATCH_ROOT + "files/" + rel, data)
    blob = buf.getvalue()
    parts_dir = os.path.join(directory, "parts")
    os.makedirs(parts_dir, exist_ok=True)
    with open(os.path.join(parts_dir, PATCH_NAME), "wb") as f:
        f.write(blob)
    patch = {"name": PATCH_NAME, "size": len(blob), "sha256": _sha(blob), "root_folder": PATCH_ROOT,
             "patch_json_sha256": _sha(meta_bytes),
             "world_updates": {edition: {"database": key, "path": name, "sha256": _sha(update_bytes[name])}
                               for edition, (key, name, _) in updates.items()}}
    return dict(lock, patch=patch), files


class RangeServer:
    """Serves directory/parts with HTTP Range support. Set .fail to a callable
    (path, range_header) -> bool to make matching requests fail with 503, or .truncate to one
    that makes them send only half of the promised bytes and close the connection."""

    def __init__(self, directory):
        self.directory = os.path.join(directory, "parts")
        self.requests = []
        self.fail = None
        self.truncate = None
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                rng = self.headers.get("Range")
                outer.requests.append((self.path, rng))
                if outer.fail and outer.fail(self.path, rng):
                    self.send_error(503)
                    return
                path = os.path.join(outer.directory, os.path.basename(self.path))
                if not os.path.isfile(path) or not rng or not rng.startswith("bytes="):
                    self.send_error(404 if not os.path.isfile(path) else 416)
                    return
                start, end = (int(x) for x in rng[6:].split("-"))
                with open(path, "rb") as f:
                    f.seek(start)
                    data = f.read(end - start + 1)
                self.send_response(206)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if outer.truncate and outer.truncate(self.path, rng):
                    self.wfile.write(data[:len(data) // 2])
                    self.close_connection = True
                    return
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def lock(self, lock):
        """Return a copy of lock with part URLs (and the patch's) pointing at this server."""
        out = dict(lock)
        out["parts"] = [{"url": f"{self.url}/{p['name']}", "size": p["size"]} for p in lock["parts"]]
        if "patch" in lock:
            out["patch"] = dict(lock["patch"], url=f"{self.url}/{lock['patch']['name']}")
        return out

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
