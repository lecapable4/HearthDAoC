"""deploy/upstream.lock pins upstream 0.37b: the full 0.36b release (the base) plus upstream's 0.37 game patch
(README 5.4 of the 0.37 research). Checked against what upstream commits about its 0.36 releases
(source/tools/release-baselines/0.36/) and against the hdc that reads the lock. With upstream's patch zip and clean
worlds at hand (HDC_TEST_PATCH_ZIP, HDC_TEST_BASE_WORLD, HDC_TEST_PATCHED_WORLD), the real patch is read through the
lock from a local copy, and the 0.37b world is built and compared table by table."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path[:0] = [os.path.join(REPO, "deploy", "bin"), os.path.join(REPO, "tools", "linux"),
                os.path.join(REPO, "tools", "linux", "accounts"), os.path.join(REPO, "tools", "linux", "tests")]

import accounts  # noqa: E402
import init_world  # noqa: E402
import release_fixture as fx  # noqa: E402
import world_admin  # noqa: E402
import world_update  # noqa: E402
from odaoc_fetch import Release  # noqa: E402
from tests import test_world_admin  # noqa: E402

LOCK = os.path.join(REPO, "deploy", "upstream.lock")
HDC = os.path.join(REPO, "deploy", "hdc")
BASELINES = os.path.join(REPO, "source", "tools", "release-baselines", "0.36")
BASE_MANIFEST = os.path.join(BASELINES, "0.36b-package.sha256")
RELEASES = "https://github.com/shadowofze/OfflineDAoC/releases/download/"
PATCH_ZIP = os.environ.get("HDC_TEST_PATCH_ZIP")  # upstream's OfflineDAoC-v0.37-game-patch.zip
BASE_WORLD = os.environ.get("HDC_TEST_BASE_WORLD")  # upstream's clean 0.36b classic world
PATCHED_WORLD = os.environ.get("HDC_TEST_PATCHED_WORLD")  # a clean 0.37b classic world to compare with
OLD_WORLD = os.environ.get("HDC_TEST_OLD_WORLD")  # upstream's clean 0.35b classic world (the live world's version)
TOOLS = os.environ.get("HDC_TOOLS")  # the built Linux CLIs (tools/linux/build.sh), for upstream's import engine
QUIET = lambda *a, **k: None  # noqa: E731


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def manifest(path):
    with open(path, encoding="utf-8") as f:
        return {line[66:].rstrip("\r\n"): line[:64] for line in f if line[64:66] == "  "}


def client_patch_files(lock):
    """(release path, SHA-256 before patching) of every file client/patches' sets patch, at the release paths CI's
    "Fetch the classic client files" step reads: the classic edition's game.dll, the rest under the client prefix."""
    out = []
    for name in ("classic-creation.json", "default-layout.json"):
        for f in load(os.path.join(REPO, "client", "patches", name))["files"]:
            rel = lock["editions"]["classic"]["game_dll"] if f["path"] == "game.dll" else lock["client_prefix"] + f["path"]
            out.append((rel, f["before"]))
    return out


class LockTests(unittest.TestCase):
    def setUp(self):
        self.lock = load(LOCK)

    def test_hdc_reads_the_releases_upstream_version_from_its_first_version_line(self):
        # The hdc that runs ./hdc update (v0.35b-hearth.20's too) reads the new lock with this function: the first
        # line with a "version" key. hdc_integration.sh rewrites every such key. So only the top level has one.
        with open(HDC, encoding="utf-8") as f:
            function = next(line for line in f if line.startswith("lock_version()"))
        out = subprocess.run(["bash", "-c", function + 'lock_version "$1"', "_", LOCK], capture_output=True, text=True)
        self.assertEqual((out.returncode, out.stdout), (0, "0.37b\n"), out.stderr)
        with open(LOCK, encoding="utf-8") as f:
            self.assertEqual(sum('"version"' in line for line in f), 1)

    def test_no_nested_object_has_a_version_key(self):
        def walk(node, top):
            if isinstance(node, dict):
                self.assertTrue(top or "version" not in node, node)
                for child in node.values():
                    walk(child, False)
            elif isinstance(node, list):
                for child in node:
                    walk(child, False)
        walk(self.lock, True)

    def test_the_release_is_upstreams_v0_37b(self):
        self.assertEqual((self.lock["upstream_repo"], self.lock["version"], self.lock["tag"], self.lock["commit"]),
                         ("shadowofze/OfflineDAoC", "0.37b", "v0.37b", "ab4df02a1ad26192357477dbc912756c6703fb66"))

    def test_the_base_is_upstreams_full_0_36b_release(self):
        published = load(os.path.join(BASELINES, "v0.36b-download-manifest.json"))
        self.assertEqual((self.lock["base_version"], self.lock["base_tag"], self.lock["base_commit"]),
                         ("0.36b", "v0.36b", load(os.path.join(BASELINES, "baseline.json"))["repo_commit"]))
        self.assertEqual(self.lock["root_folder"], published["RootFolder"] + "/")
        self.assertEqual(self.lock["archive_sha256"], published["ArchiveSHA256"])
        self.assertEqual(self.lock["parts"], [{"url": RELEASES + "v0.36b/" + p["Name"], "size": p["Bytes"], "sha256": p["SHA256"]}
                                              for p in published["Parts"]])
        self.assertEqual(self.lock["manifest_path"], "PACKAGE MANIFEST.sha256")
        self.assertEqual(self.lock["manifest_sha256"], sha256(BASE_MANIFEST))

    def test_the_editions_are_files_of_the_base(self):
        files = manifest(BASE_MANIFEST)
        self.assertEqual(sorted(self.lock["editions"]), ["b", "classic"])
        for edition in self.lock["editions"].values():
            self.assertEqual(sorted(edition), ["game_dll", "world_db"])
            for rel in edition.values():
                self.assertTrue(rel in files, f"{rel} is not in the base's manifest")
        classic = load(os.path.join(BASELINES, "baseline.json"))["edition_files_0.36"]
        self.assertEqual(files[self.lock["editions"]["classic"]["world_db"]], classic["runtime/data/opendaoc.sqlite3.db"])
        self.assertEqual(files[self.lock["editions"]["classic"]["game_dll"]], classic["runtime/client-opendaoc/app/game.dll"])

    def test_the_patch_is_upstreams_0_37_game_patch(self):
        patch = self.lock["patch"]
        self.assertEqual(patch["url"], RELEASES + "v0.37b/OfflineDAoC-v0.37-game-patch.zip")
        self.assertEqual((patch["size"], patch["sha256"], patch["root_folder"]),
                         (38084367, "48fd6482433c4e66748bee4842cb811df87a16e8b82b65fd017b91dd46d769c1",
                          "OfflineDAoC-v0.37-game-patch/"))
        self.assertEqual(patch["patch_json_sha256"], "9ad8740e939be96d92ab0ee53fa7a366d904eecfeda7c22d73e9400fe3acfbe6")
        update = "edce00002f7a5b2cdd41c9157659324275b891d8ebf4af7585c8bcadf5f013a7"  # db-0.37.json = db-0.37b.json
        self.assertEqual(patch["world_updates"], {"b": {"database": "b", "path": "db-0.37b.json", "sha256": update},
                                                  "classic": {"database": "plain", "path": "db-0.37.json", "sha256": update}})

    def test_the_server_files_and_the_navmesh_files_are_where_the_lock_says(self):
        self.assertEqual((self.lock["server_prefix"], self.lock["server_files"], self.lock["navmesh_prefix"]),
                         ("runtime/server/", ["classic-quests.json", "classic-quest-guides.json"], "runtime/server/navmesh/"))
        files = manifest(BASE_MANIFEST)
        for name in ("roads.json", "seams.json", "pockets.json", "zone001.nav"):  # pockets.json: the patch replaces it
            self.assertTrue(self.lock["navmesh_prefix"] + name in files, f"{name} is not in the base's manifest")

    def test_the_client_patch_sets_patch_the_releases_own_client_files(self):
        # client/patches' sets patch each player's own client: a file's "before" must be what the lock's release has
        # at that path (the classic edition's game.dll, the client's pregame files and default.ini), or no player's
        # client is patched ("Not patched"). The base's manifest gives them; RealPatchTests checks that the patch
        # replaces none of them.
        files = manifest(BASE_MANIFEST)
        for rel, before in client_patch_files(self.lock):
            with self.subTest(rel):
                self.assertEqual(files.get(rel), before)


@unittest.skipUnless(PATCH_ZIP, "needs HDC_TEST_PATCH_ZIP (upstream's OfflineDAoC-v0.37-game-patch.zip)")
class RealPatchTests(unittest.TestCase):
    """The lock read against upstream's real patch zip, served from a local copy (no network). The base's manifest is
    upstream's committed copy, checked against the lock's pin; the base archive itself is never read."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        os.makedirs(os.path.join(self.dir, "parts"))
        os.symlink(os.path.abspath(PATCH_ZIP), os.path.join(self.dir, "parts", "patch.zip"))
        self.srv = fx.RangeServer(self.dir).__enter__()
        lock = load(LOCK)
        lock["patch"] = dict(lock["patch"], url=self.srv.url + "/patch.zip")
        self.release = Release(lock, retries=1, backoff=0, manifest_file=BASE_MANIFEST)

    def tearDown(self):
        self.srv.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_patch_json_and_the_world_updates_match_the_lock(self):
        self.assertEqual(self.release.patch()["meta"]["Version"], "0.37")
        version, classic = self.release.world_update("classic")
        self.assertEqual((version, classic["Version"]), ("0.37", "0.37"))
        self.assertEqual(self.release.world_update("b")[1], classic)
        self.assertEqual([t["Table"] for t in classic["NewTables"]], ["offline_world_bot_guild"])

    def test_the_patch_replaces_no_client_file_the_patch_sets_patch(self):
        listed = set(self.release.patch()["files"]) | set(self.release.patch()["removed"])
        self.assertEqual([rel for rel, _ in client_patch_files(load(LOCK)) if rel in listed], [])

    def test_the_server_files_from_the_patch_match_patch_json(self):
        for rel, sha in (("runtime/server/classic-quests.json", "8ff88f60017541cf8717bbf8ee412aaa67ee105be75595a7bb2f9680a20f413e"),
                         ("runtime/server/navmesh/pockets.json", "1c27f267dd74b83d3e1dac088ab14b46fc574b7081c8e0f05b665b9da1b9bef4")):
            dest = os.path.join(self.dir, "out", os.path.basename(rel))
            self.assertEqual(self.release.extract(rel, dest), "ok")
            self.assertEqual(sha256(dest), sha)
        self.assertEqual(self.release.expected_sha256("runtime/server/classic-quest-guides.json"),
                         manifest(BASE_MANIFEST)["runtime/server/classic-quest-guides.json"])  # from the base

    @unittest.skipUnless(BASE_WORLD and PATCHED_WORLD, "needs HDC_TEST_BASE_WORLD (upstream's clean 0.36b classic world) "
                                                       "and HDC_TEST_PATCHED_WORLD (a clean 0.37b classic world)")
    def test_the_world_built_from_the_cached_base_equals_the_clean_0_37b_world(self):
        cache = os.path.join(self.dir, "cache")
        base = os.path.join(cache, self.release.root.rstrip("/"), self.release.edition("classic")["world_db"])
        os.makedirs(os.path.dirname(base))
        shutil.copyfile(BASE_WORLD, base)
        dest = os.path.join(self.dir, "world", "opendaoc.sqlite3.db")
        logged = []
        self.assertEqual(world_update.build_world(self.release, "classic", dest, cache, logged.append), "skip")
        self.assertEqual(logged, ["Upstream's 0.37 world update applied to the new clean copy: 16 added, 263 changed, "
                                  "0 removed."])
        con = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
        try:
            con.execute("ATTACH DATABASE ? AS clean", (f"file:{PATCHED_WORLD}?mode=ro",))
            schema = "SELECT type, name, tbl_name, sql FROM {}.sqlite_master ORDER BY type, name"
            self.assertEqual(con.execute(schema.format("main")).fetchall(), con.execute(schema.format("clean")).fetchall())
            tables = [r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type='table' ORDER BY name")]
            differ = {}
            for t in tables:
                cols = "*" if t != "offline_patch_log" else "Version, Notes"  # AppliedUtc is the time of each build
                q = f'SELECT {cols} FROM main."{t}" EXCEPT SELECT {cols} FROM clean."{t}"'
                back = f'SELECT {cols} FROM clean."{t}" EXCEPT SELECT {cols} FROM main."{t}"'
                counts = [con.execute(f'SELECT count(*) FROM {db}."{t}"').fetchone()[0] for db in ("main", "clean")]
                n = (con.execute(f"SELECT count(*) FROM ({q})").fetchone()[0],
                     con.execute(f"SELECT count(*) FROM ({back})").fetchone()[0], counts[0] - counts[1])
                if n != (0, 0, 0):
                    differ[t] = n
            self.assertEqual(differ, {})
            self.assertEqual(len(tables), 128)
            self.assertEqual(con.execute("SELECT Version, Notes FROM offline_patch_log").fetchall(), [("0.37", "")])
        finally:
            con.close()

    def live_world(self):
        """A data folder with a 0.35b world, as ./hdc update finds the owner's: two accounts, one an admin."""
        data = os.path.join(self.dir, "data")
        db = init_world.world_paths(data)["db"]
        os.makedirs(os.path.dirname(db))
        shutil.copyfile(OLD_WORLD, db)
        os.chmod(db, 0o644)
        init_world.write_meta(init_world.world_paths(data)["meta"],
                              {"version": "0.35b", "edition": "classic", "navmesh": True, "created_utc": "x"})
        conn = accounts.connect(db)
        accounts.create(conn, "Admin1", "adminpw", plvl=3)
        accounts.create(conn, "Player2", "playerpw")
        conn.close()
        return data, db

    @unittest.skipUnless(OLD_WORLD and BASE_WORLD and TOOLS, "needs HDC_TEST_OLD_WORLD (upstream's clean 0.35b classic "
                                                            "world), HDC_TEST_BASE_WORLD and HDC_TOOLS (built CLIs)")
    def test_hdc_update_upgrades_a_0_35b_world_into_the_world_the_lock_builds(self):
        # ./hdc update hands the world over to the new release's upgrade-world: fetch-clean (here from the cached base
        # and the local patch zip), then upstream's 0.37 import engine, which takes 0.35b saves.
        data, db = self.live_world()
        cached = os.path.join(init_world.world_cache_dir(data), self.release.root.rstrip("/"),
                              self.release.edition("classic")["world_db"])
        os.makedirs(os.path.dirname(cached))
        shutil.copyfile(BASE_WORLD, cached)
        clean = world_admin.fetch_clean(self.release, data, log=QUIET)
        world_admin.upgrade_world(self.release, data, test_world_admin.importer_cmd(data), clean_world=clean, log=QUIET)
        with sqlite3.connect(db) as c:
            self.assertEqual(dict(c.execute("SELECT Name, PrivLevel FROM Account").fetchall()), {"Admin1": 3, "Player2": 1})
            self.assertEqual(c.execute("SELECT Version FROM offline_patch_log").fetchall(), [("0.37",)])
            self.assertEqual(c.execute("SELECT count(*) FROM offline_world_bot_guild").fetchone()[0], 0)
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(load(init_world.world_paths(data)["meta"])["version"], "0.37b")

    @unittest.skipUnless(OLD_WORLD and BASE_WORLD and TOOLS, "needs HDC_TEST_OLD_WORLD (upstream's clean 0.35b classic "
                                                            "world), HDC_TEST_BASE_WORLD and HDC_TOOLS (built CLIs)")
    def test_without_the_patchs_world_update_the_upgrade_fails_and_changes_nothing(self):
        # A lock that pinned only the 0.36b base would hand upstream's 0.37 import engine the bare 0.36b world. It
        # lacks the progress table only the world update adds, so the engine refuses it, and the world stays as it was.
        data, db = self.live_world()
        before, meta = sha256(db), load(init_world.world_paths(data)["meta"])
        with self.assertRaisesRegex(world_admin.AdminError, r"(?s)the import failed; the current world is unchanged\..*"
                                                            r"missing progress table offline_world_bot_guild"):
            world_admin.upgrade_world(self.release, data, test_world_admin.importer_cmd(data), clean_world=BASE_WORLD,
                                      log=QUIET)
        self.assertEqual(sha256(db), before)
        self.assertEqual(load(init_world.world_paths(data)["meta"]), meta)
        self.assertFalse(os.path.exists(os.path.join(data, "archive")))


if __name__ == "__main__":
    unittest.main()
