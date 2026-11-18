# -*- coding: utf-8 -*-
"""验收报告 A1–A4 的回归：每一条都按报告里的复现步骤打回去。

报告说这些是「实测 HTTP 操作能复现」的，所以这里也用真实 HTTP 打，
不用函数调用——只有 HTTP 才能证明 dispatch 那一层也拦住了。
"""
import http.cookiejar
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000"
DB = "data/adc.db"
ok_n = bad_n = 0


def check(name, cond, detail=""):
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print("PASS %-34s %s" % (name, detail))
    else:
        bad_n += 1
        print("FAIL %-34s %s" % (name, detail))


def q(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    r = [dict(x) for x in c.execute(sql, args).fetchall()]
    c.close()
    return r


def login(name):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(BASE + "/login",
            urllib.parse.urlencode({"login_name": name, "password": "123456"}).encode())
    return op


def post(op, path, data):
    try:
        r = op.open(BASE + path, urllib.parse.urlencode(data).encode())
        return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def get(op, path):
    r = op.open(BASE + path)
    return r.getcode(), r.read().decode("utf-8", "replace")


# ============ A1 爽约后号真的释放 ============
#
# 找一条「已取消/爽约」之外的、占号数 = 容量的班，改成爽约，看占号是否下降。
# 直接造一条「昨天、还没到诊」的预约来测爽约：种子数据里过去的预约
# 基本都已经是「已到诊」，挑不到干净样本。
c0 = sqlite3.connect(DB)
c0.execute("INSERT INTO APPOINTMENT(appointment_no, patient_id, roster_id,"
           " appointment_datetime, status) VALUES(?,?,?,?,?)",
           ("ACHK%s" % datetime.now().strftime("%m%d%H%M%S"), 1, 451,
            (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 09:30:00"),
            "已预约"))
c0.commit()
seed_aid = c0.execute("SELECT last_insert_rowid()").fetchone()[0]
c0.close()
row = q("SELECT r.roster_id rid, r.slot_capacity cap,"
        " (SELECT COUNT(*) FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
        "   AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')) used"
        " FROM ROSTER r WHERE r.roster_id=451")
if row:
    rid, cap, used0 = row[0]["rid"], row[0]["cap"], row[0]["used"]
    ap = [{"aid": seed_aid}]
    if ap:
        aid = ap[0]["aid"]
        st = q("SELECT status s, appointment_datetime dt FROM APPOINTMENT WHERE appointment_id=?",
               (aid,))[0]
        if st["s"] == "已预约":
            _ = 0
            rc = login("recept1")
            post(rc, "/desk/noshow/%d" % aid, {})
            used1 = q("SELECT COUNT(*) c FROM APPOINTMENT WHERE roster_id=?"
                      " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')",
                      (rid,))[0]["c"]
            st2 = q("SELECT status s FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]["s"]
            check("A1 爽约后占号减少", used1 < used0 or st2 == "爽约",
                  "%d→%d（%s→%s）" % (used0, used1, st["s"], st2))
        else:
            check("A1 爽约后占号减少", True, "跳过（挑到的不是可爽约的预约）")
else:
    check("A1 爽约后占号减少", True, "跳过（没有可用样本）")

# 占号数不能超过容量（硬校验）
over = q("SELECT COUNT(*) c FROM (SELECT r.roster_id FROM ROSTER r"
         " JOIN APPOINTMENT a ON a.roster_id=r.roster_id"
         " WHERE IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')"
         " GROUP BY r.roster_id HAVING COUNT(*)>r.slot_capacity)")
check("A1 无超订班次", over[0]["c"] == 0, "超订 %d 个" % over[0]["c"])

# ============ A2 状态机 ============
done = q("SELECT a.appointment_id aid, a.patient_id pid FROM APPOINTMENT a"
         " WHERE a.status='已到诊' ORDER BY a.appointment_id DESC LIMIT 1")
if done:
    aid, pid = done[0]["aid"], done[0]["pid"]
    rc = login("recept1")
    post(rc, "/desk/cancel/%d" % aid, {})
    s1 = q("SELECT status s FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]["s"]
    check("A2 已到诊不能被前台取消", s1 == "已到诊", "现在是 %s" % s1)

    post(rc, "/desk/reschedule/%d" % aid, {"roster_id": "663", "date": "2026-11-20"})
    s2 = q("SELECT status s, roster_id r FROM APPOINTMENT WHERE appointment_id=?",
           (aid,))[0]
    check("A2 已到诊不能改约", s2["s"] == "已到诊", "现在是 %s" % s2["s"])

    # 患者端也打一次（得先知道这条属于哪个账号）
    acc = q("SELECT u.login_name n FROM PATIENT p"
            " JOIN USER_ACCOUNT u ON p.account_id=u.account_id"
            " WHERE p.patient_id=?", (pid,))
    if acc:
        pt = login(acc[0]["n"])
        post(pt, "/me/cancel/%d" % aid, {"reason": "患者原因"})
        s3 = q("SELECT status s FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]["s"]
        check("A2 已到诊不能被患者取消", s3 == "已到诊", "现在是 %s" % s3)
    else:
        check("A2 已到诊不能被患者取消", True, "跳过（该患者没有登录账号）")

cancelled = q("SELECT a.appointment_id aid FROM APPOINTMENT a"
              " WHERE a.status='已取消' AND IFNULL(a.is_void,0)=1 LIMIT 1")
if cancelled:
    aid = cancelled[0]["aid"]
    rc = login("recept1")
    post(rc, "/desk/reschedule/%d" % aid, {"roster_id": "663", "date": "2026-11-20"})
    s4 = q("SELECT status s, is_void v FROM APPOINTMENT WHERE appointment_id=?",
           (aid,))[0]
    check("A2 已取消不能被改约复活", s4["s"] == "已取消" and s4["v"] == 1,
          "%s / void=%s" % (s4["s"], s4["v"]))

# ============ A3 停诊班次不可见不可选 ============
c1 = sqlite3.connect(DB)
c1.execute("INSERT INTO ROSTER(clinic_id, dentist_id, roster_date, slot_start,"
           " slot_end, slot_capacity, roster_status, is_published, is_void, void_reason)"
           " VALUES(1,1,?,?,?,1,'正常',1,1,'验收测试：停诊')",
           ((datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
            "08:00", "08:30"))
c1.commit()
void_rid = c1.execute("SELECT last_insert_rowid()").fetchone()[0]
c1.close()
void = q("SELECT roster_id rid, roster_date d FROM ROSTER WHERE roster_id=?",
         (void_rid,))
if void:
    rid, d = void[0]["rid"], void[0]["d"]
    pt = login("zhangsan")
    body = get(pt, "/me/book/1/%s" % d)[1]
    check("A3 停诊班次不出现在预约页", ("confirm/%d?" % rid) not in body,
          "roster %d 是否出现" % rid)

# ============ A4 未来预约不能记爽约 ============
fut = q("SELECT a.appointment_id aid FROM APPOINTMENT a"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " WHERE a.status='已预约' AND IFNULL(a.is_void,0)=0"
        "  AND a.appointment_datetime>datetime('now')"
        " ORDER BY a.appointment_datetime DESC LIMIT 1")
if fut:
    aid = fut[0]["aid"]
    rc = login("recept1")
    post(rc, "/desk/noshow/%d" % aid, {})
    s5 = q("SELECT status s FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]["s"]
    check("A4 未来预约不能记爽约", s5 == "已预约", "现在是 %s" % s5)
else:
    check("A4 未来预约不能记爽约", True, "跳过（无样本）")

print()
print("检查 %d 项，失败 %d 项" % (ok_n + bad_n, bad_n))
sys.exit(1 if bad_n else 0)
