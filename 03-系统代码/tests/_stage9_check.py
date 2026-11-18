# -*- coding: utf-8 -*-
"""第五轮 A2/A3/A4/A5 的并发与数值专项。

上一版三处失败全是**测试自己设计错了**，这一版逐个纠正：

- A4 盘点：盘点语义是「把账调成实盘数」，串行执行两次都成功是对的。
  真正要防的是「两条流水、账套只加一次」，所以断言不变量
  `账套 == SUM(流水.quantity)`，而不是「只成功一次」。
- A2 领用：库存充足时串行领两次当然都成功。要构造「只够领一次」的场景。
- A3 收货：路由是 `/desk/po/<id>/receive`，不是 `/receipt`。
"""
import http.cookiejar
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000"
DB = r"D:\系统分析与设计作业\code\data\adc.db"

fails = []


def chk(name, ok, note=""):
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(note)[:70] if note else ""))
    if not ok:
        fails.append(name)


def login(user="ops1", pw="123456"):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(BASE + "/login",
            urllib.parse.urlencode({"login_name": user, "password": pw}).encode())
    return op


def post(op, path, data):
    try:
        r = op.open(BASE + path, urllib.parse.urlencode(data).encode())
        return 200, urllib.parse.unquote(r.geturl())
    except urllib.error.HTTPError as e:
        return e.code, "HTTP%d" % e.code


def db():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    return c


def stock_of(cid, mid):
    c = db()
    v = c.execute("SELECT IFNULL(SUM(on_hand_qty),0) FROM STOCK_LEDGER"
                  " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                  (cid, mid)).fetchone()[0]
    c.close()
    return v or 0


def ledger_sum(lid):
    c = db()
    v = c.execute("SELECT IFNULL(SUM(quantity),0) FROM STOCK_MOVEMENT"
                  " WHERE ledger_id=?", (lid,)).fetchone()[0]
    c.close()
    return v or 0


op = login()

# ------------------------------------------------------------------ A5 NaN
c = db()
row = c.execute("SELECT clinic_id, material_id FROM STOCK_LEDGER"
                " WHERE IFNULL(is_void,0)=0 AND IFNULL(on_hand_qty,0)>20"
                " ORDER BY ledger_id LIMIT 1").fetchone()
cid, mid = row["clinic_id"], row["material_id"]
c.close()
before = stock_of(cid, mid)
_, url = post(op, "/desk/stock/count",
              {"clinic_id": cid, "material_id": mid, "qty": "nan"})
after = stock_of(cid, mid)
chk("A5 盘点 nan 被拦", "err=" in url and after == before, "%s -> %s" % (before, after))

# -------------------------------------------------------------- A4 盘点并发
c = db()
row = c.execute("SELECT ledger_id, clinic_id, material_id, IFNULL(on_hand_qty,0) q"
                " FROM STOCK_LEDGER WHERE IFNULL(is_void,0)=0"
                " AND IFNULL(on_hand_qty,0)>10 ORDER BY ledger_id LIMIT 1").fetchone()
lid, cid2, mid2, q0 = (row["ledger_id"], row["clinic_id"],
                       row["material_id"], row["q"])
c.close()
res = []


def _count(v):
    o = login()
    res.append(post(o, "/desk/stock/count",
                    {"clinic_id": cid2, "material_id": mid2, "qty": v}))


t1 = threading.Thread(target=_count, args=(q0 + 7,))
t2 = threading.Thread(target=_count, args=(q0 + 13,))
t1.start(); t2.start(); t1.join(); t2.join()
q_now = stock_of(cid2, mid2)
s_now = ledger_sum(lid)
chk("A4 盘点并发后账套=流水", abs(q_now - s_now) < 0.001,
    "账套 %s / 流水 %s（起始 %s）" % (q_now, s_now, q0))

# -------------------------------------------------------------- A2 领用并发
# 造一个「只够领一次」的场景：把某账套改成 6，然后两个线程各领 6
c = db()
row = c.execute("SELECT b.batch_id, b.material_id, l.clinic_id, l.ledger_id"
                " FROM MATERIAL_BATCH b JOIN STOCK_LEDGER l"
                "   ON l.material_id=b.material_id"
                " WHERE IFNULL(l.on_hand_qty,0)>=6 AND IFNULL(b.expiry_date,'9999')"
                "   >= date('now') AND l.clinic_id=1 ORDER BY b.batch_id LIMIT 1").fetchone()
if row:
    bid, mid3, cid3, lid3 = row["batch_id"], row["material_id"], row["clinic_id"], row["ledger_id"]
    # 批次现在也要扣余量：先把这一批的入库量补足，否则并发领用会双双被批次校验拦下
    c.execute("UPDATE MATERIAL_BATCH SET received_qty=IFNULL(issued_qty,0)+100000 WHERE batch_id=?", (bid,))
    c.commit()
    # 不去改 on_hand（直接赋值会打破「账套 = SUM(流水)」），
    # 而是按**当前库存全领**：并发各领 have，只有一次能成功。
    have = stock_of(cid3, mid3)
    res2 = []

    def _issue():
        o = login("assist1", "123456")
        res2.append(post(o, "/desk/materials", {"batch_id": bid, "quantity": have}))

    t1 = threading.Thread(target=_issue)
    t2 = threading.Thread(target=_issue)
    t1.start(); t2.start(); t1.join(); t2.join()
    q2 = stock_of(cid3, mid3)
    ok2 = sum(1 for _, u in res2 if "err=" not in u)
    chk("A2 全部库存并发领用只成功一次", ok2 == 1 and abs(q2) < 0.001,
        "起始 %s，成功 %d 次，最终库存 %s" % (have, ok2, q2))
    chk("A2 领用后账套=流水", abs(q2 - ledger_sum(lid3)) < 0.001,
        "账套 %s / 流水 %s" % (q2, ledger_sum(lid3)))
else:
    chk("A2 全部库存并发领用只成功一次", False, "找不到可用批次")

# ------------------------------------------------------------ A3 并发收货
c = db()
po = c.execute("SELECT po_id FROM PURCHASE_ORDER WHERE IFNULL(status,'')<>'已入库'"
               " AND po_id IN (SELECT po_id FROM PURCHASE_ORDER_LINE)"
               " ORDER BY po_id LIMIT 1").fetchone()
c.close()

if not po:
    # 没有未入库的采购单就自己造一张（前几轮测试已经全收掉了）
    m0 = c0 = None
    c1 = db()
    m0 = c1.execute("SELECT material_id FROM MATERIAL"
                    " ORDER BY material_id LIMIT 1").fetchone()
    sid = c1.execute("SELECT supplier_id FROM SUPPLIER LIMIT 1").fetchone()
    if m0 and sid:
        c1.execute("INSERT INTO PURCHASE_ORDER(po_no, supplier_id, order_date,"
                   " expected_date, status) VALUES(?,?,date('now'),date('now','+7 day'),?)",
                   ("PO9%05d" % (__import__("time").time() % 100000),
                    sid["supplier_id"], "已下单"))
        new_id = c1.execute("SELECT last_insert_rowid()").fetchone()[0]
        c1.execute("INSERT INTO PURCHASE_ORDER_LINE(po_id, line_no, material_id,"
                   " quantity, unit_price) VALUES(?,(SELECT IFNULL(MAX(line_no),0)+1"
                   "  FROM PURCHASE_ORDER_LINE WHERE po_id=?),?,?,?)",
                   (new_id, new_id, m0["material_id"], 5, 10))
        c1.commit()
        po = c1.execute("SELECT po_id FROM PURCHASE_ORDER WHERE po_id=?", (new_id,)).fetchone()
    c1.close()

if po:
    n0 = db().execute("SELECT COUNT(*) FROM RECEIPT_NOTE").fetchone()[0]
    po_id = po["po_id"]
    res3 = []

    def _recv():
        o = login()
        res3.append(post(o, "/desk/po/%d/receive" % po_id, {}))

    t1 = threading.Thread(target=_recv)
    t2 = threading.Thread(target=_recv)
    t1.start(); t2.start(); t1.join(); t2.join()

    c = db()
    n1 = c.execute("SELECT COUNT(*) FROM RECEIPT_NOTE").fetchone()[0]
    st = c.execute("SELECT status FROM PURCHASE_ORDER WHERE po_id=?",
                   (po_id,)).fetchone()["status"]
    c.close()
    chk("A3 并发收货只入库一次", n1 - n0 == 1,
        "新增收货单 %d 张，采购单 %s" % (n1 - n0, st))
else:
    chk("A3 并发收货只入库一次", False, "没有未入库的采购单")

print()
print("检查 4 项，失败 %d 项" % len(fails))
sys.exit(1 if fails else 0)
