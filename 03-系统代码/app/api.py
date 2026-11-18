# -*- coding: utf-8 -*-
"""小程序端 JSON 接口（患者端）。

与网页端共用同一套表、同一套业务规则（`biz.py` 的 OCCUPIED / appt_block /
audit / 状态机），只是把渲染换成 JSON。设计上守三条：

1. **鉴权用 Bearer token**，token 就是 SESSION.session_id。网页走 Cookie、
   小程序走 Authorization 头，各自独立，互不踢线。
2. **每个接口都自己判身份**：`/api/*` 不走后台页面白名单（那里是给 HTML 页的），
   患者只能看/改自己名下的就诊人。
3. **写操作一律 try/finally 关连接**——写锁泄漏会把全站拖成 500（验收 A1）。

返回约定：成功 `{"ok": true, ...}`，失败 `{"ok": false, "err": "中文原因"}`
+ 合适的 HTTP 状态码（401 未登录 / 403 无权 / 400 参数错 / 409 冲突）。
"""

import datetime as _dt
import traceback

import biz as B

# 「现在」取一次，列表与下单共用同一判据，
# 避免「列表显示能选、提交才说时段已过」。
_TODAY = _dt.date.today().isoformat()
_NOWHM = _dt.datetime.now().strftime("%H:%M")

# 网页端与小程序端共用的状态字典（与 biz.STATE 一致，避免两处文案分叉）
ST_CN = {
    "已预约": "已预约", "已到诊": "已到诊", "已取消": "已取消", "爽约": "爽约",
}


def register(S, BIZ):
    """由 server.main() 调用。S 是 server 模块，BIZ 是 biz 模块。"""
    route = S.route
    db = S.db
    today = lambda: _dt.date.today().isoformat()

    # ------------------------------------------------------------ 小工具
    def ok(h, **kw):
        d = {"ok": True}
        d.update(kw)
        return h.json(d)

    def bad(h, msg, code=400):
        return h.json({"ok": False, "err": msg}, code)

    def need(h, sess):
        """接口的登录校验。返回 (患者账号, 错误响应或 None)。"""
        if not sess:
            return None, bad(h, "请先登录", 401)
        if (sess.get("role") or "") != "patient":
            return None, bad(h, "这个接口只给患者端用", 403)
        return sess, None

    def my_patients(con, sess):
        """这个账号名下能操作的就诊人（一账号可挂多人，含本人）。"""
        return con.execute(
            "SELECT patient_id, patient_no, name, phone FROM PATIENT"
            " WHERE account_id=? ORDER BY patient_id",
            (sess["account_id"],)).fetchall()

    def own_patient(con, sess, pid):
        return con.execute(
            "SELECT * FROM PATIENT WHERE patient_id=? AND account_id=?",
            (int(pid), sess["account_id"])).fetchone()

    def session_ok(con, sid):
        r = con.execute("SELECT * FROM SESSION WHERE session_id=?", (sid,)).fetchone()
        if not r:
            return False
        return (r["expires_at"] or "") >= _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------ 登录
    @route("POST", r"/api/login")
    def api_login(h, sess):
        f = h.form()
        name = (f.get("login_name") or "").strip()
        pw = f.get("password") or ""
        if not name or not pw:
            return bad(h, "请填写登录名和口令")
        con = db()
        try:
            a = con.execute("SELECT * FROM USER_ACCOUNT WHERE login_name=?",
                            (name,)).fetchone()
            if not a or not S.verify_pw(pw, a["password_hash"], a["password_salt"]):
                return bad(h, "登录名或口令不对", 401)
            if a["account_status"] not in (None, "", "正常", "在职"):
                return bad(h, "这个账号已停用", 403)
            con.execute("UPDATE USER_ACCOUNT SET last_login_at=? WHERE account_id=?",
                        (_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                         a["account_id"]))
            con.commit()
            sid = S.new_session(a["account_id"], a["role"] or "patient")
            pats = [dict(x) for x in my_patients(con, {"account_id": a["account_id"]})]
        finally:
            con.close()
        return ok(h, token=sid, role=a["role"] or "patient",
                  login_name=a["login_name"], patients=pats)

    @route("POST", r"/api/register")
    def api_register(h, sess):
        f = h.form()
        name = (f.get("login_name") or "").strip()
        pw = f.get("password") or ""
        pname = (f.get("patient_name") or "").strip()
        phone = (f.get("phone") or "").strip()
        if len(name) < 3 or len(pw) < 6:
            return bad(h, "登录名至少 3 位、口令至少 6 位")
        if not pname:
            return bad(h, "请填写就诊人姓名")
        con = db()
        try:
            if con.execute("SELECT 1 FROM USER_ACCOUNT WHERE login_name=?",
                           (name,)).fetchone():
                return bad(h, "这个登录名已被占用", 409)
            ph, salt = S.hash_pw(pw)
            now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = con.execute(
                "INSERT INTO USER_ACCOUNT (login_name, password_hash, password_salt,"
                " role, account_status, registered_at) VALUES (?,?,?,?,?,?)",
                (name, ph, salt, "patient", "正常", now))
            aid = cur.lastrowid
            pcur = con.execute(
                "INSERT INTO PATIENT (patient_no, name, phone, source_channel,"
                " first_visit_date, account_id) VALUES (?,?,?,?,?,?)",
                (int(_dt.datetime.now().timestamp()) % 1000000, pname, phone,
                 "小程序", today(), aid))
            con.commit()
            pid = pcur.lastrowid
            sid = S.new_session(aid, "patient")
        finally:
            con.close()
        B.audit({"account_id": aid, "name": pname, "role": "patient"},
                "PATIENT", pid, "insert", None, "%s/%s/小程序" % (pname, phone))
        return ok(h, token=sid, patient_id=pid, name=pname)

    @route("GET", r"/api/ping")
    def api_ping(h, sess):
        return ok(h, server_time=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ------------------------------------------------------------ 我的
    @route("GET", r"/api/me")
    def api_me(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        con = db()
        try:
            pats = [dict(x) for x in my_patients(con, s)]
            if not pats:
                return ok(h, patients=[], next=None, pending=0, history=0, paid=0)
            first = pats[0]["patient_id"]
            row = con.execute(
                "SELECT a.appointment_id, a.appointment_no, a.appointment_datetime,"
                " a.status, r.roster_date, r.slot_start, r.slot_end,"
                " c.clinic_name, c.postal_address, d.name AS dentist"
                " FROM APPOINTMENT a"
                " JOIN ROSTER r ON a.roster_id=r.roster_id"
                " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
                " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
                " WHERE a.patient_id=? AND IFNULL(a.is_void,0)=0"
                " AND a.status='已预约' AND r.roster_date>=?"
                " ORDER BY r.roster_date, r.slot_start LIMIT 1",
                (first, today())).fetchone()
            pending = con.execute(
                "SELECT COUNT(*) FROM APPOINTMENT WHERE patient_id=?"
                " AND IFNULL(is_void,0)=0 AND status='已预约'", (first,)).fetchone()[0]
            hist = con.execute(
                "SELECT COUNT(*) FROM APPOINTMENT WHERE patient_id=?"
                " AND IFNULL(is_void,0)=0 AND status='已到诊'", (first,)).fetchone()[0]
            paid = con.execute(
                "SELECT IFNULL(SUM(p.amount),0) FROM PAYMENT p"
                " JOIN INVOICE i ON p.invoice_id=i.invoice_id"
                " JOIN VISIT v ON i.visit_id=v.visit_id"
                " JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                " WHERE a.patient_id=? AND IFNULL(p.is_void,0)=0", (first,)).fetchone()[0]
            unread = con.execute(
                "SELECT COUNT(*) FROM NOTICE WHERE account_id=?"
                " AND read_at IS NULL AND IFNULL(is_void,0)=0",
                (s["account_id"],)).fetchone()[0]
        finally:
            con.close()
        return ok(h, patients=pats, next=dict(row) if row else None,
                  pending=pending, history=hist,
                  paid=B.money_float(paid), unread=unread)

    # ------------------------------------------------------------ 门店与时段
    @route("GET", r"/api/clinics")
    def api_clinics(h, sess):
        con = db()
        try:
            rows = [dict(x) for x in con.execute(
                "SELECT clinic_id, clinic_no, clinic_name, postal_address, phone,"
                " service_scope FROM CLINIC ORDER BY clinic_id")]
        finally:
            con.close()
        return ok(h, clinics=rows)

    @route("GET", r"/api/days")
    def api_days(h, sess):
        q = S.qs(sess) if hasattr(S, "qs") else {}
        try:
            cid = int(q.get("clinic_id") or 1)
        except ValueError:
            cid = 1
        con = db()
        try:
            out = []
            for i in range(14):
                d = (_dt.date.today() + _dt.timedelta(days=i)).isoformat()
                n = con.execute(
                    "SELECT IFNULL(SUM(r.slot_capacity - (SELECT COUNT(*) FROM"
                    " APPOINTMENT x WHERE x.roster_id=r.roster_id AND "
                    + B.OCCUPIED + ")), 0) FROM ROSTER r"
                    " WHERE r.clinic_id=? AND r.roster_date=?"
                    " AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
                    " AND IFNULL(r.is_reserved,0)=0"
                    " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))",
                    (cid, d, _TODAY, _TODAY, _NOWHM)).fetchone()[0]
                out.append({"date": d, "weekday": "一二三四五六日"[
                    (_dt.date.today() + _dt.timedelta(days=i)).weekday()],
                    "remain": max(0, int(n))})
        finally:
            con.close()
        return ok(h, days=out)

    @route("GET", r"/api/slots")
    def api_slots(h, sess):
        q = S.qs(sess) if hasattr(S, "qs") else {}
        try:
            cid = int(q.get("clinic_id") or 1)
        except ValueError:
            cid = 1
        d = q.get("date") or today()
        con = db()
        try:
            rows = con.execute(
                "SELECT r.roster_id, r.slot_start, r.slot_end,"
                " r.slot_capacity - (SELECT COUNT(*) FROM APPOINTMENT x"
                "   WHERE x.roster_id=r.roster_id AND " + B.OCCUPIED + ") AS left_n,"
                " d.name AS dentist, d.dentist_id"
                " FROM ROSTER r LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
                " WHERE r.clinic_id=? AND r.roster_date=?"
                " AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
                " AND IFNULL(r.is_reserved,0)=0"
                " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))"
                " ORDER BY r.slot_start, d.name",
                (cid, d, _TODAY, _TODAY, _NOWHM)).fetchall()
            out = []
            for r in rows:
                left = int(r["left_n"] or 0)
                out.append({"roster_id": r["roster_id"], "start": r["slot_start"],
                            "end": r["slot_end"], "dentist": r["dentist"],
                            "dentist_id": r["dentist_id"],
                            "left": max(0, left), "full": left <= 0})
        finally:
            con.close()
        return ok(h, date=d, clinic_id=cid, slots=out)

    # ------------------------------------------------------------ 下单
    @route("POST", r"/api/book")
    def api_book(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        f = h.form()
        try:
            rid = int(f.get("roster_id") or 0)
            pid = int(f.get("patient_id") or 0)
        except ValueError:
            return bad(h, "参数不对")
        phone = (f.get("phone") or "").strip()
        reason = (f.get("reason") or "").strip()[:200]
        if not rid or not pid:
            return bad(h, "请选择时段和就诊人")
        con = db()
        try:
            p = own_patient(con, s, pid)
            if not p:
                return bad(h, "这不是你名下的就诊人", 403)
            r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (rid,)).fetchone()
            if not r:
                return bad(h, "这个时段不存在", 404)
            if (r["is_void"] or 0) == 1:
                return bad(h, "这个时段已停诊，请换一个", 409)
            if (r["is_published"] or 0) == 0:
                return bad(h, "这个时段还没放号", 409)
            now_t = _dt.datetime.now().strftime("%H:%M")
            if r["roster_date"] < today() or (r["roster_date"] == today()
                                              and (r["slot_end"] or "23:59") <= now_t):
                return bad(h, "这个时段已经过去了", 409)
            # 并发保护：BEGIN IMMEDIATE 独占写，事务内才查容量
            con.execute("BEGIN IMMEDIATE")
            used = con.execute(
                "SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=? AND " + B.OCCUPIED,
                (rid,)).fetchone()[0]
            if used >= int(r["slot_capacity"] or 0):
                con.rollback()
                return bad(h, "这个时段已约满，换一个吧", 409)
            dup = con.execute(
                "SELECT 1 FROM APPOINTMENT WHERE patient_id=? AND roster_id=?"
                " AND " + B.OCCUPIED, (pid, rid)).fetchone()
            if dup:
                con.rollback()
                return bad(h, "这位就诊人已经约了这个时段", 409)
            d8 = (r["roster_date"] or today()).replace("-", "")
            mx = con.execute(
                "SELECT IFNULL(MAX(CAST(SUBSTR(appointment_no,10) AS INTEGER)),0)"
                " FROM APPOINTMENT WHERE appointment_no LIKE ?",
                ("A" + d8 + "%",)).fetchone()[0]
            no = None
            for step in range(1, 500):
                cand = "A%s%04d" % (d8, int(mx) + step)
                if not con.execute("SELECT 1 FROM APPOINTMENT WHERE appointment_no=?",
                                   (cand,)).fetchone():
                    no = cand
                    break
            if no is None:
                con.rollback()
                return bad(h, "今天号源编号用完了，请联系前台", 409)
            at = "%s %s:00" % (r["roster_date"], r["slot_start"])
            cur = con.execute(
                "INSERT INTO APPOINTMENT (appointment_no, patient_id, roster_id,"
                " appointment_datetime, status, visit_reason) VALUES (?,?,?,?,?,?)",
                (no, pid, rid, at, "已预约", reason or None))
            aid = cur.lastrowid
            con.commit()
        finally:
            con.close()
        B.audit(s, "APPOINTMENT", aid, "insert", None,
                "%s/%s" % (no, p["name"]), patient_id=pid)
        return ok(h, appointment_id=aid, appointment_no=no,
                  datetime=at, patient=p["name"])

    # ------------------------------------------------------------ 我的预约
    @route("GET", r"/api/appointments")
    def api_appointments(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        con = db()
        try:
            pats = my_patients(con, s)
            ids = [p["patient_id"] for p in pats]
            if not ids:
                return ok(h, upcoming=[], history=[])
            ph = ",".join("?" * len(ids))
            rows = con.execute(
                "SELECT a.appointment_id, a.appointment_no, a.status,"
                " a.appointment_datetime, a.cancellation_category, a.void_reason,"
                " r.roster_date, r.slot_start, r.slot_end,"
                " c.clinic_name, d.name AS dentist, p.name AS patient"
                " FROM APPOINTMENT a"
                " JOIN ROSTER r ON a.roster_id=r.roster_id"
                " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
                " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
                " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                " WHERE a.patient_id IN (" + ph + ")"
                " ORDER BY r.roster_date DESC, r.slot_start DESC LIMIT 80", ids).fetchall()
            up, his = [], []
            for r in rows:
                d = dict(r)
                d["why"] = _why(d)
                (up if d["status"] == "已预约" and (d["roster_date"] or "") >= today()
                 else his).append(d)
            up.sort(key=lambda x: (x["roster_date"], x["slot_start"]))
        finally:
            con.close()
        return ok(h, upcoming=up, history=his)

    def _why(d):
        st = d.get("status") or ""
        if st == "已取消":
            cat = d.get("cancellation_category") or ""
            return ("取消原因：%s" % cat) if cat else "已取消"
        if st == "爽约":
            return "这个号没等到您，需要的话重新约一个"
        if (d.get("void_reason") or ""):
            return "已作废：%s" % d["void_reason"]
        return ""

    # ------------------------------------------------------------ 取消
    @route("POST", r"/api/cancel")
    def api_cancel(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        f = h.form()
        try:
            aid = int(f.get("appointment_id") or 0)
        except ValueError:
            return bad(h, "参数不对")
        cat = (f.get("reason") or "患者原因").strip()[:40]
        con = db()
        try:
            a = con.execute(
                "SELECT a.*, r.roster_date, r.slot_start FROM APPOINTMENT a"
                " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
                " WHERE a.appointment_id=?", (aid,)).fetchone()
            if not a:
                return bad(h, "这条预约不存在", 404)
            if not own_patient(con, s, a["patient_id"]):
                return bad(h, "这不是你名下的预约", 403)
            block = B.appt_block(a, "cancel")
            if block:
                return bad(h, block, 409)
            cur = con.execute(
                "UPDATE APPOINTMENT SET status='已取消', cancellation_category=?"
                " WHERE appointment_id=? AND status='已预约'", (cat, aid))
            if cur.rowcount != 1:
                con.rollback()
                return bad(h, "这条预约状态刚变了，刷新看看", 409)
            con.commit()
        finally:
            con.close()
        B.audit(s, "APPOINTMENT", aid, "status", "已预约", "已取消/" + cat)
        return ok(h, msg="已取消，这个号释放给别人了")

    # ------------------------------------------------------------ 改约
    @route("GET", r"/api/reschedule")
    def api_resched_form(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        q = S.qs(sess) if hasattr(S, "qs") else {}
        try:
            aid = int(q.get("appointment_id") or 0)
        except ValueError:
            return bad(h, "参数不对")
        want = q.get("date") or ""
        con = db()
        try:
            a = con.execute(
                "SELECT a.*, r.clinic_id, r.roster_date, r.slot_start, r.slot_end,"
                " c.clinic_name, dn.name AS dentist FROM APPOINTMENT a"
                " JOIN ROSTER r ON a.roster_id=r.roster_id"
                " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
                " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
                " WHERE a.appointment_id=?", (aid,)).fetchone()
            if not a:
                return bad(h, "这条预约不存在", 404)
            if not own_patient(con, s, a["patient_id"]):
                return bad(h, "这不是你名下的预约", 403)
            try:
                cid = int(q.get("clinic_id") or a["clinic_id"])
            except ValueError:
                cid = a["clinic_id"]
            # 没指定日期就自动找「明天起第一个真有空位的那天」，
            # 否则周一改约、周一这家店没排班，页面一片空白。
            cands = [want] if want else [
                (_dt.date.today() + _dt.timedelta(days=i)).isoformat()
                for i in range(1, 15)]
            d, rows = cands[0], []
            for cd in cands:
                rows = con.execute(
                    "SELECT r.roster_id, r.slot_start, r.slot_end, dn.name AS dentist,"
                    " r.slot_capacity - (SELECT COUNT(*) FROM APPOINTMENT x"
                    "   WHERE x.roster_id=r.roster_id AND " + B.OCCUPIED + ") AS left_n"
                    " FROM ROSTER r LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
                    " WHERE r.clinic_id=? AND r.roster_date=?"
                    " AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
                    " AND IFNULL(r.is_reserved,0)=0"
                    " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))"
                    " ORDER BY r.slot_start",
                    (cid, cd, _TODAY, _TODAY, _NOWHM)).fetchall()
                if rows or want:
                    d = cd
                    break
            slots = [{"roster_id": r["roster_id"], "start": r["slot_start"],
                      "end": r["slot_end"], "dentist": r["dentist"],
                      "left": max(0, int(r["left_n"] or 0))} for r in rows]
            clinics = [dict(x) for x in con.execute(
                "SELECT clinic_id, clinic_name FROM CLINIC ORDER BY clinic_id")]
        finally:
            con.close()
        return ok(h, current={"appointment_id": a["appointment_id"],
                              "clinic_name": a["clinic_name"],
                              "date": a["roster_date"], "start": a["slot_start"],
                              "end": a["slot_end"], "dentist": a["dentist"]},
                  date=d, clinic_id=cid, clinics=clinics, slots=slots)

    @route("POST", r"/api/reschedule")
    def api_resched_do(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        f = h.form()
        try:
            aid = int(f.get("appointment_id") or 0)
            rid = int(f.get("roster_id") or 0)
        except ValueError:
            return bad(h, "参数不对")
        con = db()
        try:
            a = con.execute("SELECT * FROM APPOINTMENT WHERE appointment_id=?",
                            (aid,)).fetchone()
            if not a:
                return bad(h, "这条预约不存在", 404)
            if not own_patient(con, s, a["patient_id"]):
                return bad(h, "这不是你名下的预约", 403)
            block = B.appt_block(a, "reschedule")
            if block:
                return bad(h, block, 409)
            r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (rid,)).fetchone()
            if not r:
                return bad(h, "目标时段不存在", 404)
            if (r["is_void"] or 0) == 1 or (r["is_published"] or 0) == 0:
                return bad(h, "这个时段不可约", 409)
            if r["roster_date"] < today():
                return bad(h, "不能改到过去的日期", 409)
            con.execute("BEGIN IMMEDIATE")
            used = con.execute(
                "SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=? AND " + B.OCCUPIED,
                (rid,)).fetchone()[0]
            if used >= int(r["slot_capacity"] or 0):
                con.rollback()
                return bad(h, "目标时段已满", 409)
            dup = con.execute(
                "SELECT 1 FROM APPOINTMENT WHERE patient_id=? AND roster_id=?"
                " AND " + B.OCCUPIED + " AND appointment_id<>?",
                (a["patient_id"], rid, aid)).fetchone()
            if dup:
                con.rollback()
                return bad(h, "这位就诊人已经约了这个时段", 409)
            at = "%s %s:00" % (r["roster_date"], r["slot_start"])
            cur = con.execute(
                "UPDATE APPOINTMENT SET roster_id=?, appointment_datetime=?"
                " WHERE appointment_id=? AND status='已预约'", (rid, at, aid))
            if cur.rowcount != 1:
                con.rollback()
                return bad(h, "这条预约状态刚变了", 409)
            con.commit()
        finally:
            con.close()
        B.audit(s, "APPOINTMENT", aid, "roster_id", a["roster_id"], rid)
        return ok(h, msg="已改约", datetime=at)

    # ------------------------------------------------------------ 就诊与账单
    @route("GET", r"/api/visits")
    def api_visits(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        con = db()
        try:
            pats = [p["patient_id"] for p in my_patients(con, s)]
            if not pats:
                return ok(h, visits=[])
            ph = ",".join("?" * len(pats))
            rows = con.execute(
                "SELECT v.visit_id, v.visit_no, v.visit_datetime, v.treated,"
                " v.chief_complaint, v.diagnosis, v.treatment_note,"
                " c.clinic_name, dn.name AS dentist, p.name AS patient,"
                " i.invoice_id, i.invoice_no, i.invoice_date, i.status AS inv_status,"
                " (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l"
                "   WHERE l.invoice_id=i.invoice_id AND IFNULL(l.is_void,0)=0) AS due,"
                " (SELECT IFNULL(SUM(amount),0) FROM PAYMENT pm"
                "   WHERE pm.invoice_id=i.invoice_id AND IFNULL(pm.is_void,0)=0) AS got"
                " FROM VISIT v"
                " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
                " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
                " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
                " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id"
                "   AND IFNULL(i.is_void,0)=0"
                " WHERE a.patient_id IN (" + ph + ") AND IFNULL(v.is_void,0)=0"
                " ORDER BY v.visit_datetime DESC LIMIT 60", pats).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["due"] = B.money_float(d["due"])
                d["got"] = B.money_float(d["got"])
                out.append(d)
        finally:
            con.close()
        return ok(h, visits=out)

    @route("GET", r"/api/invoices")
    def api_invoices(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        con = db()
        try:
            pats = [p["patient_id"] for p in my_patients(con, s)]
            if not pats:
                return ok(h, invoices=[])
            ph = ",".join("?" * len(pats))
            rows = con.execute(
                "SELECT i.invoice_id, i.invoice_no, i.invoice_date, i.status,"
                " c.clinic_name, p.name AS patient,"
                " (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l"
                "   WHERE l.invoice_id=i.invoice_id AND IFNULL(l.is_void,0)=0) AS due,"
                " (SELECT IFNULL(SUM(amount),0) FROM PAYMENT pm"
                "   WHERE pm.invoice_id=i.invoice_id AND IFNULL(pm.is_void,0)=0) AS got"
                " FROM INVOICE i JOIN VISIT v ON i.visit_id=v.visit_id"
                " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
                " WHERE a.patient_id IN (" + ph + ") AND IFNULL(i.is_void,0)=0"
                " ORDER BY i.invoice_date DESC, i.invoice_id DESC LIMIT 60",
                pats).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["due"] = B.money_float(d["due"])
                d["got"] = B.money_float(d["got"])
                d["owe"] = round(d["due"] - d["got"], 2)
                out.append(d)
        finally:
            con.close()
        return ok(h, invoices=out)

    # ------------------------------------------------------------ 通知
    @route("GET", r"/api/notices")
    def api_notices(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        con = db()
        try:
            rows = [dict(x) for x in con.execute(
                "SELECT notice_id, kind, title, body, created_at, read_at"
                " FROM NOTICE WHERE account_id=? AND IFNULL(is_void,0)=0"
                " ORDER BY created_at DESC LIMIT 50", (s["account_id"],))]
        finally:
            con.close()
        return ok(h, notices=rows)

    @route("POST", r"/api/notices/read")
    def api_notice_read(h, sess):
        s, err = need(h, sess)
        if err:
            return err
        f = h.form()
        con = db()
        try:
            nid = (f.get("notice_id") or "").strip()
            now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if nid:
                con.execute("UPDATE NOTICE SET read_at=? WHERE notice_id=?"
                            " AND account_id=? AND read_at IS NULL",
                            (now, int(nid), s["account_id"]))
            else:
                con.execute("UPDATE NOTICE SET read_at=? WHERE account_id=?"
                            " AND read_at IS NULL", (now, s["account_id"]))
            con.commit()
        finally:
            con.close()
        return ok(h, msg="已标为已读")

    print("  小程序接口已注册（14 条 /api/*）")
