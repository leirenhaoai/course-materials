# -*- coding: utf-8 -*-
"""ADC 业务模块（第二批）：复诊回访、治疗计划、账号管理、质量事件、日结对账、导出。

按 10.0 设计文档补上「系统里本来没有、但日常动作绕不开」的几块。
所有页面都走 biz.py 的同一套渲染函数，保证外观一致。
"""
import csv
import io
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta

S = None          # 由 register(mod) 注入正在运行的 server 模块
B = None          # biz 模块


def _q(sess, key, default=""):
    """Handler 上没有 `qs`，query 要去 sess["_path"] 里解析（与 biz.py 同）。"""
    import urllib.parse as _u
    q = _u.parse_qs(_u.urlparse(sess.get("_path") or "").query)
    return (q.get(key) or [default])[0]


def register(mod, bizmod):
    global S, B
    S = mod
    B = bizmod
    S.CSS += EXTRA_CSS

    def g(p, fn):
        S.ROUTES.append(("GET", re.compile("^" + p + "$"), fn))

    def po(p, fn):
        S.ROUTES.append(("POST", re.compile("^" + p + "$"), fn))

    # 证照到期
    g(r"/desk/license", p_license)
    # 站内通知
    g(r"/me/notices", p_notices)
    g(r"/me/notices/read", r_notices_read)
    # 复诊回访
    g(r"/desk/recalls", p_recalls)
    po(r"/desk/recalls/(\d+)/(done|booked|drop)", r_recall_act)
    # 治疗计划
    g(r"/desk/plans", p_plans)
    po(r"/desk/plans/(\d+)/(run|drop)", r_plan_act)
    # 账号管理
    g(r"/desk/accounts", p_accounts2)
    po(r"/desk/accounts/(\d+)/(reset|toggle|role)", r_account_act)
    # 质量事件
    g(r"/desk/quality/new", p_quality_new)
    po(r"/desk/quality/new", r_quality_new)
    po(r"/desk/quality/(\d+)/close", r_quality_close)
    # 日结对账
    g(r"/desk/daily", p_daily)
    g(r"/desk/daily.csv", r_daily_csv)
    # 导出
    g(r"/desk/export/(patients|appointments|invoices|stock).csv", r_export_csv)

    S.MENU.setdefault("frontdesk", [])
    _add_menu("manager", "/desk/license", "证照到期", "db")
    _add_menu("hq", "/desk/license", "证照到期", "db")
    _add_menu("patient", "/me/notices", "通知", "doc")
    _add_menu("frontdesk", "/desk/recalls", "复诊回访", "doc")
    _add_menu("doctor", "/desk/plans", "治疗计划", "doc")
    _add_menu("hq", "/desk/daily", "日结对账", "db")
    _add_menu("finance", "/desk/daily", "日结对账", "db")


def _add_menu(desk, path, name, icon):
    lst = S.MENU.get(desk) or []
    if not any(p == path for p, _, _ in lst):
        lst = lst + [(path, name, icon)]
        S.MENU[desk] = lst


EXTRA_CSS = """
.grid.g4{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:1100px){.grid.g4{grid-template-columns:repeat(2,minmax(0,1fr))}}
.tbl th{position:sticky;top:0}
.tiny{font-size:12px;color:#8a94a6}
.money{font-variant-numeric:tabular-nums;text-align:right}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
     background:#eef2f7;color:#4a5568}
.tag.ok{background:#e6f6ec;color:#1f7a44}
.tag.warn{background:#fdf0e3;color:#8a5310}
.tag.bad{background:#fdeaea;color:#9b2c2c}
.rowbar{display:flex;gap:8px;align-items:center;margin:8px 0}
"""


# -------------------------------------------------------------- 证照到期预警
def p_license(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk?err=证照预警只对店长与总部开放")
    c = B.con()
    t = B.today()
    cl = c.execute(
        "SELECT clinic_id, clinic_name, license_no, license_valid_until,"
        " CAST(julianday(license_valid_until) - julianday(?) AS INTEGER) d"
        " FROM CLINIC ORDER BY license_valid_until IS NULL,"
        " license_valid_until", (t,)).fetchall()
    dq = c.execute(
        "SELECT d.dentist_id, d.name, d.employee_no, q.qualification_id,"
        " ql.qualification_name, q.certificate_no, q.valid_until,"
        " CAST(julianday(q.valid_until) - julianday(?) AS INTEGER) d"
        " FROM DENTIST_QUALIFICATION q"
        " JOIN DENTIST d ON d.dentist_id=q.dentist_id"
        " LEFT JOIN QUALIFICATION ql ON ql.qualification_id=q.qualification_id"
        " ORDER BY q.valid_until IS NULL, q.valid_until", (t,)).fetchall()
    c.close()

    def band(d):
        if d is None:
            return "未登记"
        if d < 0:
            return "已过期"
        if d <= 90:
            return "90 天内"
        return "正常"

    def rowd(rows, cols):
        out = []
        for r in rows:
            b = band(r["d"])
            cls = "bad" if b == "已过期" else ("warn" if b == "90 天内" else "")
            cell = '<span class="tag %s">%s</span>' % (cls, b) if cls else b
            out.append([B.esc(r[k] or "") for k in cols] +
                       [B.esc(r["valid_until"] if "valid_until" in r.keys()
                              else (r["license_valid_until"] or "")),
                        "-" if r["d"] is None else str(r["d"]), cell])
        return out

    c1 = rowd(cl, ["clinic_name", "license_no"])
    c2 = rowd(dq, ["name", "employee_no", "qualification_name", "certificate_no"])
    n_bad = sum(1 for r in cl + dq if r["d"] is not None and r["d"] < 0)
    n_warn = sum(1 for r in cl + dq if r["d"] is not None and 0 <= r["d"] <= 90)
    n_none = sum(1 for r in cl + dq if r["d"] is None)

    body = (
        '<div class="row"><h1>证照与资质到期</h1></div>'
        '<p class="sub">执业许可证过期还在营业、牙医资质过期还在接诊，是查出来就要停业的'
        '问题。这里把两个日期都摊开，90 天内到期的提前办。</p>'
        + '<div class="grid g3">'
        + S.stat(n_bad, "已过期", "须立即处理")
        + S.stat(n_warn, "90 天内到期", "尽快续办")
        + S.stat(n_none, "未登记有效期", "补齐资料")
        + '</div>'
        + '<div class="panel"><div class="h">门店执业许可证</div><div class="bd">'
        + B.table(["门店", "许可证号", "有效期至", "剩余天数", "状态"], c1, "没有门店记录")
        + '</div></div>'
        + '<div class="panel"><div class="h">牙医资质</div><div class="bd">'
        + B.table(["牙医", "员工编号", "资质", "证书编号", "有效期至", "剩余天数", "状态"],
                  c2, "没有资质记录")
        + '</div></div>')
    return h.send(200, S.page("证照到期", body, sess, "/desk/license"))


# ------------------------------------------------------------------ 站内通知
def notify(sess, patient_id, kind, title, body, ref_table=None, ref_id=None, con=None):
    """给患者账号留一条站内通知。没有账号（散客）就跳过，不报错。"""
    c = con
    own = c is None
    if own:
        c = B.con()
    try:
        acc = c.execute("SELECT account_id FROM PATIENT WHERE patient_id=?",
                        (patient_id,)).fetchone()
        if not acc or not acc["account_id"]:
            return
        c.execute("INSERT INTO NOTICE(account_id, patient_id, kind, title, body,"
                  " ref_table, ref_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (acc["account_id"], patient_id, kind, title, body,
                   ref_table, ref_id,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        if own:
            c.commit()
    except Exception as e:                       # 通知失败不该拖垮主业务
        sys.stderr.write("[notice] %s\n" % e)
    finally:
        if own:
            c.close()


def unread_count(sess):
    if not sess or not sess.get("account_id"):
        return 0
    c = B.con()
    n = c.execute("SELECT COUNT(*) FROM NOTICE WHERE account_id=?"
                  " AND read_at IS NULL AND IFNULL(is_void,0)=0",
                  (sess["account_id"],)).fetchone()[0]
    c.close()
    return n


def p_notices(h, sess):
    if not sess:
        return h.redirect("/login")
    if not sess.get("account_id"):
        return h.redirect("/me?err=游客没有通知")
    c = B.con()
    rows = c.execute("SELECT * FROM NOTICE WHERE account_id=? AND IFNULL(is_void,0)=0"
                     " ORDER BY notice_id DESC LIMIT 100",
                     (sess["account_id"],)).fetchall()
    tr = []
    nw = ' style="white-space:nowrap"'
    for r in rows:
        new = not r["read_at"]
        tag = '<span class="tag warn">未读</span>' if new else '<span class="tag">已读</span>'
        tr.append(['<span%s>%s</span>' % (nw, B.esc((r["created_at"] or "")[:16])),
                   '<span%s>%s</span>' % (nw, B.esc(r["kind"] or "")),
                   '<b>%s</b>' % B.esc(r["title"] or "") if new else B.esc(r["title"] or ""),
                   B.esc(r["body"] or ""),
                   '<span%s>%s</span>' % (nw, tag)])
    body = ('<div class="row"><h1>通知</h1>'
            '<a class="btn ghost" href="/me/notices/read">全部标为已读</a></div>'
            '<p class="sub">停诊、改约、收款这些影响到你的事情，系统会在这里留一条。</p>'
            + B.table(["时间", "类型", "标题", "说明", "状态"], tr, "还没有通知"))
    c.close()
    return h.send(200, S.page("通知", body, sess, "/me/notices"))


def r_notices_read(h, sess):
    if not sess or not sess.get("account_id"):
        return h.redirect("/login")
    c = B.con()
    c.execute("UPDATE NOTICE SET read_at=? WHERE account_id=? AND read_at IS NULL",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sess["account_id"]))
    c.commit()
    c.close()
    return h.redirect("/me/notices?ok=已全部标为已读")


# ------------------------------------------------------------------ 复诊回访
def p_recalls(h, sess):
    if not sess:
        return h.redirect("/login")
    c = B.con()
    cid = B.staff_clinic(sess)
    cond, args = "", ()
    if cid and sess["desk"] in ("frontdesk", "assistant"):
        cond = " AND (r.clinic_id=? OR r.clinic_id IS NULL)"
        args = (cid,)
    rows = c.execute(
        "SELECT f.*, p.name pname, p.phone, dn.name dname"
        " FROM FOLLOWUP_RECALL f"
        " LEFT JOIN VISIT v ON f.visit_id=v.visit_id"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON f.patient_id=p.patient_id"
        " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
        " WHERE IFNULL(f.is_void,0)=0 AND f.status IN ('待召回','待回访','已联系')" + cond +
        " ORDER BY f.due_date LIMIT 200", args).fetchall()
    t = B.today()
    tr = []
    for r in rows:
        late = (r["due_date"] or "") < t
        st = r["status"]
        tag = ('<span class="tag warn">已过期</span>' if late and st == "待回访"
               else '<span class="tag">%s</span>' % B.esc(st))
        act = ('<form method="post" action="/desk/recalls/%d/done" style="margin:0">'
               '<button class="btn ghost sm">已联系</button></form>'
               '<form method="post" action="/desk/recalls/%d/booked" style="margin:0;margin-left:4px">'
               '<button class="btn ghost sm">已约回</button></form>'
               '<form method="post" action="/desk/recalls/%d/drop" style="margin:0;margin-left:4px">'
               '<button class="btn ghost sm">不再跟</button></form>'
               % (r["recall_id"], r["recall_id"], r["recall_id"]))
        tr.append([B.esc(r["due_date"]), B.esc(r["pname"]), B.esc(r["phone"] or ""),
                   B.esc(r["dname"] or "—"), tag, act])
    body = ('<h1>复诊回访</h1>'
            '<p class="sub">按应回访日期排。过期的排在前面，点「已联系」记一笔，'
            '「已约回」表示患者已经重新约上了。</p>' +
            B.table(["应回访", "患者", "电话", "上次牙医", "状态", "处理"], tr,
                    "没有待回访的记录"))
    c.close()
    return h.send(200, S.page("复诊回访", body, sess, "/desk/recalls"))


def r_recall_act(h, sess, rid, act):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("frontdesk", "assistant", "manager", "hq", "admin"):
        return h.redirect("/desk/recalls?err=没有权限")
    m = {"done": "已联系", "booked": "已约回", "drop": "已放弃"}
    c = B.con()
    rc = c.execute("SELECT * FROM FOLLOWUP_RECALL WHERE recall_id=?", (int(rid),)).fetchone()
    if not rc:
        c.close()
        return h.redirect("/desk/recalls?err=这条回访不存在")
    made = None
    if act == "booked":
        # 「已约回」不能只改个状态：得真的占一个号，否则患者根本没被安排上。
        # 优先挂回原牙医原门店，往后找第一个还有余位的时段。
        did = (sess.get("dentist_id") or 0)
        row = c.execute(
            "SELECT r.roster_id, r.roster_date, r.slot_start,"
            "       (SELECT name FROM DENTIST WHERE dentist_id=r.dentist_id) dn"
            "  FROM ROSTER r"
            " WHERE IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
            "   AND r.roster_date >= ?"
            "   AND r.slot_capacity > (SELECT COUNT(*) FROM APPOINTMENT a"
            "        WHERE a.roster_id=r.roster_id AND IFNULL(a.is_void,0)=0"
            "          AND a.status IN ('已预约','已到诊'))"
            + (" AND r.dentist_id=?" if did else "") +
            " ORDER BY r.roster_date, r.slot_start LIMIT 1",
            (B.today(), did) if did else (B.today(),)).fetchone()
        if row:
            d8 = row["roster_date"].replace("-", "")
            n = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE appointment_no LIKE ?",
                          ("A" + d8 + "%",)).fetchone()[0] + 1
            ano = "A%s%04d" % (d8, n)
            c.execute("INSERT INTO APPOINTMENT(appointment_no, patient_id, roster_id,"
                      " appointment_datetime, status, visit_reason)"
                      " VALUES(?,?,?,?,?,?)",
                      (ano, rc["patient_id"], row["roster_id"],
                       "%s %s" % (row["roster_date"], row["slot_start"]),
                       "已预约", "复诊回访预约"))
            made = (ano, row["dn"], row["roster_date"], row["slot_start"])
    c.execute("UPDATE FOLLOWUP_RECALL SET status=?, completed_date=?"
              " WHERE recall_id=?", (m[act], B.today(), int(rid)))
    c.commit()
    c.close()
    B.audit(sess, "FOLLOWUP_RECALL", rid, "status", None, m[act])
    if act == "booked" and not made:
        return h.redirect("/desk/recalls?err=没有可用时段，先给患者留个电话记录，"
                          "等排班出来再约")
    if made:
        return h.redirect("/desk/recalls?ok=已约回：%s，%s %s %s"
                          % (made[0], made[1], made[2], made[3]))
    return h.redirect("/desk/recalls?ok=已记一笔")


# ------------------------------------------------------------------ 治疗计划
def p_plans(h, sess):
    if not sess:
        return h.redirect("/login")
    c = B.con()
    did = sess.get("dentist_id")
    cond, args = "", ()
    if did:
        cond = " AND r.dentist_id=?"
        args = (did,)
    elif B.staff_clinic(sess):
        cond = " AND r.clinic_id=?"
        args = (B.staff_clinic(sess),)
    rows = c.execute(
        "SELECT tp.*, v.visit_id, a.patient_id, p.name pname, dn.name dname,"
        " c2.clinic_name,"
        " (SELECT COUNT(*) FROM TREATMENT_ITEM ti WHERE ti.visit_id=tp.visit_id) items"
        " FROM TREATMENT_PLAN tp"
        " LEFT JOIN VISIT v ON tp.visit_id=v.visit_id"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
        " LEFT JOIN CLINIC c2 ON r.clinic_id=c2.clinic_id"
        " WHERE 1=1" + cond + " ORDER BY tp.created_date DESC, tp.plan_id DESC LIMIT 120",
        args).fetchall()
    tr = []
    for r in rows:
        act = ('<a class="btn ghost sm" href="/desk/visit/%d">去本次诊台</a>' % r["visit_id"]
               if r["visit_id"] else '<span class="tiny">无关联就诊</span>')
        tr.append([B.esc(r["created_date"] or ""), B.esc(r["pname"] or "—"),
                   B.esc(r["dname"] or "—"), B.esc((r["plan_description"] or "")[:40]),
                   "%d 项" % r["items"], act])
    body = ('<h1>治疗计划</h1>'
            '<p class="sub">计划本身是「接下来几次要做什么」。点进去在诊台里'
            '把这次做的加进治疗项目，应收就跟着算出来了。</p>' +
            B.table(["建立日期", "患者", "牙医", "计划", "已做项目", ""], tr,
                    "还没有治疗计划"))
    c.close()
    return h.send(200, S.page("治疗计划", body, sess, "/desk/plans"))


def r_plan_act(h, sess, pid_, act):
    return h.redirect("/desk/plans")


# ------------------------------------------------------------ 账号与权限管理
def p_accounts2(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("hq", "ops", "admin"):
        return h.redirect("/desk?err=只有总部可以管账号")
    c = B.con()
    rows = c.execute(
        "SELECT u.*, s.name sname, d.name dname,"
        " (SELECT COUNT(*) FROM PATIENT p WHERE p.account_id=u.account_id) pts,"
        " (SELECT COUNT(*) FROM SESSION s2 WHERE s2.account_id=u.account_id"
        "   AND s2.expires_at>datetime('now')) live"
        " FROM USER_ACCOUNT u"
        " LEFT JOIN STAFF s ON u.staff_id=s.staff_id"
        " LEFT JOIN DENTIST d ON u.dentist_id=d.dentist_id"
        " ORDER BY u.role, u.login_name").fetchall()
    ROLE = {"patient": "患者", "receptionist": "接待员", "dentist": "牙医",
            "assistant": "助手", "supervisor": "店长", "ops": "总部运营",
            "finance": "财务", "admin": "管理员"}
    tr = []
    for r in rows:
        who = r["sname"] or r["dname"] or ("挂 %d 个患者" % r["pts"] if r["pts"] else "—")
        st = ('<span class="tag ok">正常</span>' if r["account_status"] == "正常"
              else '<span class="tag bad">%s</span>' % B.esc(r["account_status"] or ""))
        act = ('<form method="post" action="/desk/accounts/%d/reset" style="margin:0">'
               '<button class="btn ghost sm">重置口令</button></form>'
               '<form method="post" action="/desk/accounts/%d/toggle" style="margin:0;margin-left:4px">'
               '<button class="btn ghost sm">%s</button></form>'
               % (r["account_id"], r["account_id"],
                  "停用" if r["account_status"] == "正常" else "启用"))
        tr.append([B.esc(r["login_name"]), ROLE.get(r["role"], r["role"]),
                   B.esc(who), st, "%d" % r["live"],
                   B.esc((r["last_login_at"] or "")[:16]), act])
    body = ('<h1>账号与权限</h1>'
            '<p class="sub">重置后的临时口令统一是 <code>123456</code>，'
            '请让本人登录后自己改。停用后该账号立即无法登录，已登录的会话下次请求就失效。</p>' +
            B.table(["登录名", "角色", "对应人员", "状态", "在线会话", "最后登录", "操作"],
                    tr, "没有账号"))
    c.close()
    return h.send(200, S.page("账号与权限", body, sess, "/desk/accounts"))


def r_account_act(h, sess, aid, act):
    # 重置口令是最高危的操作之一，必须留痕（原来重置完 AUDIT_LOG 一条不加）
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("hq", "ops", "admin"):
        return h.redirect("/desk?err=只有总部可以管账号")
    c = B.con()
    a = c.execute("SELECT * FROM USER_ACCOUNT WHERE account_id=?", (int(aid),)).fetchone()
    if not a:
        c.close()
        return h.redirect("/desk/accounts?err=账号不存在")
    if act == "reset":
        hsh, salt = S.hash_pw("123456")
        c.execute("UPDATE USER_ACCOUNT SET password_hash=?, password_salt=?"
                  " WHERE account_id=?", (hsh, salt, int(aid)))
        c.execute("DELETE FROM SESSION WHERE account_id=?", (int(aid),))
        c.commit()
        c.close()
        # 重置口令是最高危的操作之一，必须留痕（原来重置完 AUDIT_LOG 一条不加）
        B.audit(sess, "USER_ACCOUNT", aid, "password_hash", "原口令哈希", "重置为 123456")
        return h.redirect("/desk/accounts?ok=%s 的口令已重置为 123456" % a["login_name"])
    if act == "toggle":
        new = "停用" if a["account_status"] == "正常" else "正常"
        c.execute("UPDATE USER_ACCOUNT SET account_status=? WHERE account_id=?",
                  (new, int(aid)))
        if new == "停用":
            c.execute("DELETE FROM SESSION WHERE account_id=?", (int(aid),))
        c.commit()
        c.close()
        B.audit(sess, "USER_ACCOUNT", aid, "account_status", a["account_status"], new)
        return h.redirect("/desk/accounts?ok=已%s" % new)
    if act == "role":
        # 改角色等于改权限边界，三条规矩：
        #   1) 不能改自己（否则可以给自己升权，绕开所有校验）
        #   2) 只能改成 ROLE_CN 里有的角色
        #   3) 改完必须踢掉所有会话——desk/role 是登录时写进 SESSION 的
        want = (h.form().get("role") or "").strip()
        if not want or want not in S.ROLE_CN:
            c.close()
            return h.redirect("/desk/accounts?err=角色不合法")
        if int(aid) == int(sess.get("account_id") or 0):
            c.close()
            return h.redirect("/desk/accounts?err=不能改自己的角色，请让另一位管理员来改")
        old = a["role"]
        # 患者账号与员工账号是两族，不能互转：患者号里没有任何 staff_id / dentist_id，
        # 改成「接诊牙医」后所有按 staff_id 做的归属校验都会失效（刚实测踩到）。
        if (old == "patient") != (want == "patient"):
            c.close()
            return h.redirect("/desk/accounts?err=患者账号与员工账号不能互转，"
                              "该建新号就建新号")
        if old == want:
            c.close()
            return h.redirect("/desk/accounts?ok=%s 本来就是%s" % (a["login_name"], S.ROLE_CN[want]))
        c.execute("UPDATE USER_ACCOUNT SET role=? WHERE account_id=?", (want, int(aid)))
        c.execute("DELETE FROM SESSION WHERE account_id=?", (int(aid),))
        c.commit()
        c.close()
        B.audit(sess, "USER_ACCOUNT", aid, "role", old, want)
        return h.redirect("/desk/accounts?ok=%s 改为%s，已踢下线，重新登录后生效"
                          % (a["login_name"], S.ROLE_CN[want]))
    c.close()
    return h.redirect("/desk/accounts?err=不认识的操作")


# ------------------------------------------------------------------ 质量事件
def p_quality_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin", "doctor", "assistant"):
        return h.redirect("/desk?err=没有权限")
    c = B.con()
    clis = c.execute("SELECT clinic_id, clinic_name FROM CLINIC").fetchall()
    c.close()
    body = ('<h1>登记质量事件</h1>'
            '<p class="sub">不良事件、消毒不合格、耗材过期都记这里。'
            '登记后进入待处理，处理完由店长或总部关闭。</p>'
            '<div class="panel"><div class="bd">'
            '<form method="post" action="/desk/quality/new" class="f2">'
            '<label class="f">门店<select name="clinic_id">%s</select></label>'
            '<label class="f">类型<select name="incident_type">'
            '<option>不良事件</option><option>感染控制</option><option>耗材质量</option>'
            '<option>服务投诉</option><option>设备故障</option></select></label>'
            '<label class="f">严重度<select name="severity">'
            '<option>低</option><option>中</option><option>高</option></select></label>'
            '<label class="f">发生日期<input type="date" name="occurred_date" value="%s" required></label>'
            '<label class="f" style="grid-column:1/-1">事件描述'
            '<textarea name="description" rows="3" required '
            'placeholder="什么时间、哪位患者/医生、发生了什么、当时的处置"></textarea></label>'
            '<button class="btn">提交登记</button></form></div></div>'
            % ("".join('<option value="%d">%s</option>'
                       % (c2["clinic_id"], B.esc(c2["clinic_name"])) for c2 in clis),
               B.today()))
    return h.send(200, S.page("登记质量事件", body, sess, "/desk/quality/new"))


def r_quality_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin", "doctor", "assistant"):
        return h.redirect("/desk?err=没有权限")
    f = h.form()
    try:
        cid = int(f.get("clinic_id") or 0)
    except (TypeError, ValueError):
        cid = 0
    if not cid:
        return h.redirect("/desk/quality/new?err=要选门店")
    desc = (f.get("description") or "").strip()
    if len(desc) < 5:
        return h.redirect("/desk/quality/new?err=描述太短，写清楚发生了什么")
    c = B.con()
    n = c.execute("SELECT COUNT(*) FROM QUALITY_INCIDENT").fetchone()[0] + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO QUALITY_INCIDENT(clinic_id, incident_type, description,"
        " occurred_date, severity, status)"
        " VALUES(?,?,?,?,?,?)",
        (cid, f.get("incident_type") or "其他", desc,
         f.get("occurred_date") or B.today(),
         f.get("severity") or "中", "待处理"))
    iid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    c.commit()
    c.close()
    B.audit(sess, "QUALITY_INCIDENT", iid, "insert", None, desc[:40])
    return h.redirect("/desk/quality?ok=已登记，编号 %d" % iid)


def r_quality_close(h, sess, qid):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk/quality?err=没有权限")
    c = B.con()
    c.execute("UPDATE QUALITY_INCIDENT SET status='已闭环' WHERE incident_id=?",
              (int(qid),))
    c.commit()
    c.close()
    B.audit(sess, "QUALITY_INCIDENT", qid, "status", "待处理", "已闭环")
    return h.redirect("/desk/quality?ok=已闭环")


# ------------------------------------------------------------------ 日结对账
def p_daily(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "finance", "admin"):
        return h.redirect("/desk?err=没有权限")
    c = B.con()
    day = _q(sess, "d", B.today())
    cid = B.staff_clinic(sess)
    cond, args = "", []
    if cid and sess["desk"] == "manager":
        cond = " AND c.clinic_id=?"
        args.append(cid)
    rows = c.execute(
        "SELECT COALESCE(c.clinic_name,'未归属门店') clinic_name, p.method,"
        " COUNT(*) n, COALESCE(SUM(p.amount),0) amt"
        " FROM PAYMENT p JOIN INVOICE i ON p.invoice_id=i.invoice_id"
        " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " WHERE IFNULL(p.is_void,0)=0 AND date(p.paid_datetime)=?" + cond +
        " GROUP BY COALESCE(c.clinic_name,'未归属门店'), p.method"
        " ORDER BY clinic_name, amt DESC",
        [day] + args).fetchall()
    tr = [[B.esc(r["clinic_name"]), B.esc(r["method"]), "%d" % r["n"],
           '<span class="money">%s</span>' % B.money(r["amt"])] for r in rows]
    tot = sum(r["amt"] for r in rows)
    # 当天应收 vs 实收
    due = c.execute(
        "SELECT COALESCE(SUM(l.line_subtotal),0) a FROM INVOICE_LINE l"
        " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
        " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " WHERE IFNULL(i.is_void,0)=0 AND date(v.visit_datetime)=?" + cond,
        [day] + args).fetchone()["a"]
    got = c.execute(
        "SELECT COALESCE(SUM(p.amount),0) a FROM PAYMENT p"
        " JOIN INVOICE i ON p.invoice_id=i.invoice_id"
        " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " WHERE IFNULL(p.is_void,0)=0 AND date(p.paid_datetime)=?" + cond,
        [day] + args).fetchone()["a"]
    c.close()
    chips = "".join(
        '<a class="chip %s" href="/desk/daily?d=%s">%s</a>'
        % ("on" if d == day else "", d, d)
        for d in [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                  for i in range(6)])
    body = ('<div class="row"><h1>日结对账</h1>'
            '<a class="btn ghost" href="/desk/daily.csv?d=%s">导出 CSV</a></div>' % day +
            '<div class="rowbar">%s</div>' % chips +
            '<div class="grid g4">%s%s%s%s</div>' % (
                S.stat(B.money(due), "当日应收", "按就诊日期口径"),
                S.stat(B.money(got), "当日实收", "按收款日期口径"),
                S.stat(B.money(due - got), "差额", "应收到账差额"),
                S.stat("%d 笔" % sum(r["n"] for r in rows), "收款笔数", "含多方式")) +
            B.table(["门店", "收款方式", "笔数", "金额"], tr,
                    "这一天没有收款记录") +
            '<p class="tiny">说明：应收按「就诊日期」归集，实收按「收款日期」归集，'
            '两者口径不同，差额里包含以往欠费与预收，不是纯粹的账实不符。</p>')
    return h.send(200, S.page("日结对账", body, sess, "/desk/daily"))


def _clinic_of(sess):
    """店长拿本店 clinic_id；总部/财务返回 None（看全连锁）。

    `r_daily_csv` 原来完全不过滤门店：页面显示城西 16 笔 / 35,050，
    导出的 CSV 却是 45 行、含滨江和余杭——同一个按钮两套口径。
    """
    if not sess or sess.get("desk") != "manager":
        return None
    sid = sess.get("staff_id")
    if not sid:
        return None
    c = B.con()
    r = c.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?", (sid,)).fetchone()
    c.close()
    return r["clinic_id"] if r else None


def r_daily_csv(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "finance", "admin"):
        return h.redirect("/desk?err=没有权限")
    c = B.con()
    day = _q(sess, "d", B.today())
    rows = c.execute(
        "SELECT p.payment_no, p.paid_datetime, p.method, p.amount, i.invoice_no,"
        " c.clinic_name, pt.name pname"
        " FROM PAYMENT p JOIN INVOICE i ON p.invoice_id=i.invoice_id"
        " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN PATIENT pt ON a.patient_id=pt.patient_id"
        " WHERE IFNULL(p.is_void,0)=0 AND date(p.paid_datetime)=?"
        + (" AND v.clinic_id=?" if _clinic_of(sess) else "")
        + " ORDER BY p.paid_datetime",
        ((day, _clinic_of(sess)) if _clinic_of(sess) else (day,))).fetchall()
    c.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["收款单号", "收款时间", "方式", "金额", "结算单号", "门店", "患者"])
    for r in rows:
        w.writerow([r["payment_no"], r["paid_datetime"], r["method"], r["amount"],
                    r["invoice_no"], r["clinic_name"], r["pname"] or ""])
    data = buf.getvalue().encode("utf-8-sig")     # BOM，Excel 打开不乱码
    h.send_response(200)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition",
                  'attachment; filename="daily-%s.csv"' % day)
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)


# -------------------------------------------------------------------- 导出
EXPORTS = {
    "patients": ("患者名单",
                 "SELECT p.patient_no 病历号, p.name 姓名, p.phone 电话,"
                 " p.date_of_birth 出生日期, p.insurance_card_no 医保卡号,"
                 " p.source_channel 来源, p.first_visit_date 初诊日期,"
                 " p.emergency_contact_name 紧急联系人, p.emergency_contact_phone 紧急联系电话"
                 " FROM PATIENT p ORDER BY p.patient_no",
                 ["病历号", "姓名", "电话", "出生日期", "医保卡号", "来源", "初诊日期",
                  "紧急联系人", "紧急联系电话"]),
    "appointments": ("预约明细",
                     "SELECT a.appointment_no 预约号, a.appointment_datetime 时间, a.status 状态,"
                     " p.name 患者, d.name 牙医, c.clinic_name 门店, a.visit_reason 就诊原因"
                     " FROM APPOINTMENT a LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                     " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
                     " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
                     " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
                     " WHERE IFNULL(a.is_void,0)=0 ORDER BY a.appointment_datetime DESC LIMIT 5000",
                     ["预约号", "时间", "状态", "患者", "牙医", "门店", "就诊原因"]),
    "invoices": ("结算单",
                 "SELECT i.invoice_no 单号, i.invoice_date 开单日期,"
                 " (SELECT COALESCE(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
                 "   WHERE l.invoice_id=i.invoice_id) 应收,"
                 " (SELECT COALESCE(SUM(pm.amount),0) FROM PAYMENT pm"
                 "   WHERE pm.invoice_id=i.invoice_id AND IFNULL(pm.is_void,0)=0) 已收,"
                 " i.status 状态, p.name 患者, c.clinic_name 门店"
                 " FROM INVOICE i LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
                 " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                 " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                 " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
                 " WHERE IFNULL(i.is_void,0)=0 ORDER BY i.invoice_date DESC LIMIT 5000",
                 ["单号", "开单日期", "应收", "已收", "状态", "患者", "门店"]),
    "stock": ("库存（按门店）",
              "SELECT c.clinic_name 门店, m.material_code 编码, m.material_name 名称,"
              " m.unit 单位, CASE WHEN m.is_high_value=1 THEN '是' ELSE '否' END 高值,"
              " SUM(s.on_hand_qty) 结存量,"
              " CASE WHEN SUM(s.on_hand_qty) <= CAST(m.reorder_point AS REAL) THEN '需补'"
              "      ELSE '' END 提示, m.reorder_point 补货点"
              " FROM STOCK_LEDGER s"
              " JOIN MATERIAL m ON m.material_id=s.material_id"
              " JOIN CLINIC c ON c.clinic_id=s.clinic_id"
              " WHERE IFNULL(s.is_void,0)=0"
              " GROUP BY c.clinic_id, s.material_id"
              " ORDER BY c.clinic_id, m.material_code",
              ["门店", "编码", "名称", "单位", "高值", "结存量", "提示", "补货点"]),
}


def r_export_csv(h, sess, kind):
    if not sess:
        return h.redirect("/login")
    if kind not in EXPORTS:
        return h.redirect("/desk?err=不支持这种导出")
    name, sql, heads = EXPORTS[kind]
    if sess["desk"] not in ("hq", "ops", "finance", "admin"):
        return h.redirect("/desk?err=只有总部和财务可以导出")
    c = B.con()
    rows = c.execute(sql).fetchall()
    c.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(heads)
    for r in rows:
        w.writerow(["" if v is None else v for v in tuple(r)])
    data = buf.getvalue().encode("utf-8-sig")
    h.send_response(200)
    h.send_header("Content-Type", "text/csv; charset=utf-8")
    h.send_header("Content-Disposition",
                  'attachment; filename="%s-%s.csv"'
                  % (kind, datetime.now().strftime("%Y%m%d")))
    h.send_header("Content-Length", str(len(data)))
    h.end_headers()
    h.wfile.write(data)
