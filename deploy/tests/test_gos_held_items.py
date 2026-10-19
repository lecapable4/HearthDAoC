"""A Guild of Shadows reward a player holds, on the owner's world after ./hdc update (owner decision 2.a, #138).

The upgrade imports every character's items into a clean 0.37b world, whose 41 Guild of Shadows rows are upstream's
0.36 ones; the first start's world fixes then replace them with the fork's (deploy/bin/epic_chains.py, step 7). An
item a player holds is an Inventory row that names its template by Id_nb (ITemplate_Id), so it takes the fork's stats
and class lock from the replaced row, as long as the replace keeps the row's Id_nb and ItemTemplate_ID and leaves the
Inventory row as it is.

With HDC_TEST_WORLD (a clean classic world, 0.37b), on a copy of it.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

import epic_chains  # noqa: E402
import world_fixes  # noqa: E402

TEST_WORLD = os.environ.get("HDC_TEST_WORLD")
# Two rewards upstream 0.36 ships with other values: the Mercenary's sleeves (another model, no PackageID of ours) and the
# Spirit Threaded Cloak, which upstream lets any class wear.
HELD = ("cq_alb_sleeves_of_might", "cq_alb_spirit_threaded_cloak")


@unittest.skipUnless(TEST_WORLD, "needs HDC_TEST_WORLD (a clean classic world database)")
class HeldItemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "world.db")
        shutil.copyfile(TEST_WORLD, self.db)
        os.chmod(self.db, 0o644)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_held_reward_reads_the_forks_values_after_the_first_start(self):
        conn = sqlite3.connect(self.db)
        try:
            with conn:  # what the importer carries: a character's items in its backpack
                for slot, id_nb in enumerate(HELD, 40):
                    conn.execute("INSERT INTO Inventory (Inventory_ID, OwnerID, ITemplate_Id, SlotPosition, Count) "
                                 "VALUES (?, 'held-items-test', ?, ?, 1)", (f"held-{id_nb}", id_nb, slot))
            held = conn.execute("SELECT * FROM Inventory ORDER BY Inventory_ID").fetchall()
            row_ids = dict(conn.execute(f"SELECT Id_nb, ItemTemplate_ID FROM ItemTemplate WHERE Id_nb IN "
                                        f"({', '.join('?' * len(HELD))})", HELD).fetchall())
        finally:
            conn.close()
        self.assertEqual(sorted(row_ids), sorted(HELD))
        world_fixes.apply(self.db)
        entries = {item["Id_nb"]: item for item in epic_chains.load_data()["items"]}
        conn = sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)
        try:
            self.assertEqual(conn.execute("SELECT * FROM Inventory ORDER BY Inventory_ID").fetchall(), held)
            for id_nb in HELD:
                with self.subTest(id_nb):
                    ours = {c: v for c, v in entries[id_nb].items() if c != "Id_nb"}
                    self.assertTrue(epic_chains._holds(conn, id_nb, ours))
                    template = conn.execute("SELECT t.ItemTemplate_ID, t.AllowedClasses FROM Inventory i JOIN "
                                            "ItemTemplate t ON t.Id_nb = i.ITemplate_Id WHERE i.ITemplate_Id=?",
                                            (id_nb,)).fetchone()
                    self.assertEqual(template, (row_ids[id_nb], ours["AllowedClasses"]))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
