"""
Default tests and a one-time import of the flavours and test dates from the
original Google Sheet. Runs only when the database is first created.
"""

DEFAULT_TESTS = [
    # name, what it covers, repeat every N months, price (Rs), active, order
    ("Physico-chemical", "Moisture, total ash, acid insoluble ash, volatile oil, heat value", 12, 2250, 1, 10),
    ("Heavy metals", "Arsenic, cadmium, copper, lead, mercury, methyl mercury, tin", 12, 4050, 1, 20),
    ("Pesticide residues", "Multi-residue profile incl. ethylene oxide, chlorpyrifos, profenofos", 12, 9000, 1, 30),
    ("Aflatoxins & OTA", "Total aflatoxins (B1, B2, G1, G2) and ochratoxin A", 12, None, 1, 40),
    ("Microbiology", "TPC, yeast & mould, coliforms / E. coli, Salmonella, S. aureus, B. cereus", 12, 2250, 1, 50),
    ("Illegal dyes", "Sudan I-IV, metanil yellow, auramine O, rhodamine B, orange II, malachite green", 12, None, 1, 60),
    ("Nutrition", "Label nutrition panel incl. sodium", 12, None, 1, 70),
    ("Food additives", "Anticaking agents, preservatives, permitted colours (only if added)", 12, None, 0, 80),
]

# Short keys used below -> test names above
T = {
    "phys": "Physico-chemical",
    "metals": "Heavy metals",
    "pr": "Pesticide residues",
    "myco": "Aflatoxins & OTA",
    "micro": "Microbiology",
    "dyes": "Illegal dyes",
    "nut": "Nutrition",
}
FSSAI_SIX = ["phys", "metals", "pr", "myco", "micro", "dyes"]

# (flavour, category, notes, completed tests [(date, [keys])], awaiting reports [(date sent, [keys])])
# The sheet's "Chemical" column is recorded as both Physico-chemical and Heavy metals.
FLAVOURS = [
    ("Achaari Atyachaari", "existing", "", [("2026-03-29", ["nut"]), ("2025-06-28", ["phys", "metals"])], [("2026-09-24", FSSAI_SIX)]),
    ("Afghan Ka Shaitan", "existing", "", [("2026-03-29", ["nut"]), ("2025-06-28", ["phys", "metals"])], []),
    ("Bloody Peri", "existing", "", [("2026-03-31", ["nut"])], [("2026-09-24", FSSAI_SIX)]),
    ("Curry 9211", "existing", "", [("2026-03-29", ["nut"])], []),
    ("Dhaniya Mirchi Aur Woh", "existing", "", [("2026-03-29", ["nut"]), ("2026-06-24", ["micro"]), ("2025-06-28", ["phys", "metals"])], []),
    ("Gangs Of Awadh", "existing", "", [("2026-03-29", ["nut"]), ("2025-06-28", ["phys", "metals"]), ("2025-10-17", ["pr"])], []),
    ("Kali Mirch Ki Haddcurry", "existing", "", [("2026-03-29", ["nut"])], []),
    ("Lucknowi Tamancha", "existing", "", [("2026-03-29", ["nut"]), ("2025-07-28", ["phys", "metals"])], []),
    ("Paapi Pudina", "existing", "", [("2026-03-29", ["nut"]), ("2026-03-17", ["micro"]), ("2026-03-18", ["phys", "metals"])], []),
    ("Palak Ka Panchnama", "existing", "", [("2026-03-29", ["nut"])], []),
    ("Pistol Pesto", "existing", "", [("2026-03-29", ["nut"]), ("2025-06-28", ["phys", "metals"])], []),
    ("Saza E Kali Mirch", "existing", "", [("2026-03-29", ["nut"]), ("2026-04-06", ["micro"]), ("2025-06-28", ["phys", "metals"])], []),
    ("Shawarma Ji Ka Beta", "existing", "", [("2026-03-29", ["nut"]), ("2025-06-28", ["phys", "metals"])], []),
    ("Tandoori Blast", "existing", "", [("2026-03-29", ["nut"]), ("2026-04-06", ["micro"]), ("2026-03-18", ["phys", "metals"]), ("2025-10-17", ["pr"])], []),
    ("Chicken 65", "new", "Shelf life (6 months): 17 Sep 2026.", [], [("2026-09-17", ["nut"])]),
    ("Arabic Biryani Masala", "new", "Sodium tested 17 Aug 2026. Shelf life 6M: 20 Aug 2026, 9M: 9 Sep 2026.", [("2026-07-13", ["nut"])], []),
    ("Awadhi Biryani Masala", "new", "Sodium tested 17 Aug 2026. Shelf life 6M: 20 Aug 2026, 9M: 16 Sep 2026.", [("2026-07-13", ["nut"])], []),
    ("Chettinad Biryani Masala", "new", "Sodium tested 17 Aug 2026. Shelf life 6M: 20 Aug 2026, 9M: 9 Sep 2026.", [("2026-07-13", ["nut"])], []),
    ("Pan Tikka Flavour", "new", "Shelf life 6M: 10 Sep 2026. 9M report dated 18 Sep 2026.", [("2026-07-28", ["nut"])], []),
    ("Rogan Josh", "new", "Shelf-life report expected 24 Sep 2026.", [], [("2026-09-24", ["nut"])]),
    ("Fennel - Gravy", "new", "Shelf-life report expected 24 Sep 2026.", [], [("2026-09-24", ["nut"])]),
]


def seed_tests(db):
    for name, covers, months, price, active, order in DEFAULT_TESTS:
        db.execute(
            "INSERT INTO tests(name, covers, frequency_months, price, active, sort_order) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            (name, covers, months, price, active, order),
        )


def seed_sheet(db, now_iso):
    test_ids = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM tests")}
    for name, category, notes, done, waiting in FLAVOURS:
        fid = db.insert(
            "INSERT INTO flavours(name, category, notes, created_at) VALUES (?,?,?,?)",
            (name, category, notes, now_iso),
        )
        for day, keys in done:
            sid = db.insert(
                """INSERT INTO submissions(flavour_id, sample_date, lab_name, status, remarks, created_at, source)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, day, "", "complete", "Imported from Google Sheet. No report link.", now_iso, "import"),
            )
            for k in keys:
                db.execute("INSERT INTO submission_tests(submission_id, test_id) VALUES (?,?)", (sid, test_ids[T[k]]))
        for day, keys in waiting:
            sid = db.insert(
                """INSERT INTO submissions(flavour_id, sample_date, lab_name, status, remarks, created_at, source)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, day, "Equinox", "awaiting_report", "Imported from Google Sheet.", now_iso, "import"),
            )
            for k in keys:
                db.execute("INSERT INTO submission_tests(submission_id, test_id) VALUES (?,?)", (sid, test_ids[T[k]]))
