# -*- coding: utf-8 -*-
"""采购到付款链路端到端：建单 → 收货入库 → 对账 → 挂应付 → 付款。"""
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


def login(name):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(B + "/login", urllib.parse.urlencode(
        {"login_name": name, "password": "123456"}).encode())
    return op


def page(op, url):
    return op.open(B + url).read().decode("utf-8", "replace")


def post(op, url, data):
    r = op.open(B + url, urllib.parse.urlencode(data).encode())
    return urllib.parse.unquote(r.geturl())


ok = fail = 0


def chk(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS %-28s %s" % (name, extra))
    else:
        fail += 1
        print("FAIL %-28s %s" % (name, extra))


hq = login("ops1")
for u in ("/desk/po", "/desk/po/new", "/desk/statements", "/desk/statements/new",
          "/desk/payables", "/desk/stock"):
    try:
        h = page(hq, u)
        chk("页面 " + u, len(h) > 800, "%d B" % len(h))
    except Exception as e:
        chk("页面 " + u, False, str(e))

# 1. 建采购单
n_po = db.execute("SELECT COUNT(*) FROM PURCHASE_ORDER").fetchone()[0]
mat = [r["material_code"] for r in db.execute(
    "SELECT material_code FROM MATERIAL ORDER BY material_id LIMIT 2")]
sup = db.execute("SELECT supplier_id FROM SUPPLIER ORDER BY supplier_id LIMIT 1").fetchone()[0]
term = db.execute("SELECT term_id FROM SETTLEMENT_TERM ORDER BY term_id LIMIT 1").fetchone()[0]
lines = "\r\n".join("%s 6 25.5" % c for c in mat)
u = post(hq, "/desk/po/new", {"supplier_id": sup, "term_id": term, "clinic_id": 1,
                              "expected_date": "2026-12-01", "lines": lines})
chk("建采购单", db.execute("SELECT COUNT(*) FROM PURCHASE_ORDER").fetchone()[0] == n_po + 1,
    u.split("?")[-1][:40])
po_id = db.execute("SELECT MAX(po_id) FROM PURCHASE_ORDER").fetchone()[0]
n_line = db.execute("SELECT COUNT(*) FROM PURCHASE_ORDER_LINE WHERE po_id=?",
                    (po_id,)).fetchone()[0]
chk("采购单有明细", n_line == 2, "%d 行" % n_line)

# 2. 收货入库
led0 = db.execute("SELECT IFNULL(SUM(on_hand_qty),0) FROM STOCK_LEDGER").fetchone()[0]
mv0 = db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0]
u = post(hq, "/desk/po/%d/receive" % po_id, {})
st = db.execute("SELECT status FROM PURCHASE_ORDER WHERE po_id=?", (po_id,)).fetchone()[0]
chk("采购单转已入库", st == "已入库", st)
led1 = db.execute("SELECT IFNULL(SUM(on_hand_qty),0) FROM STOCK_LEDGER").fetchone()[0]
mv1 = db.execute("SELECT COUNT(*) FROM STOCK_MOVEMENT").fetchone()[0]
chk("库存增加 12", led1 - led0 == 12, "%s → %s" % (led0, led1))
chk("入库写了 2 条流水", mv1 - mv0 == 2, "%d → %d" % (mv0, mv1))
chk("生成了批次", db.execute("SELECT COUNT(*) FROM MATERIAL_BATCH").fetchone()[0] >= 26,
    "%d 条" % db.execute("SELECT COUNT(*) FROM MATERIAL_BATCH").fetchone()[0])
# 重复收货要被拦
u2 = post(hq, "/desk/po/%d/receive" % po_id, {})
chk("重复收货被拦", "err=" in u2 or "已经" in u2, u2[-30:])

# 3. 对账
fin = login("finance1")
n_st = db.execute("SELECT COUNT(*) FROM STATEMENT").fetchone()[0]
u = post(fin, "/desk/statements/new",
         {"supplier_id": sup, "d0": "2026-01-01", "d1": "2026-12-31"})
n_st2 = db.execute("SELECT COUNT(*) FROM STATEMENT").fetchone()[0]
chk("生成对账单", n_st2 == n_st + 1, u.split("?")[-1][:40])
stid = db.execute("SELECT MAX(statement_id) FROM STATEMENT").fetchone()[0]
amt = db.execute("SELECT IFNULL(SUM(amount),0) FROM STATEMENT_LINE WHERE statement_id=?",
                 (stid,)).fetchone()[0]
chk("对账金额 > 0", amt > 0, "%s 元" % amt)

# 4. 挂应付
n_ap = db.execute("SELECT COUNT(*) FROM ACCOUNT_PAYABLE").fetchone()[0]
u = post(fin, "/desk/statements/%d/payable" % stid, {})
chk("挂应付", db.execute("SELECT COUNT(*) FROM ACCOUNT_PAYABLE").fetchone()[0] == n_ap + 1,
    u.split("?")[-1][:30])
apid = db.execute("SELECT MAX(payable_id) FROM ACCOUNT_PAYABLE").fetchone()[0]
u2 = post(fin, "/desk/statements/%d/payable" % stid, {})
chk("重复挂账被拦", "已经" in u2 or "err=" in u2, u2[-24:])

# 5. 付款
due = db.execute("SELECT payable_amount FROM ACCOUNT_PAYABLE WHERE payable_id=?",
                 (apid,)).fetchone()[0]
u = post(fin, "/desk/payables/%d/pay" % apid, {"amount": str(due), "method": "银行转账"})
paid = db.execute("SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD WHERE payable_id=?",
                  (apid,)).fetchone()[0]
chk("付款落库", abs(paid - due) < 0.01, "付 %s / 应付 %s" % (paid, due))
st2 = db.execute("SELECT status FROM ACCOUNT_PAYABLE WHERE payable_id=?",
                 (apid,)).fetchone()[0]
chk("应付转已付款", st2 == "已付款", st2)
# 超付要被拦
u2 = post(fin, "/desk/payables/%d/pay" % apid, {"amount": "1", "method": "现金"})
chk("超付被拦", "err=" in u2 or "已结清" in u2 or "超过" in u2, u2[-24:])

# 6. 权限
pat = login("zhangsan")
try:
    h = page(pat, "/desk/po")
    chk("患者看不到采购单", "/login" in h or "我的" in h, h[:40])
except Exception:
    chk("患者看不到采购单", True, "被拦")

# 收尾：把本轮自己造的对账单/应付作废，否则下次跑会被「同供应商同期间
# 只能对一次账」的查重拦住——这条查重本身是对的，测试要自己收拾干净。
db.execute("UPDATE ACCOUNT_PAYABLE SET is_void=1, void_reason='stage7 测试数据'"
           " WHERE statement_id=? AND IFNULL(is_void,0)=0", (stid,))
db.execute("UPDATE STATEMENT SET is_void=1, void_reason='stage7 测试数据'"
           " WHERE statement_id=? AND IFNULL(is_void,0)=0", (stid,))
db.commit()

print("\n检查 %d 项，失败 %d 项" % (ok + fail, fail))
sys.exit(1 if fail else 0)
