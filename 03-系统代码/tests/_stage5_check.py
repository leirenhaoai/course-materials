# -*- coding: utf-8 -*-
"""并发复测：A1 到诊、A2 开单，两线程同时打同一个 URL。

跑法：先确认服务在 8000 跑着，然后 `python _stage5_check.py`。
"""
import http.cookiejar
import sqlite3
import sys
import threading
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
B = "http://127.0.0.1:8000"
DB = r"D:\系统分析与设计作业\code\data\adc.db"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS %s" % name)
    else:
        fail += 1
        print("FAIL %s  %s" % (name, detail))


def login(name, pw="123456"):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(B + "/login", urllib.parse.urlencode(
        {"login_name": name, "password": pw}).encode())
    return op


def post_twice(urls):
    """两个线程同时 POST 不同（或相同）URL，返回各自的 (最终URL, 正文)。"""
    out = []

    def run(op, u):
        try:
            r = op.open(u, b"")
            out.append((urllib.parse.unquote(r.geturl()), r.read().decode("utf-8", "replace")))
        except Exception as e:                      # noqa: BLE001
            out.append(("EXC", str(e)))

    ts = [threading.Thread(target=run, args=(o, u)) for o, u in urls]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

# ---------- A1 并发到诊 ----------
row = db.execute(
    "SELECT a.appointment_id FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
    " WHERE a.status='已预约' AND IFNULL(a.is_void,0)=0 AND r.clinic_id=1"
    "   AND a.appointment_id NOT IN (SELECT IFNULL(appointment_id,-1) FROM VISIT)"
    "   AND r.roster_date<=date('now') LIMIT 1").fetchone()
if not row:
    # 库里已经没有「今天及以前、还没有就诊记录」的预约了（被历次测试消耗光），
    # 自己插一条今天的再测——不能因为数据用完就判功能失败。
    r0 = db.execute("SELECT roster_id, clinic_id, dentist_id FROM ROSTER"
                    " WHERE roster_date=date('now') AND IFNULL(is_void,0)=0"
                    "   AND IFNULL(is_published,1)=1 ORDER BY roster_id LIMIT 1").fetchone()
    p0 = db.execute("SELECT patient_id FROM PATIENT ORDER BY patient_id LIMIT 1").fetchone()
    if r0 and p0:
        db.execute("INSERT INTO APPOINTMENT(appointment_no, patient_id, roster_id,"
                   " appointment_datetime, status, visit_reason)"
                   " VALUES(?,?,?,?,?,?)",
                   ("AS5%05d" % (int(__import__("time").time()) % 100000),
                    p0["patient_id"], r0["roster_id"],
                    __import__("datetime").date.today().isoformat() + " 09:00",
                    "已预约", "并发到诊测试"))
        db.commit()
        row = db.execute("SELECT appointment_id FROM APPOINTMENT WHERE appointment_no"
                         " LIKE 'AS5%' ORDER BY appointment_id DESC LIMIT 1").fetchone()
if not row:
    check("A1 并发到诊", False, "找不到可测的预约，也无法自造")
else:
    aid = row["appointment_id"]
    op1, op2 = login("recept1"), login("recept1")
    url = "%s/desk/checkin/%d" % (B, aid)
    res = post_twice([(op1, url), (op2, url)])
    n = db.execute("SELECT COUNT(*) FROM VISIT WHERE appointment_id=?", (aid,)).fetchone()[0]
    check("A1 并发到诊只产生一条 VISIT", n == 1,
          "appointment=%s 实际 VISIT=%d；返回 %s" % (aid, n, [r[0][-30:] for r in res]))
    check("A1 另一线程收到提示而不是 500",
          any("EXC" not in r[0] for r in res) and not any(r[0] == "EXC" for r in res),
          str([r[0][-40:] for r in res]))

# ---------- A2 并发开单 ----------
row = db.execute(
    "SELECT v.visit_id FROM VISIT v"
    " WHERE v.visit_id IN (SELECT visit_id FROM TREATMENT_ITEM)"
    "   AND v.visit_id NOT IN (SELECT visit_id FROM INVOICE WHERE IFNULL(is_void,0)=0)"
    " LIMIT 1").fetchone()
if not row:
    # 演示库里的就诊基本都开过单了，临时造一条「有项目、还没开单」的就诊。
    # 用固定前缀便于回收，跑完删掉。
    db.executescript("""
        DELETE FROM INVOICE_LINE WHERE invoice_id IN (SELECT invoice_id FROM INVOICE WHERE visit_id = 990001);
        DELETE FROM INVOICE WHERE visit_id = 990001;
        DELETE FROM TREATMENT_ITEM WHERE visit_id = 990001;
        DELETE FROM VISIT WHERE visit_id = 990001;
    """)
    db.execute("INSERT INTO VISIT(visit_id, visit_no, clinic_id, visit_datetime, treated)"
               " VALUES(990001, 95001, 1, '2026-11-12 09:00:00', 0)")
    db.execute("INSERT INTO TREATMENT_ITEM(visit_id, line_no, catalog_id, dentist_id,"
               " standard_units, standard_unit_price, agreed_price, added_during_visit)"
               " VALUES(990001, 1, 1, 1, 2, 100, 100, 0)")
    db.commit()
    row = {"visit_id": 990001}
if not row:
    check("A2 并发开单", False, "找不到可测的就诊")
else:
    vid = row["visit_id"]
    op1, op2 = login("recept1"), login("recept1")
    url = "%s/desk/invoice/%d/create" % (B, vid)
    res = post_twice([(op1, url), (op2, url)])
    invs = db.execute("SELECT invoice_id, invoice_no FROM INVOICE WHERE visit_id=?"
                      " AND IFNULL(is_void,0)=0", (vid,)).fetchall()
    check("A2 并发开单只产生一张单", len(invs) == 1,
          "visit=%s 实际 %d 张：%s" % (vid, len(invs), [dict(i) for i in invs]))
    if len(invs) == 1:
        lines = db.execute("SELECT IFNULL(SUM(line_subtotal),0) s FROM INVOICE_LINE"
                           " WHERE invoice_id=?", (invs[0]["invoice_id"],)).fetchone()["s"]
        items = db.execute("SELECT IFNULL(SUM(IFNULL(agreed_price, standard_unit_price)"
                           " * standard_units),0) s FROM TREATMENT_ITEM WHERE visit_id=?",
                           (vid,)).fetchone()["s"]
        check("A2 应收没有翻倍", abs(lines - items) < 0.01,
              "明细 %s vs 项目 %s" % (lines, items))

# ---------- 单号唯一性 ----------
r = db.execute("SELECT invoice_no, COUNT(*) n FROM INVOICE WHERE IFNULL(is_void,0)=0"
               " GROUP BY invoice_no HAVING n>1").fetchall()
check("全库没有重号结算单", not r, str([dict(x) for x in r]))

db.close()

# 收尾：删掉本次测试造的预约与就诊，避免把排班容量顶穿影响后续用例
_c = sqlite3.connect(DB)
for _r in _c.execute("SELECT appointment_id FROM APPOINTMENT"
                     " WHERE appointment_no LIKE 'AS%' OR appointment_no LIKE 'AE2E%'").fetchall():
    _aid = _r[0]
    for _v in _c.execute("SELECT visit_id FROM VISIT WHERE appointment_id=?", (_aid,)).fetchall():
        _vt = _v[0]
        _c.execute("DELETE FROM INVOICE_LINE WHERE invoice_id IN"
                   " (SELECT invoice_id FROM INVOICE WHERE visit_id=?)", (_vt,))
        _c.execute("DELETE FROM PAYMENT WHERE invoice_id IN"
                   " (SELECT invoice_id FROM INVOICE WHERE visit_id=?)", (_vt,))
        _c.execute("DELETE FROM INVOICE WHERE visit_id=?", (_vt,))
        _c.execute("DELETE FROM TREATMENT_ITEM WHERE visit_id=?", (_vt,))
        _c.execute("DELETE FROM VISIT WHERE visit_id=?", (_vt,))
    _c.execute("DELETE FROM APPOINTMENT WHERE appointment_id=?", (_aid,))
_c.commit()
_c.close()


print("\n检查 %d 项，失败 %d 项" % (ok + fail, fail))
sys.exit(1 if fail else 0)
