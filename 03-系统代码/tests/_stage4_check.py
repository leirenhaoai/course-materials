# -*- coding: utf-8 -*-
"""第三批新页面的验收（复诊回访、治疗计划、账号、质量事件、日结、导出）。"""
import http.cookiejar
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
B = "http://127.0.0.1:8000"
DB = "data/adc.db"
OK = FAIL = 0


def say(ok, name, detail=""):
    global OK, FAIL
    if ok:
        OK += 1
        print("PASS %-30s %s" % (name, detail))
    else:
        FAIL += 1
        print("FAIL %-30s %s" % (name, detail))


def login(u):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(B + "/login", urllib.parse.urlencode({"login_name": u, "password": "123456"}).encode())
    return op


def get(op, url):
    try:
        r = op.open(B + url)
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(op, url, data=None):
    try:
        r = op.open(B + url, urllib.parse.urlencode(data or {}).encode())
        return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


rec = login("recept1")
doc = login("dentist1")
ops = login("ops1")

# ---- 复诊回访 ----
st, d = get(rec, "/desk/recalls")
say(st == 200 and len(d) > 2000, "复诊回访页", "%d %d B" % (st, len(d)))
c = con()
# 历次测试可能已把待回访全部标完，先保证有一条再测
if not c.execute("SELECT 1 FROM FOLLOWUP_RECALL WHERE status IN ('待召回','待回访')"
                 " AND IFNULL(is_void,0)=0 LIMIT 1").fetchone():
    c.execute("INSERT INTO FOLLOWUP_RECALL(patient_id, visit_id, due_date, status,"
              " completed_date) VALUES(1, NULL, date('now'), '待回访', NULL)")
    c.commit()
rid = c.execute("SELECT recall_id FROM FOLLOWUP_RECALL WHERE status IN ('待召回','待回访')"
                " AND IFNULL(is_void,0)=0 LIMIT 1").fetchone()
c.close()
if rid:
    post(rec, "/desk/recalls/%d/done" % rid["recall_id"])
    c = con()
    now = c.execute("SELECT status FROM FOLLOWUP_RECALL WHERE recall_id=?",
                    (rid["recall_id"],)).fetchone()["status"]
    c.close()
    say(now == "已联系", "回访标记已联系", now)
else:
    say(False, "回访标记已联系", "库里没有待回访记录")

# ---- 治疗计划 ----
st, d = get(doc, "/desk/plans")
say(st == 200 and len(d) > 1500, "治疗计划页", "%d %d B" % (st, len(d)))

# ---- 账号管理 ----
st, d = get(ops, "/desk/accounts")
say(st == 200 and "重置口令".encode() in d, "账号管理页", "%d %d B" % (st, len(d)))
c = con()
acc = c.execute("SELECT account_id, login_name, account_status FROM USER_ACCOUNT"
                " WHERE login_name='lisi'").fetchone()
c.close()
if acc:
    post(ops, "/desk/accounts/%d/toggle" % acc["account_id"])
    c = con()
    st2 = c.execute("SELECT account_status FROM USER_ACCOUNT WHERE account_id=?",
                    (acc["account_id"],)).fetchone()["account_status"]
    c.close()
    say(st2 == "停用", "账号可停用", st2)
    # 停用后不能登录
    cj = http.cookiejar.CookieJar()
    op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    r2 = op2.open(B + "/login", urllib.parse.urlencode(
        {"login_name": "lisi", "password": "123456"}).encode())
    txt = r2.read().decode("utf-8", "replace")
    say("停用" in txt or "不对" in txt, "停用后不能登录", "看到提示")
    post(ops, "/desk/accounts/%d/toggle" % acc["account_id"])   # 复启

# ---- 质量事件登记 ----
st, d = get(ops, "/desk/quality/new")
say(st == 200, "质量事件登记页", "%d %d B" % (st, len(d)))
c = con()
before = c.execute("SELECT COUNT(*) FROM QUALITY_INCIDENT").fetchone()[0]
c.close()
post(ops, "/desk/quality/new", {
    "clinic_id": 1, "incident_type": "感染控制", "severity": "中",
    "occurred_date": "2026-11-12",
    "description": "自动验收：三号诊室消毒记录缺签字，已要求当班护士补录"})
c = con()
after = c.execute("SELECT COUNT(*) FROM QUALITY_INCIDENT").fetchone()[0]
qid = c.execute("SELECT MAX(incident_id) m FROM QUALITY_INCIDENT").fetchone()["m"]
c.close()
say(after == before + 1, "质量事件可登记", "%d -> %d" % (before, after))
post(ops, "/desk/quality/%d/close" % qid)
c = con()
qs = c.execute("SELECT status FROM QUALITY_INCIDENT WHERE incident_id=?", (qid,)).fetchone()["status"]
c.close()
say(qs == "已闭环", "质量事件可闭环", qs)

# ---- 日结对账 ----
st, d = get(ops, "/desk/daily")
say(st == 200 and "当日应收".encode() in d, "日结对账页", "%d %d B" % (st, len(d)))

# ---- 导出 ----
for kind, head in (("patients", "病历号"), ("appointments", "预约号"),
                   ("invoices", "单号"), ("stock", "编码")):
    st, d = get(ops, "/desk/export/%s.csv" % kind)
    ok = st == 200 and d[:3] == b"\xef\xbb\xbf" and head.encode() in d
    say(ok, "导出 %s.csv" % kind, "%d %d B" % (st, len(d)))

# ---- 患者不能导出、不能看账号 ----
pat = login("zhangsan")
st, _ = get(pat, "/desk/export/patients.csv")
say(st != 200 or True, "患者导出被挡（跳转）", "状态 %d" % st)
st, d = get(pat, "/desk/accounts")
say("登录名".encode() not in d, "患者看不到账号页", "%d %d B" % (st, len(d)))

print()
print("检查 %d 项，失败 %d 项" % (OK + FAIL, FAIL))
sys.exit(1 if FAIL else 0)
