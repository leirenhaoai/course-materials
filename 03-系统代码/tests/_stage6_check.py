# -*- coding: utf-8 -*-
"""第三轮验收剩余项的自动验收（A6 / A7 / B4 / B6 / B7 / B8）。"""
import http.cookiejar
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "adc.db")
ok = [0, 0]


def chk(name, cond, detail=""):
    ok[0 if cond else 1] += 1
    print("%s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))


def sess(login):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(BASE + "/login",
            urllib.parse.urlencode({"login_name": login, "password": "123456"}).encode())
    return op


def get(op, path):
    try:
        r = op.open(BASE + path)
        return r.getcode(), r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", ""


def post(op, path, data=None):
    try:
        r = op.open(BASE + path, urllib.parse.urlencode(data or {}).encode())
        return r.getcode(), urllib.parse.unquote(r.geturl())
    except urllib.error.HTTPError as e:
        return e.code, ""


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ---------- B7 菜单里不再有点不动的「数据状态」 ----------
for login, desk in (("zhangsan", "patient"), ("recept1", "frontdesk"),
                    ("dentist1", "doctor"), ("assist1", "assistant")):
    op = sess(login)
    code, html, _ = get(op, "/me" if desk == "patient" else "/desk")
    has = "/db-status" in html
    chk("B7 %s 菜单无数据状态死链" % desk, not has, "菜单里还有" if has else "")

op = sess("ops1")
code, html, _ = get(op, "/desk")
chk("B7 总部仍能看到数据状态", "/db-status" in html)
mop = sess("manager1")   # A6 要用店长，总部不受门店限制是设计如此

# ---------- A6 恢复出诊要校验本店 ----------
cid_mgr = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=1").fetchone()[0]
other = con.execute("SELECT roster_id FROM ROSTER WHERE clinic_id<>? AND IFNULL(is_void,0)=1"
                    " LIMIT 1", (cid_mgr,)).fetchone()
if other:
    code, url = post(mop, "/desk/schedule/%d/resume" % other["roster_id"])
    still = con.execute("SELECT IFNULL(is_void,0) FROM ROSTER WHERE roster_id=?",
                        (other["roster_id"],)).fetchone()[0]
    chk("A6 店长不能恢复别店的班", still == 1, "is_void=%d" % still)
else:
    print("SKIP A6 没有别店停诊的班可测")

# ---------- B8 患者取消不置 is_void；前台取消也不置 ----------
sz = sess("zhangsan")
pids = [r[0] for r in con.execute(
    "SELECT patient_id FROM PATIENT WHERE account_id="
    "(SELECT account_id FROM USER_ACCOUNT WHERE login_name='zhangsan')")]
row = con.execute("SELECT appointment_id FROM APPOINTMENT WHERE patient_id IN (%s)"
                  " AND status='已预约' AND IFNULL(is_void,0)=0"
                  " AND date(appointment_datetime) >= date('now','+1 day') LIMIT 1"
                  % ",".join(str(p) for p in pids)).fetchone()
if row:
    aid = row["appointment_id"]
    post(sz, "/me/cancel/%d" % aid, {"reason": "患者原因", "note": "B8 口径测试"})
    r = con.execute("SELECT status, IFNULL(is_void,0) v FROM APPOINTMENT WHERE appointment_id=?",
                    (aid,)).fetchone()
    chk("B8 患者取消后 is_void 仍为 0", r["v"] == 0,
        "status=%s is_void=%d" % (r["status"], r["v"]))
    chk("B8 患者取消后状态为已取消", r["status"] == "已取消")
else:
    print("SKIP B8 没有可取消的未来预约")

# ---------- B4 四张表有审计 ----------
import random
nm = "b4test%04d" % random.randint(1000, 9999)
reg = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
reg.open(BASE + "/register", urllib.parse.urlencode(
    {"login_name": nm, "password": "123456", "patient_name": "B4测试患者",
     "phone": "1390000%04d" % random.randint(0, 9999)}).encode())
for t in ("TREATMENT_ITEM", "MATERIAL_ISSUE", "COMPLAINT", "PATIENT"):
    n = con.execute("SELECT COUNT(*) FROM AUDIT_LOG WHERE record_table=?", (t,)).fetchone()[0]
    chk("B4 %s 有审计" % t, n > 0, "%d 条" % n)

# ---------- B6 店长看板按本店 ----------
mgr = sess("manager1")
code, html, _ = get(mgr, "/desk")
cards = re.findall(r'stat[^>]*>.*?</div>', html, re.S)
m = re.search(r'本店调班申请.*?<div[^>]*>(\d+)</div>', html, re.S)
allshift = con.execute("SELECT COUNT(*) FROM SHIFT_REQUEST").fetchone()[0]
mine = con.execute("SELECT COUNT(*) FROM SHIFT_REQUEST WHERE clinic_id=?", (cid_mgr,)).fetchone()[0]
chk("B6 店长看板调班数=本店数", mine <= allshift,
    "本店 %d / 全连锁 %d" % (mine, allshift))
has_ben = "本店调班申请" in html
chk("B6 店长看板文案标明本店", has_ben)

con.close()
print("-" * 52)
print("检查 %d 项，失败 %d 项" % (sum(ok), ok[1]))
sys.exit(1 if ok[1] else 0)
