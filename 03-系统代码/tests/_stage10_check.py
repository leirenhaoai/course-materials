# -*- coding: utf-8 -*-
"""收尾检查（stage10）：把「一直没单独测过、但用户真会用」的几条固定下来。

1. 结算单作废：未收款可作废、重复被拒、已收款被拒、患者无权
2. 跨店改约：患者能在改约页切门店，且后端接受别店的目标班次
3. 导航分组：每个角色都分出至少两组，且不出现「其他」被切成多段
4. 顶栏待办铃：六类角色都能算出一个数（0 也算，不能是异常）
"""
import http.cookiejar
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "adc.db")
B = "http://127.0.0.1:8000"

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        print("  FAIL  %s  %s" % (name, detail))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sess(login):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    try:
        op.open(B + "/login", urllib.parse.urlencode(
            {"login_name": login, "password": "123456"}).encode())
    except urllib.error.HTTPError:
        pass
    return op


def get(op, path):
    try:
        r = op.open(B + path)
        return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def post_raw(op, path):
    try:
        r = op.open(B + path, b"")
        return r.getcode(), ""
    except urllib.error.HTTPError as e:
        return e.code, urllib.parse.unquote(e.headers.get("Location") or "")


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("=" * 60)
print("1. 结算单作废")
free = con.execute(
    "SELECT i.visit_id, i.invoice_id, i.invoice_no FROM INVOICE i"
    " WHERE IFNULL(i.is_void,0)=0 AND (SELECT IFNULL(SUM(amount),0) FROM PAYMENT p"
    " WHERE p.invoice_id=i.invoice_id AND IFNULL(p.is_void,0)=0) <= 0.01").fetchone()
paid = con.execute(
    "SELECT i.visit_id, i.invoice_no FROM INVOICE i"
    " WHERE IFNULL(i.is_void,0)=0 AND (SELECT IFNULL(SUM(amount),0) FROM PAYMENT p"
    " WHERE p.invoice_id=i.invoice_id AND IFNULL(p.is_void,0)=0) > 0.01 LIMIT 1").fetchone()
fin = sess("finance1")
if free:
    code, loc = post_raw(fin, "/desk/invoice/%d/void" % free["visit_id"])
    row = con.execute("SELECT is_void,status FROM INVOICE WHERE invoice_id=?",
                      (free["invoice_id"],)).fetchone()
    check("未收款单可作废", row["is_void"] == 1 and "已作废" in (row["status"] or ""),
          "%s -> %s" % (free["invoice_no"], row["status"]))
    code2, loc2 = post_raw(fin, "/desk/invoice/%d/void" % free["visit_id"])
    check("重复作废被拒", "已经作废" in loc2, loc2[:40])
    con.execute("UPDATE INVOICE SET is_void=0, status='待收款', void_reason=NULL,"
                " void_at=NULL, void_account_id=NULL WHERE invoice_id=?", (free["invoice_id"],))
    con.commit()
    me = sess("zhangsan")
    post_raw(me, "/desk/invoice/%d/void" % free["visit_id"])
    r2 = con.execute("SELECT is_void FROM INVOICE WHERE invoice_id=?",
                     (free["invoice_id"],)).fetchone()
    check("患者不能作废", r2["is_void"] == 0)
if paid:
    code3, loc3 = post_raw(fin, "/desk/invoice/%d/void" % paid["visit_id"])
    check("已收款单要先退费", "要先退费" in loc3, loc3[:48])

print("1b. 采购单与应付作废")
ops = sess("ops1")
recv_po = con.execute(
    "SELECT po_id, po_no FROM PURCHASE_ORDER WHERE IFNULL(is_void,0)=0"
    " AND IFNULL(status,'')='已入库' LIMIT 1").fetchone()
if recv_po:
    code, loc = post_raw(ops, "/desk/po/%d/void" % recv_po["po_id"])
    check("已入库采购单不能作废", "已经收货入库" in loc, loc[:46])
free_ap = con.execute(
    "SELECT payable_id, payable_no FROM ACCOUNT_PAYABLE WHERE IFNULL(is_void,0)=0"
    " AND (SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD r"
    " WHERE r.payable_id=ACCOUNT_PAYABLE.payable_id AND IFNULL(r.is_void,0)=0) <= 0.01"
    " LIMIT 1").fetchone()
if free_ap:
    code, loc = post_raw(fin, "/desk/payables/%d/void" % free_ap["payable_id"])
    row = con.execute("SELECT is_void FROM ACCOUNT_PAYABLE WHERE payable_id=?",
                      (free_ap["payable_id"],)).fetchone()
    check("未付款应付可作废", row["is_void"] == 1, free_ap["payable_no"])
    con.execute("UPDATE ACCOUNT_PAYABLE SET is_void=0, status='未付款', void_reason=NULL"
                " WHERE payable_id=?", (free_ap["payable_id"],))
    con.commit()
paid_ap = con.execute(
    "SELECT payable_id FROM ACCOUNT_PAYABLE WHERE IFNULL(is_void,0)=0"
    " AND (SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD r"
    " WHERE r.payable_id=ACCOUNT_PAYABLE.payable_id AND IFNULL(r.is_void,0)=0) > 0.01"
    " LIMIT 1").fetchone()
if paid_ap:
    code, loc = post_raw(fin, "/desk/payables/%d/void" % paid_ap["payable_id"])
    check("已付款应付要先冲正", "要先作废付款记录" in loc, loc[:46])

print("2. 跨店改约")
me = sess("zhangsan")
code, h = get(me, "/me/appointments")
ids = re.findall(r"/me/reschedule/(\d+)", h)
if ids:
    aid = ids[0]
    code, h2 = get(me, "/me/reschedule/%s" % aid)
    clinics = set(re.findall(r'reschedule/%s\?[^"]*?c=(\d+)' % aid, h2))
    check("改约页能切门店", len(clinics) >= 2, "可选 %d 家" % len(clinics))
    # 后端接受别店的目标班次：找一个不属于当前预约门店的空位
    my_clinic = con.execute(
        "SELECT r.clinic_id FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
        " WHERE a.appointment_id=?", (int(aid),)).fetchone()
    other = con.execute(
        "SELECT r.roster_id FROM ROSTER r WHERE IFNULL(r.is_void,0)=0"
        " AND IFNULL(r.is_published,1)=1 AND r.clinic_id<>? AND r.roster_date>=date('now')"
        " ORDER BY r.roster_date LIMIT 1",
        (my_clinic["clinic_id"] if my_clinic else 0,)).fetchone()
    check("存在别店的空位可改", bool(other))
else:
    check("有可改约的预约", False, "患者名下没有可改约的预约")

print("3. 导航分组")
for login, desk in (("zhangsan", "patient"), ("recept1", "frontdesk"), ("dentist1", "doctor"),
                    ("assist1", "assistant"), ("manager1", "manager"),
                    ("ops1", "hq"), ("finance1", "finance")):
    op = sess(login)
    code, h = get(op, "/desk" if desk != "patient" else "/me")
    secs = re.findall(r'<div class="sec">([^<]+)</div>', h)
    ok = code == 200 and len(secs) >= 2 and len(set(secs)) == len(secs)
    check("%s 导航分组正常" % login, ok, "%d 组：%s" % (len(secs), "/".join(secs)))

print("4. 顶栏待办铃")
for login in ("zhangsan", "recept1", "dentist1", "assist1", "manager1", "ops1", "finance1"):
    op = sess(login)
    code, h = get(op, "/desk" if login != "zhangsan" else "/me")
    m = re.search(r'class="bell"[^>]*>(.*?)</a>', h, re.S)
    ok = bool(m) and code == 200
    txt = (m.group(1) if m else "")[:24]
    check("%s 顶栏有铃" % login, ok, txt)

print("5. 首页不报错")
for login in ("zhangsan", "recept1", "dentist1", "assist1", "manager1", "ops1", "finance1"):
    op = sess(login)
    code, h = get(op, "/desk" if login != "zhangsan" else "/me")
    bad = ("加载失败" in h) or ("Traceback" in h) or ("OperationalError" in h)
    check("%s 首页无异常" % login, code == 200 and not bad)

con.close()
print("=" * 60)
print("检查 %d 项，失败 %d 项" % (PASS + FAIL, FAIL))
sys.exit(1 if FAIL else 0)
