import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import release_fixture as fx  # noqa: E402
from odaoc_fetch import FetchError, Release, fetch_client, sha256_file  # noqa: E402


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def release(self, server, lock, **kw):
        kw.setdefault("retries", 1)
        kw.setdefault("backoff", 0)
        return Release(server.lock(lock), **kw)

    def test_extract_verifies_and_then_skips(self):
        lock, files = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            dest = os.path.join(self.dir, "out", "nav1")
            self.assertEqual(rel.extract("runtime/server/navmesh/zone001.nav", dest), "ok")
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), files["runtime/server/navmesh/zone001.nav"])
            self.assertEqual(rel.extract("runtime/server/navmesh/zone001.nav", dest), "skip")

    def test_files_spanning_part_boundaries(self):
        lock, files = fx.build(self.dir, part_size=777)
        self.assertGreater(len(lock["parts"]), 5)
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            for name, data in files.items():
                dest = os.path.join(self.dir, "all", name)
                rel.extract(name, dest)
                with open(dest, "rb") as f:
                    self.assertEqual(f.read(), data, name)

    def test_manifest_pin_mismatch_is_refused(self):
        lock, _ = fx.build(self.dir)
        lock["manifest_sha256"] = "0" * 64
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            with self.assertRaisesRegex(FetchError, "does not match the pinned"):
                rel.manifest()

    def test_file_not_matching_manifest_is_refused_and_not_left_behind(self):
        target = "runtime/server/navmesh/zone002.nav"
        lock, _ = fx.build(self.dir, tamper={target: "1" * 64})
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            dest = os.path.join(self.dir, "out", "zone002.nav")
            with self.assertRaisesRegex(FetchError, "SHA-256 mismatch"):
                rel.extract(target, dest)
            self.assertFalse(os.path.exists(dest))
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_network_failure_leaves_no_partial_file(self):
        lock, _ = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            rel.manifest()  # index and manifest succeed
            srv.fail = lambda path, rng: True
            dest = os.path.join(self.dir, "out", "world.db")
            with self.assertRaisesRegex(FetchError, "range request failed"):
                rel.extract("runtime/data/opendaoc.sqlite3.db", dest)
            self.assertFalse(os.path.exists(dest))
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_truncated_transfer_is_retried_then_reported(self):
        lock, _ = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock, retries=2)
            rel.manifest()
            srv.truncate = lambda path, rng: True
            dest = os.path.join(self.dir, "out", "world.db")
            with self.assertRaisesRegex(FetchError, "range request failed"):
                rel.extract("runtime/data/opendaoc.sqlite3.db", dest)
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_one_truncated_transfer_is_retried(self):
        lock, files = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock, retries=2)
            rel.manifest()
            seen = []
            srv.truncate = lambda path, rng: (seen.append(rng), len(seen) == 1)[1]
            dest = os.path.join(self.dir, "out", "world.db")
            self.assertEqual(rel.extract("runtime/data/opendaoc.sqlite3.db", dest), "ok")
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), files["runtime/data/opendaoc.sqlite3.db"])

    def test_unsafe_archive_path_is_refused(self):
        lock, _ = fx.build(self.dir, extra_names=[fx.ROOT + "../evil.txt"])
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "unsafe archive path"):
                self.release(srv, lock).entries()

    def test_unknown_edition_is_refused(self):
        lock, _ = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "unknown edition"):
                self.release(srv, lock).edition("deluxe")

    def test_fetch_client_overlays_only_differences_and_edition_game_dll(self):
        lock, files = fx.build(self.dir)
        client = os.path.join(self.dir, "client")
        os.makedirs(client)
        with open(os.path.join(client, "connect.exe"), "wb") as f:
            f.write(files["runtime/client-opendaoc/app/connect.exe"])  # identical: not fetched
        with open(os.path.join(client, "paths.dat"), "wb") as f:
            f.write(b"[paths]\r\nsettings=Atlas1")  # different: fetched
        with open(os.path.join(client, "game.dll"), "wb") as f:
            f.write(b"stock")  # replaced by the edition's game.dll
        with fx.RangeServer(self.dir) as srv:
            n = fetch_client(self.release(srv, lock), "classic", client, log=lambda *_: None)
        self.assertEqual(n, 3)  # paths.dat, ui/new_window.xml, game.dll
        with open(os.path.join(client, "game.dll"), "rb") as f:
            self.assertEqual(f.read(), files["editions/0.34-no-custom-class/runtime/client-opendaoc/app/game.dll"])
        with open(os.path.join(client, "paths.dat"), "rb") as f:
            self.assertEqual(f.read(), files["runtime/client-opendaoc/app/paths.dat"])
        self.assertTrue(os.path.isfile(os.path.join(client, "ui", "new_window.xml")))

    def test_cli_extract(self):
        lock, files = fx.build(self.dir)
        with fx.RangeServer(self.dir) as srv:
            lock_path = os.path.join(self.dir, "upstream.lock")
            with open(lock_path, "w") as f:
                json.dump(srv.lock(lock), f)
            dest = os.path.join(self.dir, "cli", "logconfig.xml")
            out = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "odaoc_fetch.py"),
                                  "--lock", lock_path, "extract", "runtime/server/config/logconfig.xml", dest],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(sha256_file(dest), hashlib.sha256(files["runtime/server/config/logconfig.xml"]).hexdigest())


    def test_a_local_manifest_is_checked_against_the_pin_and_read_instead_of_the_archives(self):
        lock, files = fx.build(self.dir)
        path = os.path.join(self.dir, "manifest.sha256")
        with open(path, "wb") as f:
            f.write("".join(f"{hashlib.sha256(data).hexdigest()}  {rel}\n" for rel, data in sorted(files.items())).encode())
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock, manifest_file=path)
            sha = rel.expected_sha256("runtime/server/navmesh/zone001.nav")
            self.assertEqual(srv.requests, [])  # neither the index nor the manifest was downloaded
            self.assertEqual(sha, hashlib.sha256(files["runtime/server/navmesh/zone001.nav"]).hexdigest())
            with open(path, "a") as f:
                f.write("0" * 64 + "  extra\n")
            with self.assertRaisesRegex(FetchError, "does not match the pinned"):
                self.release(srv, lock, manifest_file=path).manifest()


QUESTS = "runtime/server/classic-quests.json"
GUIDES = "runtime/server/classic-quest-guides.json"
POCKETS = "runtime/server/navmesh/pockets.json"
NAV2 = "runtime/server/navmesh/zone002.nav"
CLASSIC_DLL = "editions/0.34-no-custom-class/runtime/client-opendaoc/app/game.dll"
CLASSIC_DB = "editions/0.34-no-custom-class/runtime/data/opendaoc.sqlite3.db"
UPDATE = {"Version": "test.1", "IgnoreColumns": ["LastTimeRowUpdated"], "NewTables": [], "NewColumns": [], "Tables": []}


class PatchFetchTests(unittest.TestCase):
    """A lock with a "patch": upstream's game patch on a full base release (0.37b = 0.36b + the 0.37 patch)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.base_lock, self.base_files = fx.build(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def patched(self, **kw):
        kw.setdefault("files", {QUESTS: b'{"Quests": {"new": 1}}', POCKETS: b'{"pockets": []}'})
        return fx.build_patch(self.dir, self.base_lock, self.base_files, **kw)

    def release(self, srv, lock):
        return Release(srv.lock(lock), retries=1, backoff=0)

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_a_file_the_patch_lists_comes_from_the_patch_zip_and_the_rest_from_the_base(self):
        lock, patch_files = self.patched()
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            for name in (QUESTS, GUIDES, POCKETS):
                self.assertEqual(rel.extract(name, os.path.join(self.dir, "out", name)), "ok")
            self.assertEqual(rel.extract(QUESTS, os.path.join(self.dir, "out", QUESTS)), "skip")
            self.assertIn(f"/{fx.PATCH_NAME}", {path for path, _ in srv.requests})
        self.assertEqual(self.read(os.path.join(self.dir, "out", QUESTS)), patch_files[QUESTS])
        self.assertEqual(self.read(os.path.join(self.dir, "out", POCKETS)), patch_files[POCKETS])
        self.assertEqual(self.read(os.path.join(self.dir, "out", GUIDES)), self.base_files[GUIDES])

    def test_a_patch_file_not_matching_patch_json_is_refused_and_not_left_behind(self):
        lock, _ = self.patched(tamper={QUESTS: "1" * 64})
        dest = os.path.join(self.dir, "out", "classic-quests.json")
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "SHA-256 mismatch against the patch's patch.json"):
                self.release(srv, lock).extract(QUESTS, dest)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_patch_json_not_matching_the_lock_pin_is_refused(self):
        lock, _ = self.patched()
        lock["patch"]["patch_json_sha256"] = "0" * 64
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "SHA-256 mismatch against the lock's pin: patch.json"):
                self.release(srv, lock).extract(GUIDES, os.path.join(self.dir, "out", "guides.json"))

    def test_a_patch_for_another_base_release_is_refused(self):
        lock, _ = self.patched(identity_from=["2" * 64])
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "is not for this base release"):
                self.release(srv, lock).files_under("runtime/server/")

    def test_files_under_has_the_patchs_new_files_and_not_its_removed_ones(self):
        lock, _ = self.patched(remove=[NAV2])
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            self.assertEqual(rel.files_under("runtime/server/navmesh/"), [POCKETS, "runtime/server/navmesh/zone001.nav"])
            with self.assertRaisesRegex(FetchError, "removed by the test patch"):
                rel.extract(NAV2, os.path.join(self.dir, "out", "zone002.nav"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "out", "zone002.nav")))

    def test_edition_files_come_from_the_base_though_the_patch_removes_them(self):
        lock, _ = self.patched(remove=[CLASSIC_DLL, CLASSIC_DB])
        dest = os.path.join(self.dir, "out", "game.dll")
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, lock)
            self.assertIn(CLASSIC_DLL, rel.files_under("editions/"))
            self.assertEqual(rel.extract(CLASSIC_DLL, dest), "ok")
        self.assertEqual(self.read(dest), self.base_files[CLASSIC_DLL])

    def test_a_patch_that_ships_an_edition_file_is_refused(self):
        lock, _ = self.patched(files={CLASSIC_DLL: b"patched game.dll"})
        with fx.RangeServer(self.dir) as srv:
            with self.assertRaisesRegex(FetchError, "only the base may hold"):
                self.release(srv, lock).extract(CLASSIC_DLL, os.path.join(self.dir, "out", "game.dll"))

    def test_the_world_update_is_the_file_both_the_lock_and_patch_json_name(self):
        update = dict(UPDATE, Tables=[{"Table": "t", "Columns": ["id"], "Key": ["id"], "IgnoreCompare": [],
                                       "Insert": [[1]], "Update": [], "Delete": []}])
        lock, _ = self.patched(updates={"classic": ("plain", "db-test.json", update)})
        with fx.RangeServer(self.dir) as srv:
            self.assertEqual(self.release(srv, lock).world_update("classic"), ("test.1", update))
            with self.assertRaisesRegex(FetchError, "names no world update .* for edition 'b'"):
                self.release(srv, lock).world_update("b")
            other = json.loads(json.dumps(lock))
            other["patch"]["world_updates"]["classic"]["database"] = "b"
            with self.assertRaisesRegex(FetchError, "patch.json names None as the 'b' world update"):
                self.release(srv, other).world_update("classic")
            other = json.loads(json.dumps(lock))
            other["patch"]["world_updates"]["classic"]["sha256"] = "3" * 64
            with self.assertRaisesRegex(FetchError, "SHA-256 mismatch against the lock's pin: db-test.json"):
                self.release(srv, other).world_update("classic")

    def test_a_release_without_a_patch_has_no_world_update(self):
        with fx.RangeServer(self.dir) as srv:
            rel = self.release(srv, self.base_lock)
            self.assertIsNone(rel.world_update("classic"))
            self.assertIsNone(rel.patch())

    def test_fetch_client_takes_a_client_file_the_patch_replaces(self):
        paths = "runtime/client-opendaoc/app/paths.dat"
        lock, patch_files = self.patched(files={paths: b"[paths]\r\nsettings=OfflineDAoC037"})
        client = os.path.join(self.dir, "client")
        os.makedirs(client)
        with open(os.path.join(client, "paths.dat"), "wb") as f:
            f.write(self.base_files[paths])  # the base's: the patch's differs, so it is fetched
        with fx.RangeServer(self.dir) as srv:
            n = fetch_client(self.release(srv, lock), "classic", client, log=lambda *_: None)
        self.assertEqual(n, 4)  # paths.dat, connect.exe, ui/new_window.xml, game.dll
        self.assertEqual(self.read(os.path.join(client, "paths.dat")), patch_files[paths])
        self.assertEqual(self.read(os.path.join(client, "game.dll")), self.base_files[CLASSIC_DLL])

    def test_cli_list_shows_each_file_from_where_it_comes(self):
        lock, patch_files = self.patched()
        with fx.RangeServer(self.dir) as srv:
            lock_path = os.path.join(self.dir, "upstream.lock")
            with open(lock_path, "w") as f:
                json.dump(srv.lock(lock), f)
            out = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "odaoc_fetch.py"),
                                  "--lock", lock_path, "list", "--prefix", "runtime/server/navmesh/"],
                                 capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.splitlines(), [f"{len(patch_files[POCKETS]):>12} {POCKETS}",
                                                   f"{5000:>12} runtime/server/navmesh/zone001.nav",
                                                   f"{7000:>12} {NAV2}"])


if __name__ == "__main__":
    unittest.main()
