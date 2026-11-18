# -*- coding: utf-8 -*-
"""seed2 漏了 MATERIAL_ISSUE（助手的耗材领用记录），补上。

领用会造成库存扣减，所以同时要更新 STOCK_LEDGER.on_hand_qty，
否则报表里"已领用"和"库存"对不上。
"""
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "..", "data", "adc.db")

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
con.execute("PRAGMA foreign_keys = ON")

n = con.execute("SELECT COUNT(*) FROM MATERIAL_ISSUE").fetchone()[0]
if n:
    print("MATERIAL_ISSUE 已有 %d 行，跳过" % n)
else:
    random.seed(20261113)
    staff = con.execute("SELECT staff_id, clinic_id FROM STAFF").fetchall()
    visits = con.execute("SELECT v.visit_id, v.clinic_id FROM VISIT v"
                         " ORDER BY v.visit_id DESC LIMIT 400").fetchall()
    batches = con.execute("SELECT b.batch_id, b.material_id, b.purchase_unit_price,"
                          " s.clinic_id, s.on_hand_qty"
                          " FROM MATERIAL_BATCH b"
                          " JOIN STOCK_LEDGER s ON s.material_id=b.material_id"
                          " ORDER BY b.batch_id").fetchall()
    by_clinic = {}
    for b in batches:
        by_clinic.setdefault(b["clinic_id"], []).append(b)
    if not batches:
        print("没有批次数据，无法造领用")
    else:
        made, seq = 0, 0
        for v in visits:
            if random.random() > 0.25:
                continue
            pool = by_clinic.get(v["clinic_id"]) or batches
            b = random.choice(pool)
            who = [s for s in staff if s["clinic_id"] == v["clinic_id"]] or staff
            st = random.choice(who)
            seq += 1
            qty = random.choice([1, 1, 2, 2, 3])
            when = datetime.now() - timedelta(days=random.randint(0, 90),
                                              hours=random.randint(0, 8))
            con.execute(
                "INSERT INTO MATERIAL_ISSUE(issue_no, batch_id, visit_id, quantity,"
                " issued_by, issued_datetime)"
                " VALUES(?,?,?,?,?,?)",
                ("MI%06d" % seq, b["batch_id"], v["visit_id"], qty,
                 st["staff_id"], when.strftime("%Y-%m-%d %H:%M:%S")))
            # 不要扣成负数：现查库存（b 里那份是循环开始时的快照，早过时了）
            left = con.execute("SELECT on_hand_qty FROM STOCK_LEDGER"
                               " WHERE material_id=? AND clinic_id=?",
                               (b["material_id"], v["clinic_id"])).fetchone()
            if left is None or (left[0] or 0) < qty:
                continue
            con.execute("UPDATE STOCK_LEDGER SET on_hand_qty=on_hand_qty-?"
                        " WHERE material_id=? AND clinic_id=?",
                        (qty, b["material_id"], v["clinic_id"]))
            made += 1
        con.commit()
        print("MATERIAL_ISSUE 新增 %d 行" % made)

tot = con.execute("SELECT COUNT(*) FROM MATERIAL_ISSUE").fetchone()[0]
neg = con.execute("SELECT COUNT(*) FROM STOCK_LEDGER WHERE on_hand_qty<0").fetchone()[0]
print("MATERIAL_ISSUE 合计 %d 行；库存为负的 %d 条" % (tot, neg))
con.close()
