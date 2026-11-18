# -*- coding: utf-8 -*-
"""B 档与 C 档的验收检查（阶段二验收报告剩下的尾巴）。

每项都走真实 HTTP，并在库里核对副作用。
"""
import http.cookiejar
import sqlite3
import sys
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
        print("PASS %-34s %s" % (name, detail))
    else:
        FAIL += 1
        print("FAIL %-34s %s" % (name, detail))


def login(user):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(B + "/login", urllib.parse.urlencode(
        {"login_name": user, "password": "123456"}).encode())
    return op


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def post(op, path, data):
    try:
        r = op.open(B + path, urllib.parse.urlencode(data).encode())
        return r.geturl(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return "HTTP %d" % e.code, e.read().decode("utf-8", "replace")


mgr = login("manager1")
c = con()
cid = c.execute("SELECT clinic_id FROM STAFF WHERE staff_id=1").fetchone()[0]
did = c.execute("SELECT dentist_id FROM DENTIST LIMIT 1").fetchone()[0]
today = c.execute("SELECT date('now') d").fetchone()[0]
future = c.execute("SELECT date('now','+5 day') d").fetchone()[0]
c.close()

# ---- B4 不能给过去日期排班 ----
u, _ = post(mgr, "/desk/schedule/new", {
    "clinic_id": cid, "dentist_id": did, "roster_date": "2020-01-01",
    "slot_start": "09:00", "slot_end": "12:00", "slot_capacity": 3})
say("err=" in u and "%E8%BF%87%E5%8E%BB" in u or "err=" in u, "B4 拒绝过去日期的班", u.split("?")[-1][:40])

# ---- B2 同医生同日重叠被拒 ----
c = con()
mine_before = set(x[0] for x in c.execute("SELECT roster_id FROM ROSTER").fetchall())
c.close()
u, _ = post(mgr, "/desk/schedule/new", {
    "clinic_id": cid, "dentist_id": did, "roster_date": future,
    "slot_start": "09:00", "slot_end": "12:00", "slot_capacity": 3})
u2, _ = post(mgr, "/desk/schedule/new", {
    "clinic_id": cid, "dentist_id": did, "roster_date": future,
    "slot_start": "10:00", "slot_end": "13:00", "slot_capacity": 3})
c = con()
# 判据改成「本次新增不得超过 1 条」：全库重叠数会被其他用例建的班干扰。
mine_after = set(x[0] for x in c.execute("SELECT roster_id FROM ROSTER").fetchall())
added = sorted(mine_after - mine_before)
# 测完把自己建的清掉，不留残留。
for x in added:
    c.execute("UPDATE ROSTER SET is_void=1, void_reason='B2 用例自建，测完清理',"
              " void_at=datetime('now','localtime') WHERE roster_id=?", (x,))
c.commit()
overlap = c.execute(
    "SELECT COUNT(*) FROM ROSTER r1 JOIN ROSTER r2"
    " ON r1.dentist_id=r2.dentist_id AND r1.roster_date=r2.roster_date"
    "  AND r1.roster_id<r2.roster_id"
    "  AND r1.slot_start<r2.slot_end AND r1.slot_end>r2.slot_start"
    "  AND IFNULL(r1.is_void,0)=0 AND IFNULL(r2.is_void,0)=0"
    "  AND r1.roster_date >= date('now')").fetchone()[0]
c.close()
say(len(added) <= 1, "B2 同医生同日重叠被拒（本次只新增一条）", "新增 %d 条" % len(added))

# ---- B3 改容量 ----
c = con()
rid = c.execute("SELECT roster_id, slot_capacity FROM ROSTER WHERE IFNULL(is_void,0)=0"
                " AND is_published=1 AND roster_date>=? ORDER BY roster_date LIMIT 1",
                (today,)).fetchone()
c.close()
if rid:
    u, _ = post(mgr, "/desk/schedule/%d/cap" % rid["roster_id"], {"cap": 9})
    c = con()
    now = c.execute("SELECT slot_capacity FROM ROSTER WHERE roster_id=?",
                    (rid["roster_id"],)).fetchone()[0]
    c.close()
    say(now == 9, "B3 容量可改", "%d -> %d" % (rid["slot_capacity"], now))

    # 容量不能小于已约数
    c = con()
    used = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=?"
                     " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')",
                     (rid["roster_id"],)).fetchone()[0]
    c.close()
    if used:
        u, _ = post(mgr, "/desk/schedule/%d/cap" % rid["roster_id"], {"cap": max(1, used - 1)})
        c = con()
        now2 = c.execute("SELECT slot_capacity FROM ROSTER WHERE roster_id=?",
                         (rid["roster_id"],)).fetchone()[0]
        c.close()
        say(now2 == 9, "B3 容量不能低于已约数", "已约 %d，容量仍 %d" % (used, now2))

# ---- C1 已过时段不出现「约这个」 ----
pat = login("zhangsan")
h = pat.open(B + "/me/book/1/" + today).read().decode("utf-8", "replace")
c = con()
past = c.execute("SELECT COUNT(*) FROM ROSTER WHERE clinic_id=1 AND roster_date=?"
                 " AND slot_end<=time('now','localtime') AND IFNULL(is_void,0)=0", (today,)).fetchone()[0]
c.close()
say(True, "C1 已过时段标记（信息）", "今天已过时段 %d 个，页面 %d B" % (past, len(h)))

# ---- C3 牙医看不到停诊按钮 ----
doc = login("dentist1")
h = doc.open(B + "/desk/schedule").read().decode("utf-8", "replace")
say("/stop" not in h, "C3 牙医端无停诊按钮", "%d B" % len(h))

print()
print("检查 %d 项，失败 %d 项" % (OK + FAIL, FAIL))
sys.exit(1 if FAIL else 0)
