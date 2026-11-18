# -*- coding: utf-8 -*-
"""库存三块能力实测：批次与效期、盘点、调拨。"""
import http.cookiejar
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
B = "http://127.0.0.1:8000"
ROOT = r"D:\系统分析与设计作业\code"
db = sqlite3.connect(ROOT + r"\data\adc.db")
db.row_factory = sqlite3.Row
ok = fail = 0


def chk(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS %-26s %s" % (name, extra))
    else:
        fail += 1
        print("FAIL %-26s %s" % (name, extra))


def login(n):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(B + "/login", urllib.parse.urlencode(
        {"login_name": n, "password": "123456"}).encode())
    return op


def page(op, u):
    return op.open(B + u).read().decode("utf-8", "replace")


def post(op, u, d):
    return urllib.parse.unquote(op.open(B + u, urllib.parse.urlencode(d).encode()).geturl())


hq = login("ops1")

# 1. 批次与效期（先造一个 20 天后到期的批次，否则种子数据全是 +730 天，测不出预警）
mid0 = db.execute("SELECT material_id FROM MATERIAL ORDER BY material_id LIMIT 1").fetchone()[0]
db.execute("INSERT INTO MATERIAL_BATCH(material_id, batch_serial_no, expiry_date,"
           " purchase_unit_price) VALUES(?,?,date('now','+20 day'),12.5)",
           (mid0, "TEST-NEAR-EXP"))
db.commit()
h = page(hq, "/desk/stock/batches")
chk("批次页可开", len(h) > 1000, "%d B" % len(h))
n_batch = db.execute("SELECT COUNT(*) FROM MATERIAL_BATCH").fetchone()[0]
chk("列出全部批次", h.count("<tr>") >= n_batch, "%d 行 / 库 %d 条" % (h.count("<tr>"), n_batch))
chk("标出近效期", "天后到期" in h, "TEST-NEAR-EXP" if "TEST-NEAR-EXP" in h else "未显示")
db.execute("DELETE FROM MATERIAL_BATCH WHERE batch_serial_no='TEST-NEAR-EXP'")
db.commit()

# 2. 盘点：把某店某物料调到指定值
row = db.execute(
    "SELECT l.ledger_id, l.clinic_id, l.material_id, IFNULL(l.on_hand_qty,0) q"
    "  FROM STOCK_LEDGER l WHERE IFNULL(l.is_void,0)=0 ORDER BY l.ledger_id LIMIT 1").fetchone()
before = row["q"]
target = before + 7
n_mv = db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0]
u = post(hq, "/desk/stock/count",
         {"clinic_id": row["clinic_id"], "material_id": row["material_id"], "qty": target})
after = db.execute("SELECT on_hand_qty FROM STOCK_LEDGER WHERE ledger_id=?",
                   (row["ledger_id"],)).fetchone()[0]
chk("盘点写入实盘数", abs(after - target) < 0.001, "%s → %s" % (before, after))
chk("盘点写了一条流水",
    db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0] == n_mv + 1,
    u.split("?")[-1][:34])
mv = db.execute("SELECT direction, quantity, source_no FROM STOCK_MOVEMENT"
                " WHERE source_type='盘点' ORDER BY movement_id DESC LIMIT 1").fetchone()
chk("流水方向与差额对上", mv["direction"] == "入库" and abs(mv["quantity"] - 7) < 0.001,
    "%s %s" % (mv["direction"], mv["quantity"]))
chk("盘点单号已发", (mv["source_no"] or "").startswith("PD"), mv["source_no"])
# 数量一致时不写流水
n_mv2 = db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0]
u2 = post(hq, "/desk/stock/count",
          {"clinic_id": row["clinic_id"], "material_id": row["material_id"], "qty": target})
chk("数量一致不写流水",
    db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0] == n_mv2,
    u2.split("?")[-1][:26])
# 负数被拦
u3 = post(hq, "/desk/stock/count",
          {"clinic_id": row["clinic_id"], "material_id": row["material_id"], "qty": -5})
chk("负数实盘被拦", "err=" in u3, u3.split("?")[-1][:24])

# 3. 调拨
cl = [r["clinic_id"] for r in db.execute("SELECT clinic_id FROM CLINIC ORDER BY clinic_id")]
a, b = cl[0], cl[1]
src0 = db.execute("SELECT IFNULL(on_hand_qty,0) FROM STOCK_LEDGER"
                  " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                  (a, row["material_id"])).fetchone()
src0 = src0[0] if src0 else 0
dst0 = db.execute("SELECT IFNULL(on_hand_qty,0) FROM STOCK_LEDGER"
                  " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                  (b, row["material_id"])).fetchone()
dst0 = dst0[0] if dst0 else 0
chk("调出店有货", src0 >= 3, "现货 %s" % src0)
n_mv3 = db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0]
u = post(hq, "/desk/stock/transfer",
         {"from_id": a, "to_id": b, "material_id": row["material_id"], "qty": 3})
src1 = db.execute("SELECT IFNULL(on_hand_qty,0) FROM STOCK_LEDGER"
                  " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                  (a, row["material_id"])).fetchone()[0]
dst1 = db.execute("SELECT IFNULL(on_hand_qty,0) FROM STOCK_LEDGER"
                  " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                  (b, row["material_id"])).fetchone()[0]
chk("调出店 -3", abs((src0 - src1) - 3) < 0.001, "%s → %s" % (src0, src1))
chk("调入店 +3", abs((dst1 - dst0) - 3) < 0.001, "%s → %s" % (dst0, dst1))
chk("一次调拨写两条流水",
    db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0] == n_mv3 + 2,
    u.split("?")[-1][:40])
# 超量被拦
u2 = post(hq, "/desk/stock/transfer",
          {"from_id": a, "to_id": b, "material_id": row["material_id"], "qty": 999999})
chk("超量调拨被拦", "不够" in u2 or "err=" in u2, u2.split("?")[-1][:30])
# 同店被拦
u3 = post(hq, "/desk/stock/transfer",
          {"from_id": a, "to_id": a, "material_id": row["material_id"], "qty": 1})
chk("同店调拨被拦", "同一家" in u3 or "err=" in u3, u3.split("?")[-1][:26])

# 4. 账套 = 流水净额（全库对账）
bad = 0
for led in db.execute("SELECT ledger_id, IFNULL(on_hand_qty,0) q FROM STOCK_LEDGER"
                      " WHERE IFNULL(is_void,0)=0").fetchall():
    # quantity 自带符号（入正出负），直接求和就是账套应有值
    s_ = db.execute("SELECT IFNULL(SUM(quantity),0) FROM STOCK_MOVEMENT"
                    " WHERE ledger_id=?", (led["ledger_id"],)).fetchone()[0]
    if abs(s_ - led["q"]) > 0.01:
        bad += 1
chk("账套与流水净额一致", bad == 0, "不一致 %d 条" % bad)

# 5. 权限
pat = login("zhangsan")
h = page(pat, "/desk/stock/count")
chk("患者进不了盘点", ("/login" in h) or ("我的" in h), h[:26])

print("\n检查 %d 项，失败 %d 项" % (ok + fail, fail))
sys.exit(1 if fail else 0)
