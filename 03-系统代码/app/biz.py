import sys
import time
# -*- coding: utf-8 -*-
"""六个角色的业务功能。

单独成文件的原因：server.py 已有 1000 行基础设施（认证、会话、样式、路由），
业务功能再堆进去会到 3000 行，改一处要滚很久。这里只依赖 server 暴露的
db / page / route / stat / badge / count / fmt_dt / flash_ok / flash_err。

角色 -> 桌面（DESK）映射在 server.py：patient / frontdesk / doctor /
assistant / manager / hq。财务与总部运营共用 hq 桌面，靠 role 区分菜单。
"""
import html
import math
import sqlite3
from datetime import date, datetime, timedelta

# 同一个「现在」：今天已结束的时段不再出现在列表里，
# 否则会出现「列表显示剩 N 位、点进去说已经过去了」。
_T = datetime.now().date().isoformat()
_HM = datetime.now().strftime("%H:%M")

S = None  # 由 register(mod) 注入

EXTRA_CSS = """
.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th{text-align:left;font-weight:600;color:#6b7280;font-size:12.5px;
  padding:10px 12px;border-bottom:1px solid #e8eaee;background:#fbfcfd}
.tbl td{padding:11px 12px;border-bottom:1px solid #f1f2f5;vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}
.panel{background:#fff;border:1px solid #e8eaee;border-radius:12px;
  overflow:hidden;margin-bottom:18px}
.panel h3{margin:0;padding:14px 18px;font-size:15px;border-bottom:1px solid #f1f2f5;
  display:flex;justify-content:space-between;align-items:center}
.panel .bd{padding:16px 18px}
.f{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.f label{font-size:13px;color:#4b5563}
.f input,.f select,.f textarea{border:1px solid #d7dbe2;border-radius:8px;
  padding:9px 11px;font-size:14px;font-family:inherit;background:#fff}
.f textarea{width:100%;min-height:72px;resize:vertical}
.f2{display:grid;grid-template-columns:1fr 1fr;gap:14px 22px}
.kv{display:grid;grid-template-columns:110px 1fr;gap:9px 14px;font-size:14px;margin:0}
.kv dt{color:#6b7280}
.kv dd{margin:0}
h2.sec{font-size:16px;margin:24px 0 12px}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid #d7dbe2;border-radius:8px;padding:7px 13px;font-size:13.5px;
  background:#fff;color:#1f2937;text-decoration:none}
.chip:hover{border-color:#9db8e8;text-decoration:none}
.chip.on{background:#1d6fd8;border-color:#1d6fd8;color:#fff}
.chip.off{color:#b6bcc6;background:#f7f8fa}
"""


# ------------------------------------------------------------------ 小工具
def con():
    return S.db()


def next_no(c, name, prefix, start):
    """原子发号：单号不能从业务键派生，否则并发/重号是必然的。

    SQLite 的 INSERT ... ON CONFLICT DO UPDATE 是单条原子语句，
    两个连接同时发号也只会拿到不同的值（后到的等前一个提交）。
    """
    c.execute("INSERT INTO SEQ(name, val) VALUES(?, ?)"
              " ON CONFLICT(name) DO UPDATE SET val=val+1", (name, start + 1))
    v = c.execute("SELECT val FROM SEQ WHERE name=?", (name,)).fetchone()[0]
    return "%s%06d" % (prefix, v)


def today():
    return date.today().isoformat()


def esc(x):
    return html.escape("" if x is None else str(x))


def hhmm(s):
    return (s or "")[11:16]


def ymd(s):
    return (s or "")[:10]


def table(head, rows, empty="暂无记录"):
    if not rows:
        return '<p class="muted">%s</p>' % esc(empty)
    th = "".join("<th>%s</th>" % esc(c) for c in head)
    tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    return ('<table class="tbl"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table>') % (th, tr)


def panel(title, inner, right=""):
    return ('<div class="panel"><h3><span>%s</span><span>%s</span></h3>'
            '<div class="bd">%s</div></div>') % (esc(title), right, inner)


def btn(text, href, cls="btn sm"):
    return '<a class="%s" href="%s">%s</a>' % (cls, href, esc(text))


def post_btn(text, action, cls="btn sm", confirm=None):
    on = ' onsubmit="return confirm(\'%s\')"' % confirm if confirm else ""
    return ('<form method="post" action="%s" style="display:inline;margin:0"%s>'
            '<button class="%s">%s</button></form>') % (action, on, cls, esc(text))


# 收款方式写死成枚举，避免有人往库里塞任意字符串（验收报告 A2）
PAY_METHODS = ("现金", "银行卡", "微信", "支付宝", "保险直付")

# 发票（结算单）状态：由收款金额推导，不手工指定
INV_STATUS = ("待收款", "部分收款", "已收款")


def num(x):
    # Python 的 % 格式化不支持 "%,.0f"（千分位只有 str.format 才有）。
    # 原先写 "%,.0f" % float(x) 会抛 ValueError，被下面 except 吞成 "0"，
    # 造成全站金额一律显示 0。必须用 {:,.0f}。
    try:
        v = float(x)
        return "{:,.0f}".format(v) if abs(v) >= 1000 else ("%g" % v)
    except (TypeError, ValueError):
        return "0"


def inv_due(c, iid):
    """某张结算单的应收（明细合计）。不读 INVOICE.status——那个字段只在写操作后同步，
    历史上曾与金额脱钩（146 张「已收款」实际零收款），读的时候一律按金额重算。"""
    return float(c.execute(
        "SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE WHERE invoice_id=?",
        (iid,)).fetchone()[0])


def inv_paid(c, iid):
    """某张结算单的已收（非作废 PAYMENT 合计）。"""
    return float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
        " WHERE invoice_id=? AND IFNULL(is_void,0)=0", (iid,)).fetchone()[0])


def inv_state(due, paid):
    """按金额算状态，供列表/看板/详情统一使用。"""
    if due <= 0.01:
        return "已收款"
    if paid <= 0.01:
        return "待收款"
    return "已收款" if paid + 0.01 >= due else "部分收款"


def money(x):
    try:
        return "{:,.0f}".format(float(x))
    except (TypeError, ValueError):
        return "0"


def money_float(x):
    # 钱只记到分。0.001 元写进来会让「已收」与明细永远差一点，
    # 状态判定也就永远差一点。
    try:
        return round(float(x or 0) + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


def m2(x):
    """金额一律两位小数。0.1+0.2=0.30000000000000004 这类误差不进库。"""
    try:
        return round(float(x) + 1e-9, 2)
    except (TypeError, ValueError):
        return 0.0


def ti_price(it):
    """治疗项目的单价：谈定价优先，没有再回落到标准价。"""
    v = it["agreed_price"] if it["agreed_price"] is not None else it["standard_unit_price"]
    return money_float(v)


def ti_amount(it):
    # 金额只保留两位：明细、应收、收款判断全从这一个口出
    return m2(ti_price(it) * float(it["standard_units"] or 1))


def staff_clinic(sess):
    """当前员工所属门店；总部与财务没有门店，返回 None。"""
    sid = sess.get("staff_id")
    if not sid:
        return None
    c = con()
    r = c.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?", (sid,)).fetchone()
    c.close()
    return r[0] if r else None


def _notify_stop(con, aid, d0, t0, d1, t1):
    """牙医停诊把患者的预约取消掉，必须主动告诉他，否则人到了才发现没医生。

    返回 True 表示确实写了一条通知。写通知用独立连接并在失败时重试：
    调用方刚 commit 过停诊与取消，同一个连接上再写容易撞上写锁。
    """
    try:
        r = con.execute(
            "SELECT a.patient_id, a.appointment_datetime, r.clinic_id"
            " FROM APPOINTMENT a LEFT JOIN ROSTER r ON r.roster_id=a.roster_id"
            " WHERE a.appointment_id=?", (aid,)).fetchone()
        if not r:
            return False
        acc = con.execute("SELECT account_id FROM PATIENT WHERE patient_id=?",
                          (r["patient_id"],)).fetchone()
        if not acc or not acc["account_id"]:
            return False
        when = (r["appointment_datetime"] or "")[:16]
        body = ("%s 的预约因接诊牙医请假（%s %s 至 %s %s）取消，"
                "给您带来不便。可以重新预约，或打门店电话改约。"
                % (when, d0, t0 or "全天", d1, t1 or "全天"))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("[notify_stop] 读取失败 %s\n" % e)
        return False

    for _ in range(3):
        try:
            # 注意：参数名 con 遮蔽了模块级的 con()，这里必须用 con_db()。
            w = con_db()
            w.execute(
                "INSERT INTO NOTICE(account_id, patient_id, kind, title, body,"
                " ref_table, ref_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (acc["account_id"], r["patient_id"], "停诊",
                 "您的预约已因医生停诊取消", body, "APPOINTMENT", aid,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            w.commit()
            w.close()
            return True
        except Exception as e:  # noqa: BLE001
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.05)
            sys.stderr.write("[notify_stop] 写通知重试 %s\n" % e)
    return False


def my_patients(sess):
    """当前账号名下的患者 id 列表。一个账号可以挂多个家人档案。"""
    if not sess:
        return []
    c = con()
    rows = c.execute("SELECT patient_id FROM PATIENT WHERE account_id=?",
                     (sess.get("account_id"),)).fetchall()
    c.close()
    return [r[0] for r in rows]


def own_appt(sess, aid):
    """这条预约是不是当前账号名下患者的——患者端每个写操作都要先过这一关。"""
    c = con()
    r = c.execute("SELECT patient_id FROM APPOINTMENT WHERE appointment_id=?",
                  (int(aid),)).fetchone()
    c.close()
    return bool(r) and r[0] in my_patients(sess)


def same_clinic(sess, aid=None, vid=None, inv=None, cid=None):
    """员工只能操作本店的预约/就诊/结算单；总部与财务不受限（返回 True）。

    cid 用于「手里已经拿到门店 id」的场合（排班、征调单、门店维护），不必再查一遍。
    """
    mine = staff_clinic(sess)
    if mine is None:
        return True
    if cid is not None:
        return int(cid) == int(mine)
    c = con()
    try:
        if aid is not None:
            r = c.execute(
                "SELECT r.clinic_id FROM APPOINTMENT a"
                " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
                " WHERE a.appointment_id=?", (int(aid),)).fetchone()
        elif vid is not None:
            r = c.execute("SELECT clinic_id FROM VISIT WHERE visit_id=?",
                          (int(vid),)).fetchone()
        elif inv is not None:
            r = c.execute(
                "SELECT v.clinic_id FROM INVOICE i"
                " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
                " WHERE i.invoice_id=?", (int(inv),)).fetchone()
        else:
            return True
    finally:
        c.close()
    return bool(r) and int(r[0] or 0) == int(mine)


def con_db():
    return con()


def audit(sess, table, ref, field, old, new, patient_id=None, con=None):
    """写一条审计。所有改动病历/钱/审批的操作都应该留痕，出事能追。

    给了 con 就用它（调用方自己的事务），没给才单开一个连接。
    注意：调用方如果还持有写锁，这里另开连接会 database is locked，
    所以调用点一律放在 commit/close 之后，或者把 c 传进来。
    """
    sql = ("INSERT INTO AUDIT_LOG(patient_id, record_table, record_id_ref,"
           " changed_field, old_value, new_value, operator_name, changed_datetime)"
           " VALUES(?,?,?,?,?,?,?,?)")
    args = (patient_id, table, str(ref), field,
            None if old is None else str(old)[:200],
            None if new is None else str(new)[:200],
            (sess or {}).get("display") or (sess or {}).get("login_name") or "system",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    for attempt in range(3):
        c = con
        own = c is None
        try:
            if own:
                c = con_db()
            c.execute(sql, args)
            if own:
                c.commit()
            return
        except Exception as e:
            if own and c is not None:
                try:
                    c.rollback()
                except Exception:
                    pass
            if attempt == 2:
                sys.stderr.write("audit 失败: %r\n" % (e,))
            else:
                time.sleep(0.05 * (attempt + 1))
        finally:
            if own and c is not None:
                try:
                    c.close()
                except Exception:
                    pass


def own_visit(sess, vid):
    """这次就诊能不能由当前账号写。

    牙医没有 staff_id（DENTIST 是独立表，且门店归属在 ROSTER 上），
    所以 staff_clinic() 对牙医恒返回 None、same_clinic() 恒真，
    结果是任何牙医、甚至患者都能改别人的病历（验收报告 A6）。
    这里按「就诊 → 预约 → 排班 → 牙医」查真正的接诊医生。
    """
    role = sess.get("role")
    # 病历只能由接诊医生本人写。前台/店长/总部**读**没问题（会诊、质控、纠纷调查
    # 都要看），但写不行——医疗文书被非医生改写是查不回来的。只有管理员保留兜底能力。
    if role == "admin":
        return True
    if role not in ("dentist", "patient"):
        return False
    c = con()
    r = c.execute(
        "SELECT a.patient_id, ro.dentist_id, v.clinic_id FROM VISIT v"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN ROSTER ro ON a.roster_id=ro.roster_id"
        " WHERE v.visit_id=?", (int(vid),)).fetchone()
    c.close()
    if not r:
        return False
    if role == "dentist":
        if int(r["dentist_id"] or 0) != int(sess.get("dentist_id") or 0):
            return False
        return True
    if role == "patient":
        return int(r["patient_id"] or 0) in my_patients(sess)
    return False


def deny(h, back, msg="没有权限操作这一条"):
    sep = "&" if "?" in back else "?"
    return h.redirect(back + sep + "err=" + msg)


def own_row(sess, table, key, ccol, val):
    """行级归属：这张表这一行是不是本店的（店长只能批自己店的）。"""
    cid = staff_clinic(sess)
    if cid is None:
        return True
    c = con()
    try:
        r = c.execute("SELECT %s FROM %s WHERE %s=?" % (ccol, table, key),
                      (int(val),)).fetchone()
    finally:
        c.close()
    return bool(r) and int(r[0] or 0) == int(cid)


def clinic_name(cid):
    c = con()
    r = c.execute("SELECT clinic_name FROM CLINIC WHERE clinic_id=?", (cid,)).fetchone()
    c.close()
    return r[0] if r else "—"


def flash(sess, key):
    """一次性提示：借 session 的 query 传，简单起见用 ?ok= / ?err= 读 URI。"""
    return ""


# ------------------------------------------------------------------ 患者
def p_visit_detail(sess, vid):
    conX = con()
    v = conX.execute(
        "SELECT v.*, a.patient_id, p.name AS pname, p.phone, d.name AS dname,"
        " c.clinic_name FROM VISIT v"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " WHERE v.visit_id=?", (vid,)).fetchone()
    if not v:
        conX.close()
        return None
    items = conX.execute(
        "SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
        " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
        " WHERE i.visit_id=?", (vid,)).fetchall()
    inv = conX.execute("SELECT * FROM INVOICE WHERE visit_id=?", (vid,)).fetchone()
    lines, pays = [], []
    if inv:
        lines = conX.execute(
            "SELECT * FROM INVOICE_LINE WHERE invoice_id=? ORDER BY line_no",
            (inv["invoice_id"],)).fetchall()
        pays = conX.execute(
            "SELECT * FROM PAYMENT WHERE invoice_id=?", (inv["invoice_id"],)).fetchall()
    conX.close()

    kv = [("就诊时间", esc(S.fmt_dt(v["visit_datetime"]))),
          ("门店", esc(v["clinic_name"])),
          ("牙医", esc(v["dname"])),
          ("就诊编号", "V%05d" % v["visit_no"] if v["visit_no"] else "—")]
    body = panel("就诊信息", '<dl class="kv">%s</dl>' % "".join(
        "<dt>%s</dt><dd>%s</dd>" % (a, b) for a, b in kv))

    med = [("主诉", v["chief_complaint"]), ("现病史", v["present_history"]),
           ("检查所见", v["examination"]), ("诊断", v["diagnosis"]),
           ("处置记录", v["treatment_note"]), ("备注", v["special_notes"])]
    body += panel("病历", '<dl class="kv">%s</dl>' % "".join(
        "<dt>%s</dt><dd>%s</dd>" % (a, esc(b) if b else '<span class="muted">未填写</span>')
        for a, b in med))

    rows = []
    for it in items:
        rows.append([esc(it["item_name"]), esc(it["tooth_fdi"] or "—"),
                     num(it["standard_units"] or 1), money(ti_price(it)),
                     money(ti_amount(it))])
    body += panel("治疗项目", table(["项目", "牙位", "数量", "单价", "小计"], rows))

    if inv:
        lrows = [[esc(l["item_name"]), num(l["units_used"] or 1),
                  money(l["unit_price"]), money(l["line_subtotal"])] for l in lines]
        prows = [[esc(p["payment_no"]), esc(p["method"]),
                  money(p["amount"]), esc(ymd(p["paid_datetime"]))] for p in pays]
        body += panel("结算单 %s" % esc(inv["invoice_no"]),
                      table(["项目", "数量", "单价", "金额"], lrows) +
                      "<h2 class=\"sec\">收款记录</h2>" +
                      table(["收款单号", "方式", "金额", "日期"], prows),
                      right='<span class="badge %s">%s</span>' % (
                          "g" if inv["status"] == "已收款" else "y", esc(inv["status"])))
    return S.page("就诊详情", body, sess, "/me/visits")


def r_visit_detail(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    v = h_get_visit(int(vid))
    if not v or not h_can_see(sess, v):
        return h.send(403, S.page("无权查看", '<div class="msg err">这次就诊不属于你。</div>', sess))
    return h.send(200, p_visit_detail(sess, int(vid)))


def h_get_visit(vid):
    c = con()
    r = c.execute("SELECT v.visit_id, a.patient_id FROM VISIT v"
                  " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                  " WHERE v.visit_id=?", (vid,)).fetchone()
    c.close()
    return r


def h_can_see(sess, row):
    if sess["role"] in ("ops", "finance", "supervisor", "receptionist"):
        return True
    if sess["role"] == "dentist":
        return True
    return row[1] in (sess.get("patient_ids") or [])



# ---------------------------------------------------------------- 预约状态机
# 占号口径：只有「已预约」和「已到诊」占号。已取消、爽约都释放号——爽约的人
# 没来，那个位置当天可以给别人；已到诊的人确实用过这个号。
OCCUPIED = "IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')"

APPT_FINAL = {"已到诊", "已取消", "爽约"}
ACT_CN = {"cancel": "取消", "reschedule": "改约",
          "checkin": "登记到诊", "noshow": "记爽约"}


def appt_block(a, act):
    """这条预约能不能做 act。能返回 None，不能返回中文理由。

    状态机只有一条规则：**只有「已预约」能流转**，其余三个都是终态。
    已到诊要退号得走退费作废（另开单据），不能把就诊记录取消掉；
    已取消要重新约就新建一条，不能把旧记录「复活」——否则 is_void=1
    与 status=已预约 会同时成立，到诊时被拒，患者与前台都看不懂。
    """
    if a is None:
        return "这条预约不存在"
    st = a["status"] or "已预约"
    if st in APPT_FINAL:
        return "这条预约已经是「%s」，不能再%s" % (st, ACT_CN.get(act, "操作"))
    if (a["is_void"] or 0) == 1:
        return "这条预约已作废（%s），不能再%s" % (a["void_reason"] or "无原因",
                                                 ACT_CN.get(act, "操作"))
    return None


def appt_row(c, aid):
    return c.execute("SELECT * FROM APPOINTMENT WHERE appointment_id=?",
                     (int(aid),)).fetchone()

def p_reschedule(sess, aid, err="", day=None, clinic=None):
    c = con()
    a = c.execute(
        "SELECT a.*, p.name AS pname, c.clinic_name, d.name AS dname,"
        " r.slot_start, r.slot_end, r.roster_date FROM APPOINTMENT a"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE a.appointment_id=?", (aid,)).fetchone()
    if not a:
        c.close()
        return None
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(14)]
    d = day or (datetime.now() + timedelta(days=1)).date().isoformat()
    if d not in days:
        d = days[1]
    r0 = c.execute("SELECT clinic_id FROM ROSTER WHERE roster_id=?",
                   (a["roster_id"],)).fetchone()
    cid0 = r0["clinic_id"] if r0 else 1          # 原门店
    # 换门店：?c=N 指定看哪家；不指定就是原门店
    try:
        cid = int(clinic) if clinic else cid0
    except ValueError:
        cid = cid0
    clinics = c.execute(
        "SELECT clinic_id, clinic_name, region FROM CLINIC ORDER BY clinic_id").fetchall()
    if not any(x["clinic_id"] == cid for x in clinics):
        cid = cid0
    rows = c.execute(
        "SELECT r.roster_id, r.slot_start, r.slot_end, d.name AS dn,"
        " r.slot_capacity - (SELECT COUNT(*) FROM APPOINTMENT x"
        "   WHERE x.roster_id=r.roster_id AND IFNULL(x.is_void,0)=0"
        "   AND x.status IN ('已预约','已到诊')) AS left_n"
        " FROM ROSTER r LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE r.clinic_id=? AND r.roster_date=?"
        "   AND IFNULL(r.is_reserved,0)=0"
        "   AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
        "   AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))"
        " ORDER BY r.slot_start", (cid, d, _T, _T, _HM)).fetchall()
    c.close()

    chips = "".join(
        '<a class="chip %s" href="/me/reschedule/%d?d=%s&c=%d">%s</a>'
        % ("on" if x == d else "", aid, x, cid, x[5:]) for x in days[:7])
    cchips = "".join(
        '<a class="chip %s" href="/me/reschedule/%d?d=%s&c=%d">%s</a>'
        % ("on" if x["clinic_id"] == cid else "", aid, d, x["clinic_id"],
           esc(x["clinic_name"])) for x in clinics)
    sl = []
    for r in rows:
        left = int(r["left_n"] or 0)
        if left <= 0:
            continue
        sl.append('<tr><td>%s — %s</td><td>%s</td><td>剩 %d 位</td><td>%s</td></tr>' % (
            esc(r["slot_start"]), esc(r["slot_end"]), esc(r["dn"]), left,
            ('<form method="post" action="/me/reschedule/%d" style="margin:0">'
             '<input type="hidden" name="roster_id" value="%d">'
             '<input type="hidden" name="date" value="%s">'
             '<input type="hidden" name="clinic_id" value="%d">'
             '<button class="btn sm">改到这一场</button></form>'
             % (aid, r["roster_id"], d, cid))))
    cur = ("原预约：%s %s — %s　%s　%s" % (
        esc(ymd(a["appointment_datetime"])), esc(hhmm(a["appointment_datetime"])),
        esc(a["slot_end"] or ""), esc(a["clinic_name"]), esc(a["dname"])))
    same = (cid == cid0)
    hint = ("" if same else
            '<p class="sub" style="margin:0 0 10px">换到别的门店后，原门店的号会释放，'
            '新门店的时段立即占用；牙医可能不是同一位。</p>')
    body = (S.flash_err(err) +
            panel("当前预约", '<p>%s</p>' % cur) +
            panel("选择新时段",
                  '<div class="muted" style="margin-bottom:6px">门店</div>'
                  '<div class="chips" style="margin-bottom:14px">%s</div>'
                  '<div class="muted" style="margin-bottom:6px">日期</div>'
                  '<div class="chips" style="margin-bottom:10px">%s</div>%s'
                  '<table class="tbl"><thead><tr><th>时段</th><th>牙医</th>'
                  '<th>余位</th><th></th></tr></thead><tbody>%s</tbody></table>'
                  % (cchips, chips, hint,
                     "".join(sl) or '<tr><td colspan="4" class="muted">这天已无余位</td></tr>'),
                  right=btn("返回我的预约", "/me/appointments", "btn ghost sm")))
    return S.page("改约", body, sess, "/me/appointments")


def r_reschedule_form(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    # 只能改自己的预约；日期取页面上的 ?d=，否则点哪一天都看到同一天
    if not own_appt(sess, aid):
        return deny(h, "/me/appointments")
    day = h.qs("d") if hasattr(h, "qs") else None
    if not day:
        mo = None
        import urllib.parse as _u
        _q = _u.parse_qs(_u.urlparse(sess.get("_path") or "").query)
        day = (_q.get("d") or [None])[0]
    cl = None
    try:
        _q2 = _u.parse_qs(_u.urlparse(sess.get("_path") or "").query)
        cl = (_q2.get("c") or [None])[0]
    except Exception:
        cl = None
    p = p_reschedule(sess, int(aid), day=day, clinic=cl)
    if p is None:
        return h.redirect("/me/appointments")
    return h.send(200, p)


def r_reschedule_do(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    if not own_appt(sess, aid):
        return deny(h, "/me/appointments")
    f = h.form()
    rid = int(f.get("roster_id") or 0)
    d = f.get("date") or today()
    c = con()
    _old = appt_row(c, aid)
    old_rid = _old["roster_id"] if _old else None
    bad = appt_block(_old, "reschedule")
    if bad:
        c.close()
        return h.redirect("/me/appointments?err=" + S.quote(bad))
    r = c.execute("SELECT * FROM ROSTER WHERE roster_id=?"
                  " AND IFNULL(is_void,0)=0 AND IFNULL(is_published,1)=1",
                  (rid,)).fetchone()
    if not r:
        c.close()
        return h.redirect("/me/reschedule/%d?err=这个时段不存在或已停诊" % int(aid))
    used = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=? AND IFNULL(is_void,0)=0"
                     " AND status IN ('已预约','已到诊') AND appointment_id<>?", (rid, int(aid))).fetchone()[0]
    cap = c.execute("SELECT slot_capacity FROM ROSTER WHERE roster_id=?", (rid,)).fetchone()[0]
    if used >= int(cap or 0):
        c.close()
        return h.redirect("/me/reschedule/%d?err=这个时段刚被约满" % int(aid))
    cur = c.execute("UPDATE APPOINTMENT SET roster_id=?, appointment_datetime=?"
                    " WHERE appointment_id=? AND status='已预约'"
                    " AND IFNULL(is_void,0)=0",
                    (rid, "%s %s:00" % (d, r["slot_start"]), int(aid)))
    if cur.rowcount != 1:
        c.rollback()
        c.close()
        return h.redirect("/me/appointments?err=这条预约状态已经变了，改约没生效")
    audit(sess, "APPOINTMENT", int(aid), "roster_id", old_rid, rid, con=c)
    c.commit()
    c.close()
    return h.redirect("/me/appointments")


# ------------------------------------------------------------------ 前台
def p_queue(sess, d=None, q=""):
    d = d or today()
    c = con()
    cid = staff_clinic(sess)
    wh, args = ["date(a.appointment_datetime)=?"], [d]
    if cid:
        wh.append("r.clinic_id=?")
        args.append(cid)
    rows = c.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name AS pname,"
        " p.phone, d.name AS dname, c.clinic_name, r.slot_end, v.visit_id"
        " FROM APPOINTMENT a"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " WHERE " + " AND ".join(wh) + " ORDER BY a.appointment_datetime", tuple(args)).fetchall()
    c.close()
    out = []
    for r in rows:
        aid = r["appointment_id"]
        act = ""
        if r["status"] == "已预约":
            act = (post_btn("登记到诊", "/desk/checkin/%d" % aid, confirm="确认患者已到店？")
                   + " " + btn("改约", "/desk/reschedule/%d" % aid, "btn ghost sm")
                   + " " + post_btn("爽约", "/desk/noshow/%d" % aid, "btn ghost sm",
                                    confirm="确认这位患者没来？记爽约会把号让出来。")
                   + " " + post_btn("取消", "/desk/cancel/%d" % aid, "btn ghost sm",
                                    confirm="确认取消这条预约？"))
        elif r["status"] in ("爽约", "已取消"):
            # 取消/爽约的号已经释放，不能再登记到诊；但如果这个人当天确实看过
            # （异常取消、补登记之类），结算单还是要能开出来。
            act = (btn("已到诊·开结算单", "/desk/invoice/%d" % r["visit_id"], "btn ghost sm")
                   if r["visit_id"] else '<span class="muted">号已释放</span>')
        elif r["visit_id"]:
            act = btn("开结算单", "/desk/invoice/%d" % r["visit_id"])
        out.append([esc(hhmm(r["appointment_datetime"])), esc(r["pname"]),
                    esc(r["phone"] or "—"), esc(r["clinic_name"]), esc(r["dname"]),
                    S.badge(r["status"]), act])
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(7)]
    chips = "".join('<a class="chip %s" href="/desk/appointments?d=%s">%s</a>'
                    % ("on" if x == d else "", x, x[5:]) for x in days)
    body = panel("%s 预约队列" % d, '<div class="chips" style="margin-bottom:14px">%s</div>'
                 "<p class=\"muted\">患者到店后点「登记到诊」，系统会为这次预约建一条就诊记录，"
                 "牙医就能在诊台里写病历。</p>" % chips, right=btn("散客挂号", "/desk/walkin"))
    body += table(["时间", "患者", "电话", "门店", "牙医", "状态", "操作"], out)
    return S.page("预约排队", body, sess, "/desk/appointments")


def r_queue2(h, sess):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    d = (qs.get("d") or [today()])[0]
    return h.send(200, p_queue(sess, d))


def r_checkin(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    if not same_clinic(sess, aid=aid):
        return deny(h, "/desk/appointments")
    c = con()
    a = c.execute(
        "SELECT a.*, r.roster_date, r.clinic_id FROM APPOINTMENT a"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " WHERE a.appointment_id=?", (int(aid),)).fetchone()
    if not a:
        c.close()
        return h.redirect("/desk/appointments")
    # 到诊必须真的能到：已取消/已作废的号不能复活，只能登记当天，一条预约只建一条病历。
    # 早先这里什么都不查，一个月前的取消号点一下就能"到诊"，还能重复点出多条 VISIT。
    if (a["is_void"] or 0) or a["status"] in ("已取消", "已作废"):
        c.close()
        return deny(h, "/desk/appointments", msg="这条预约已经取消了，不能登记到诊")
    if a["status"] == "已到诊":
        c.close()
        return deny(h, "/desk/appointments", msg="这条预约已经登记过到诊了")
    # 未来日期的预约不能提前登记到诊；过去日期允许补登记（漏登记的情况真实存在）。
    if a["roster_date"] and a["roster_date"] > today():
        c.close()
        return deny(h, "/desk/appointments",
                    msg="这条预约是 %s 的，还没到日子，不能现在登记到诊" % a["roster_date"])
    if c.execute("SELECT COUNT(*) FROM VISIT WHERE appointment_id=?",
                 (int(aid),)).fetchone()[0]:
        c.close()
        return deny(h, "/desk/appointments", msg="这条预约已经有就诊记录了")
    cid = a["clinic_id"] or 1
    # 并发兜底：两个前台同时点「登记到诊」时，上面的 SELECT 都会说「还没有就诊记录」，
    # 于是都往下插。VISIT(appointment_id) 上的唯一索引让第二个 INSERT 直接抛
    # IntegrityError——这里接住它，当成「已经有人登记过了」，而不是 500。
    try:
        n = c.execute("SELECT IFNULL(MAX(visit_no),30000)+1 FROM VISIT").fetchone()[0]
        c.execute("INSERT INTO VISIT(visit_no, appointment_id, clinic_id,"
                  " visit_datetime, treated) VALUES(?,?,?,?,0)",
                  (n, int(aid), cid, a["appointment_datetime"]))
        c.execute("UPDATE APPOINTMENT SET status='已到诊'"
                  " WHERE appointment_id=? AND status='已预约'", (int(aid),))
        c.commit()
    except sqlite3.IntegrityError:
        c.rollback()
        c.close()
        return deny(h, "/desk/appointments", msg="这条预约已经有人登记过到诊了")
    c.close()
    audit(sess, "APPOINTMENT", aid, "status", "已预约", "已到诊")
    return h.redirect("/desk/appointments")


def p_desk_reschedule(sess, aid, day=None, err=""):
    """前台代客改约：跟患者端同一套时段规则，但可以替任意本店患者改。"""
    aid = int(aid)
    if not same_clinic(sess, aid=aid):
        return S.page("没有权限", '<h1>没有权限</h1><p class="sub">这条预约不在你的门店。</p>',
                      sess, "/desk/appointments")
    c = con()
    a = c.execute(
        "SELECT a.*, p.name AS pname, r.clinic_id, r.dentist_id, r.roster_date,"
        " d.name AS dname, cl.clinic_name FROM APPOINTMENT a"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC cl ON r.clinic_id=cl.clinic_id"
        " WHERE a.appointment_id=?", (int(aid),)).fetchone()
    if not a:
        c.close()
        return S.page("找不到预约", '<h1>找不到这条预约</h1>', sess, "/desk/appointments")
    day = day or a["roster_date"] or today()
    slots = c.execute(
        "SELECT r.roster_id, r.slot_start, r.slot_end, r.slot_capacity, d.name AS dname,"
        " (SELECT COUNT(*) FROM APPOINTMENT x WHERE x.roster_id=r.roster_id"
        "   AND IFNULL(x.is_void,0)=0 AND x.status IN ('已预约','已到诊')) AS used"
        " FROM ROSTER r JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE r.clinic_id=? AND r.roster_date=? AND IFNULL(r.is_void,0)=0"
        "   AND IFNULL(r.is_published,1)=1 AND r.slot_capacity >"
        "     (SELECT COUNT(*) FROM APPOINTMENT x WHERE x.roster_id=r.roster_id"
        "      AND IFNULL(x.is_void,0)=0 AND x.status IN ('已预约','已到诊'))"
        " ORDER BY r.slot_start, d.name", (a["clinic_id"], day)).fetchall()
    c.close()
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(14)]
    chips = "".join('<a class="chip %s" href="/desk/reschedule/%d?d=%s">%s</a>'
                    % ("on" if x == day else "", aid, x, x[5:]) for x in days)
    rows = []
    for s0 in slots:
        rows.append([esc(s0["slot_start"] + "—" + s0["slot_end"]), esc(s0["dname"]),
                     "%d/%d" % (s0["used"], s0["slot_capacity"]),
                     '<form method="post" action="/desk/reschedule/%d" style="margin:0">'
                     '<input type="hidden" name="roster_id" value="%d">'
                     '<button class="btn sm">改到这儿</button></form>'
                     % (aid, s0["roster_id"])])
    body = S.flash_err(err)
    body += panel("把「%s」的预约改到别的时段" % (a["pname"] or "这位患者"),
                  '<p class="muted">当前：%s %s，%s。</p>'
                  '<div class="chips" style="margin:10px 0 14px">%s</div>'
                  % (esc(a["roster_date"]), esc(hhmm(a["appointment_datetime"])),
                     esc(a["dname"] or ""), chips), right=btn("回队列", "/desk/appointments"))
    body += table(["时段", "牙医", "已约/容量", ""], rows,
                  "这一天没有空余时段，换个日期看看")
    return S.page("改约", body, sess, "/desk/appointments")


def r_desk_reschedule_form(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    return h.send(200, p_desk_reschedule(sess, aid, day=(qs.get("d") or [None])[0]))


def r_desk_reschedule_do(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    if not same_clinic(sess, aid=aid):
        return deny(h, "/desk/appointments")
    f = h.form()
    try:
        rid = int(f.get("roster_id") or 0)
    except ValueError:
        return deny(h, "/desk/appointments", msg="时段不对")
    c = con()
    bad = appt_block(appt_row(c, aid), "reschedule")
    if bad:
        c.close()
        return deny(h, "/desk/appointments", msg=bad)
    r = c.execute("SELECT * FROM ROSTER WHERE roster_id=?"
                  " AND IFNULL(is_void,0)=0 AND IFNULL(is_published,1)=1",
                  (rid,)).fetchone()
    if not r:
        c.close()
        return deny(h, "/desk/appointments", msg="这个时段不存在或已停诊")
    used = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=?"
                     " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')"
                     " AND appointment_id<>?", (rid, int(aid))).fetchone()[0]
    if used >= r["slot_capacity"]:
        c.close()
        return deny(h, "/desk/appointments", msg="这个时段刚被约满")
    dt = "%s %s" % (r["roster_date"], r["slot_start"])
    c.execute("UPDATE APPOINTMENT SET roster_id=?, appointment_datetime=?"
              " WHERE appointment_id=? AND status='已预约'"
              " AND IFNULL(is_void,0)=0", (rid, dt, int(aid)))
    c.commit()
    c.close()
    audit(sess, "APPOINTMENT", aid, "reschedule", None, dt)
    return h.redirect("/desk/appointments?ok=已改到 " + dt)


def r_desk_noshow(h, sess, aid):
    """记爽约：号释放出来，但保留记录，方便以后看取消率。"""
    if not sess:
        return h.redirect("/login")
    if not same_clinic(sess, aid=aid):
        return deny(h, "/desk/appointments")
    c = con()
    a = c.execute("SELECT * FROM APPOINTMENT WHERE appointment_id=?", (int(aid),)).fetchone()
    if not a:
        c.close()
        return deny(h, "/desk/appointments", msg="预约不存在")
    bad = appt_block(a, "noshow")
    if bad:
        c.close()
        return deny(h, "/desk/appointments", msg=bad)
    # 还没到就诊时间不能记爽约——患者人可能正在路上，记错了会留下错误失约记录
    if (a["appointment_datetime"] or "") > datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        c.close()
        return deny(h, "/desk/appointments",
                    msg="这条预约还没到时间，只能取消或改约，不能记爽约")
    c.execute("UPDATE APPOINTMENT SET status='爽约', cancellation_category='患者未到'"
              " WHERE appointment_id=?", (int(aid),))
    c.commit()
    c.close()
    audit(sess, "APPOINTMENT", aid, "status", "已预约", "爽约")
    return h.redirect("/desk/appointments?ok=已记爽约，号已释放")


def r_desk_cancel(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    if not same_clinic(sess, aid=aid):
        return deny(h, "/desk/appointments")
    c = con()
    bad = appt_block(appt_row(c, aid), "cancel")
    if bad:
        c.close()
        return deny(h, "/desk/appointments", msg=bad)
    cur = c.execute("UPDATE APPOINTMENT SET status='已取消', cancellation_category='前台代客取消',"
                    " void_reason='前台代客取消', void_at=?, void_account_id=?"
                    " WHERE appointment_id=? AND status='已预约' AND IFNULL(is_void,0)=0",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     sess.get("account_id"), int(aid)))
    if cur.rowcount == 0:
        c.close()
        return deny(h, "/desk/appointments", msg="这条预约刚被改过，刷新再看")
    c.commit()
    c.close()
    audit(sess, "APPOINTMENT", aid, "status", "已预约", "已取消")
    return h.redirect("/desk/appointments?ok=已取消，号已释放")


def p_walkin(sess, err=""):
    c = con()
    cid = staff_clinic(sess) or 1
    done = c.execute("SELECT d.name, d.dentist_id FROM ROSTER r"
                     " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
                     " WHERE r.clinic_id=? AND r.roster_date=? AND IFNULL(r.is_reserved,0)=0"
                     " GROUP BY d.dentist_id", (cid, today())).fetchall()
    docs = "".join('<option value="%d">%s</option>' % (d["dentist_id"], esc(d["name"])) for d in done)
    pats = c.execute("SELECT patient_id, name, phone FROM PATIENT ORDER BY patient_id DESC LIMIT 80").fetchall()
    opts = "".join('<option value="%d">%s · %s</option>' % (p["patient_id"], esc(p["name"]), esc(p["phone"] or ""))
                   for p in pats)
    c.close()
    body = S.flash_err(err) + panel(
        "散客挂号",
        '<form method="post" action="/desk/walkin" class="f2">'
        '<div><label>患者</label><select name="patient_id" style="width:100%%">%s</select></div>'
        '<div><label>接诊牙医</label><select name="dentist_id" style="width:100%%">%s</select></div>'
        '<div style="grid-column:1/-1;margin-top:14px">'
        '<button class="btn">挂号并建就诊记录</button> '
        '<a class="btn ghost" href="/desk/appointments">取消</a></div>'
        '</form>' % (opts, docs))
    body += '<p class="muted">散客没有预约，直接建一条就诊记录；结算在开诊后用「开结算单」完成。</p>'
    return S.page("散客挂号", body, sess, "/desk/appointments")


def r_walkin_form(h, sess):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_walkin(sess))


def r_walkin_do(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("frontdesk", "manager", "hq", "ops", "admin"):
        return h.redirect("/desk/walkin?err=散客挂号由前台办理")
    f = h.form()
    pid = int(f.get("patient_id") or 0)
    did = int(f.get("dentist_id") or 0)
    if not pid:
        return h.redirect("/desk/walkin")
    c = con()
    cid = staff_clinic(sess) or 1
    # 散客也要找「还有空位」的排班，不能随便抓第一条：可能已经约满，
    # 也可能已经停诊（牙医请假）。时段按当前时刻往后找最近的一条。
    hhmm = datetime.now().strftime("%H:%M")
    r = c.execute(
        "SELECT r.roster_id, r.slot_start FROM ROSTER r"
        " WHERE r.clinic_id=? AND r.dentist_id=? AND r.roster_date=?"
        "   AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
        "   AND r.slot_end > ?"
        "   AND r.slot_capacity > (SELECT COUNT(*) FROM APPOINTMENT a"
        "     WHERE a.roster_id=r.roster_id AND IFNULL(a.is_void,0)=0"
        "       AND a.status IN ('已预约','已到诊'))"
        " ORDER BY CASE WHEN r.slot_start <= ? THEN 0 ELSE 1 END, r.slot_start LIMIT 1",
        (cid, did, today(), hhmm, hhmm)).fetchone()
    if not r:
        c.close()
        return h.redirect("/desk/walkin?err=这位牙医今天没有可用的时段（没排班、已停诊或已约满）")
    # 同一位患者同一天同一个医生不要重复挂
    dup = c.execute(
        "SELECT COUNT(*) FROM APPOINTMENT a JOIN ROSTER r2 ON a.roster_id=r2.roster_id"
        " WHERE a.patient_id=? AND r2.dentist_id=? AND r2.roster_date=?"
        "   AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')",
        (pid, did, today())).fetchone()[0]
    if dup:
        c.close()
        return h.redirect("/desk/walkin?err=这位患者今天已经挂过这位牙医了")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d8 = today().replace("-", "")
    seq = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE appointment_no LIKE ?",
                    ("A" + d8 + "%",)).fetchone()[0] + 1
    ano = "A%s%04d" % (d8, seq)
    c.execute("INSERT INTO APPOINTMENT(appointment_no, patient_id, roster_id,"
              " appointment_datetime, status, visit_reason)"
              " VALUES(?,?,?,?,?,?)",
              (ano, pid, r["roster_id"], now, "已到诊", "散客到店"))
    aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    n = c.execute("SELECT IFNULL(MAX(visit_no),30000)+1 FROM VISIT").fetchone()[0]
    c.execute("INSERT INTO VISIT(visit_no, appointment_id, clinic_id, visit_datetime, treated)"
              " VALUES(?,?,?,?,0)", (n, aid, cid, now))
    audit(sess, "APPOINTMENT", aid, "status", "", "已到诊（散客）", patient_id=pid, con=c)
    c.commit()
    c.close()
    return h.redirect("/desk/appointments")


def p_invoice(sess, vid, flash=""):
    c = con()
    v = c.execute("SELECT v.*, p.name AS pname, a.patient_id FROM VISIT v"
                  " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                  " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                  " WHERE v.visit_id=?", (vid,)).fetchone()
    if not v:
        c.close()
        return None
    inv = c.execute("SELECT * FROM INVOICE WHERE visit_id=?", (vid,)).fetchone()
    items = c.execute("SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
                      " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
                      " WHERE i.visit_id=?", (vid,)).fetchall()
    # 结算单一旦开出来，它就是唯一的计费依据；
    # TREATMENT_ITEM 是医生后续可能继续加的东西，两者不一致时以结算单为准，
    # 并给一个「同步明细」的入口，而不是让页面的应收和明细各说各话。
    items_total = sum(ti_amount(i) for i in items)
    lines, pays = [], []
    if inv:
        lines = c.execute("SELECT * FROM INVOICE_LINE WHERE invoice_id=?"
                          " ORDER BY line_no", (inv["invoice_id"],)).fetchall()
        pays = c.execute("SELECT * FROM PAYMENT WHERE invoice_id=? AND IFNULL(is_void,0)=0",
                         (inv["invoice_id"],)).fetchall()
    inv_total = sum(money_float(l["line_subtotal"]) for l in lines) if inv else items_total
    total = inv_total
    c.close()
    body = S.flash_ok(flash)
    body += panel("就诊信息", '<dl class="kv"><dt>患者</dt><dd>%s</dd>'
                  '<dt>就诊时间</dt><dd>%s</dd><dt>诊断</dt><dd>%s</dd></dl>'
                  % (esc(v["pname"]), esc(S.fmt_dt(v["visit_datetime"])),
                     esc(v["diagnosis"] or "—")))
    rows = [[esc(i["item_name"]), esc(i["tooth_fdi"] or "—"), num(i["standard_units"] or 1),
             money(ti_price(i)), money(ti_amount(i))] for i in items]
    body += panel("治疗项目", table(["项目", "牙位", "数量", "单价", "金额"], rows) +
                  '<p style="margin-top:12px"><b>合计 %s 元</b></p>' % money(total))
    if not inv:
        body += post_btn("按治疗项目开结算单", "/desk/invoice/%d/create" % vid, "btn")
    else:
        lrows = [[esc(l["item_name"]), num(l["units_used"] or 1),
                  money(l["unit_price"]), money(l["line_subtotal"])] for l in lines]
        prows = [[esc(p["payment_no"]), esc(p["method"]), money(p["amount"]),
                  esc(S.fmt_dt(p["paid_datetime"]))] for p in pays]
        paid = sum(money_float(p["amount"]) for p in pays)
        body += panel("结算单 %s" % esc(inv["invoice_no"]),
                      table(["项目", "数量", "单价", "金额"], lrows) +
                      "<h2 class=\"sec\">收款</h2>" + table(["单号", "方式", "金额", "时间"], prows) +
                      '<p style="margin-top:12px">已收 <b>%s</b> 元　应收 <b>%s</b> 元</p>'
                      % (money(paid), money(total)),
                      right='<span class="badge %s">%s</span>' % (
                          "g" if inv["status"] == "已收款" else "y", esc(inv["status"])))
        if abs(items_total - inv_total) > 0.01:
            body += panel(
                "明细与治疗项目不一致",
                '<p>结算单明细合计 <b>%s</b> 元，治疗项目合计 <b>%s</b> 元。'
                "结算单开出后医生又改过项目，需要把明细同步一次，否则收款和账单会对不上。</p>"
                % (money(inv_total), money(items_total)),
                right=post_btn("按治疗项目同步明细",
                               "/desk/invoice/%d/sync" % vid, "btn",
                               confirm="会用当前治疗项目覆盖结算单明细，继续？"))
        if paid > 0.01:
            body += panel(
                "退费与红冲",
                "<p>已收 <b>%s</b> 元。收错了、项目做不了、或者患者当场要求退，"
                "在这里退；退完这张单的状态会自己回到「部分收款」或「待收款」。</p>"
                % money(paid),
                right=btn("登记退费", "/desk/invoice/%d/refund" % int(inv["invoice_id"]),
                          "btn ghost"))
        if paid <= 0.01 and int(inv["is_void"] or 0) == 0:
            body += panel(
                "作废这张单",
                "<p>开错了、或者患者当场不做了，收过钱之前可以整张作废。"
                "作废后不进报表、不能收款；要重开就回牙医端重新登记项目。</p>",
                right=post_btn("作废这张单", "/desk/invoice/%d/void" % int(vid), "btn ghost",
                               confirm="作废后这张单不再计入收入和应收，确定？"))
        if paid < total - 0.01:
            body += panel("登记收款",
                          '<form method="post" action="/desk/invoice/%d/pay" class="f">'
                          '<label>金额</label><input name="amount" value="%s" style="width:120px">'
                          '<label>方式</label><select name="method">%s</select>'
                          '<button class="btn">确认收款</button></form>'
                          % (vid, money(total - paid),
                             "".join("<option>%s</option>" % m for m in PAY_METHODS)))
    return S.page("结算", body, sess, "/desk/appointments")


def p_refund(sess, inv_id, err=""):
    """退费登记页。可退额 = 已收 - 已退。"""
    if not sess:
        return None
    c = con()
    inv = c.execute("SELECT * FROM INVOICE WHERE invoice_id=?", (inv_id,)).fetchone()
    if not inv:
        c.close()
        return None
    got = money_float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND IFNULL(is_void,0)=0",
        (inv_id,)).fetchone()[0])
    back = money_float(c.execute(
        "SELECT IFNULL(-SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND amount<0"
        " AND IFNULL(is_void,0)=0", (inv_id,)).fetchone()[0])
    ways = [r["method"] for r in c.execute(
        "SELECT DISTINCT method FROM PAYMENT WHERE invoice_id=? AND amount>0"
        " AND IFNULL(is_void,0)=0", (inv_id,)).fetchall()] or ["现金"]
    c.close()
    # got 是**净**收款（负向退费已经抵在里面），能退的上限就是它本身。
    # 早先写成 got - back，等于把退过的钱再减一遍：应收 550、已退 110 之后
    # 页面只让再退 330，实际还能退 440。
    can = got
    body = ('<div class="pg-h"><h1>退费</h1><div class="pg-a">%s</div></div>'
            % btn("返回结算单", "/desk/invoice/%d" % int(inv["visit_id"]), "btn ghost"))
    if err:
        body += '<div class="alert err">%s</div>' % esc(err)
    body += panel("这张单",
                  "<p>结算单号 <b>%s</b>　·　已收 <b>%s</b> 元　·　已退 <b>%s</b> 元"
                  "　·　还能退 <b>%s</b> 元</p>"
                  % (esc(inv["invoice_no"]), money(got), money(back), money(can)))
    if can <= 0.01:
        body += panel("没有可退的钱", "<p>这张单目前没有净收款，退不了。</p>")
        return S.page("退费", body, sess, "/desk/invoices")
    body += panel("退多少、为什么退",
                  '<form method="post" action="/desk/invoice/%d/refund"'
                  ' style="display:grid;gap:14px;max-width:520px">'
                  '<div><label style="display:block;margin-bottom:6px;color:#6b7280;'
                  'font-size:13px">退款金额（最多可退 %s 元）</label>'
                  '<input name="amount" value="%s" style="width:180px"></div>'
                  '<div><label style="display:block;margin-bottom:6px;color:#6b7280;'
                  'font-size:13px">退回方式</label><select name="method">%s</select></div>'
                  '<div><label style="display:block;margin-bottom:6px;color:#6b7280;'
                  'font-size:13px">退费原因（必填，对账要靠它）</label>'
                  '<input name="reason" placeholder="如：患者当场取消种植，已收定金退回"'
                  ' style="width:100%%"></div>'
                  '<div><button class="btn danger-solid">确认退费</button></div>'
                  '</form>'
                  % (inv_id, money(can), money(can),
                     "".join("<option>%s</option>" % esc(w) for w in ways)))
    return S.page("退费", body, sess, "/desk/invoices")


def r_refund_form(h, sess, inv_id):
    if not sess:
        return h.redirect("/login")
    p = p_refund(sess, int(inv_id))
    if p is None:
        return h.redirect("/desk/invoices")
    return h.send(200, p)


def r_refund_do(h, sess, inv_id):
    """写一条负向 PAYMENT；状态由金额派生，不用另外改。"""
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("finance", "hq", "manager", "admin"):
        return deny(h, "/desk/invoices", msg="退费要财务或店长来操作")
    f = h.form()
    inv_id = int(inv_id)
    c = con()
    inv = c.execute("SELECT * FROM INVOICE WHERE invoice_id=?", (inv_id,)).fetchone()
    if not inv:
        c.close()
        return h.redirect("/desk/invoices")
    back = "/desk/invoice/%d" % int(inv["visit_id"])
    try:
        amt = money_float(f.get("amount"))
    except (TypeError, ValueError):
        c.close()
        return deny(h, back, msg="退款金额要填数字")
    if amt != amt or amt <= 0:
        c.close()
        return deny(h, back, msg="退款金额必须大于 0")
    reason = (f.get("reason") or "").strip()
    if len(reason) < 2:
        c.close()
        return deny(h, back, msg="退费原因必须填，将来对账要靠它")
    method = (f.get("method") or "").strip()
    if method not in PAY_METHODS:
        c.close()
        return deny(h, back, msg="退回方式不在可选范围内")
    got = money_float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND IFNULL(is_void,0)=0",
        (inv_id,)).fetchone()[0])
    already = money_float(c.execute(
        "SELECT IFNULL(-SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND amount<0"
        " AND IFNULL(is_void,0)=0", (inv_id,)).fetchone()[0])
    # got 与 already 都是净额口径下的量（SUM(amount) 已含负向），可退上限＝got。
    if amt > got + 0.01:
        c.close()
        return deny(h, back, msg="退款超过可退金额（还能退 %s 元）" % money(got))
    no = next_no(c, "PAYMENT", "PAY", 80000)
    # 退费单号与收款单号分开：对账时能直接引用「这张退费单」，不用靠 amount<0 判断
    rf = next_no(c, "REFUND", "RF", 90000)
    c.execute("INSERT INTO PAYMENT(invoice_id, payment_no, amount, method, paid_datetime,"
              " refund_reason, refund_no) VALUES(?,?,?,?,?,?,?)",
              (inv_id, no, -amt, method,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S"), reason, rf))
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    audit(sess, "PAYMENT", pid, "amount", "0", -amt, con=c)
    audit(sess, "PAYMENT", pid, "refund_reason", "", reason, con=c)
    c.commit()
    c.close()
    return h.redirect(back + "?ok=" + S.quote(
        "已退 %s 元，退费单号 %s（%s）" % (money(amt), rf, reason)))


def r_invoice(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    p = p_invoice(sess, int(vid))
    if p is None:
        return h.send(404, S.page("页面不存在",
                                  '<h1>404</h1><p class="sub">这张结算单不存在，'
                                  '可能已经被作废或删除了。</p>'
                                  '<p><a class="btn" href="/desk/invoices">回结算单列表</a></p>',
                                  sess))
    return h.send(200, p)


def _rebuild_lines(c, inv_id, vid):
    """按当前的治疗项目重建结算单明细。开单、加项目、手工同步都走这里，
    避免「治疗项目 500、账单明细 200」两套数。"""
    c.execute("DELETE FROM INVOICE_LINE WHERE invoice_id=?", (inv_id,))
    items = c.execute(
        "SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
        " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
        " WHERE i.visit_id=? ORDER BY i.line_no", (vid,)).fetchall()
    for n, i in enumerate(items, 1):
        up = i["agreed_price"] if i["agreed_price"] is not None else i["standard_unit_price"]
        sub = m2((up or 0) * (i["standard_units"] or 0))
        c.execute("INSERT INTO INVOICE_LINE(invoice_id, line_no, item_name,"
                  " units_used, unit_price, line_subtotal) VALUES(?,?,?,?,?,?)",
                  (inv_id, n, i["item_name"] or "治疗项目",
                   i["standard_units"], up, sub))


def can_bill(sess, vid):
    """谁能给这次就诊开结算单 / 重建明细。

    `same_clinic` 对牙医恒真（DENTIST 没有 clinic_id，staff_clinic 查不到就返回
    None，而None 在 same_clinic 里等于「不限门店」），所以牙医这条路必须换成
    `own_visit`——只认自己主治的那台，否则任何人拿到 visit_id 就能开单。
    """
    desk = (sess or {}).get("desk")
    if desk == "doctor":
        return own_visit(sess, vid)
    if desk in ("frontdesk", "manager", "hq", "ops", "finance", "admin"):
        return same_clinic(sess, vid=vid)
    return False


def r_invoice_create(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    if not can_bill(sess, vid):
        return deny(h, "/desk/appointments")
    c = con()
    v = c.execute("SELECT * FROM VISIT WHERE visit_id=?", (int(vid),)).fetchone()
    if not v:
        c.close()
        return h.redirect("/desk/appointments")
    has = c.execute("SELECT invoice_id FROM INVOICE WHERE visit_id=?", (int(vid),)).fetchone()
    if has:
        c.close()
        return h.redirect("/desk/invoice/%d" % int(vid))
    n_item = c.execute("SELECT COUNT(*) FROM TREATMENT_ITEM WHERE visit_id=?",
                       (int(vid),)).fetchone()[0]
    amt = money_float(c.execute(
        "SELECT IFNULL(SUM(IFNULL(agreed_price, standard_unit_price) * standard_units),0)"
        " FROM TREATMENT_ITEM WHERE visit_id=?", (int(vid),)).fetchone()[0])
    if not n_item:
        c.close()
        return deny(h, "/desk/visit/%d" % int(vid),
                    msg="这次就诊还没有登记治疗项目，开了单也是 0 元，先去加项目")
    if amt <= 0.01:
        c.close()
        return deny(h, "/desk/visit/%d" % int(vid),
                    msg="这次就诊的治疗项目合计为 0 元，开不出结算单；"
                        "让医生补上单价，或者先把这笔就诊作废")
    # 单号用 SEQ 原子自增。原来写的是 "INV%06d" % (70000 + visit_id)，
    # 同一次就诊必然算出同一个号，并发两次开单就是两张同号单、应收翻倍。
    # 另外 INVOICE(invoice_no) / INVOICE(visit_id) 上都有唯一索引，撞了就说明
    # 别人先把单开出来了，直接把人送到那张单子上。
    no = next_no(c, "invoice", "INV", 70000)
    try:
        c.execute("INSERT INTO INVOICE(invoice_no, visit_id, invoice_date, status)"
                  " VALUES(?,?,?,?)", (no, int(vid), today(), "待收款"))
    except sqlite3.IntegrityError:
        c.rollback()
        row = c.execute("SELECT invoice_id FROM INVOICE WHERE visit_id=?"
                        " AND IFNULL(is_void,0)=0", (int(vid),)).fetchone()
        c.close()
        if row:
            return h.redirect("/desk/invoice/%d" % row[0])
        return deny(h, "/desk/visit/%d" % int(vid),
                    msg="这张结算单已经开出来了，刷新一下再看")
    inv_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    items = c.execute("SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
                      " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
                      " WHERE i.visit_id=?", (int(vid),)).fetchall()
    for n, i in enumerate(items, 1):
        c.execute("INSERT INTO INVOICE_LINE(invoice_id, line_no, item_name,"
                  " units_used, unit_price, line_subtotal)"
                  " VALUES(?,?,?,?,?,?)",
                  (inv_id, n, i["item_name"], i["standard_units"],
                   ti_price(i), ti_amount(i)))
    c.commit()
    c.close()
    audit(sess, "INVOICE", inv_id, "created", None, no)
    return h.redirect("/desk/invoice/%d" % int(vid))


def r_invoice_sync(h, sess, vid):
    """把结算单明细按当前治疗项目重建。只允许在「还没收满」时做，收过钱的单不能改明细。"""
    if not sess:
        return h.redirect("/login")
    if not can_bill(sess, vid):
        return deny(h, "/desk/appointments")
    c = con()
    inv = c.execute("SELECT * FROM INVOICE WHERE visit_id=?", (int(vid),)).fetchone()
    if not inv:
        c.close()
        return h.redirect("/desk/invoice/%d" % int(vid))
    due = money_float(c.execute(
        "SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE WHERE invoice_id=?",
        (inv["invoice_id"],)).fetchone()[0])
    got = money_float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND IFNULL(is_void,0)=0",
        (inv["invoice_id"],)).fetchone()[0])
    if got > 0.01:
        c.close()
        return h.redirect(
            "/desk/invoice/%d?err=已经收过 %s 元，结算单明细不能再改；"
            "请先作废收款再同步" % (int(vid), money(got)))
    items = c.execute("SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
                      " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
                      " WHERE i.visit_id=? ORDER BY i.line_no", (int(vid),)).fetchall()
    c.execute("DELETE FROM INVOICE_LINE WHERE invoice_id=?", (inv["invoice_id"],))
    for n, i in enumerate(items, 1):
        c.execute("INSERT INTO INVOICE_LINE(invoice_id, line_no, item_name,"
                  " units_used, unit_price, line_subtotal) VALUES(?,?,?,?,?,?)",
                  (inv["invoice_id"], n, i["item_name"], i["standard_units"],
                   ti_price(i), ti_amount(i)))
    newdue = sum(ti_amount(i) for i in items)
    # 状态必须按「已收 vs 应收」判，不能只看应收是不是 0：
    # 退过费的单应收仍是 550、已收 450，那是「部分收款」，不是「待收款」。
    if got >= newdue - 0.01:
        st = "已收款"
    elif got > 0.01:
        st = "部分收款"
    else:
        st = "待收款"
    if st != (inv["status"] or ""):
        audit(sess, "INVOICE", inv["invoice_id"], "status",
              inv["status"] or "", st, con=c)
    c.execute("UPDATE INVOICE SET status=? WHERE invoice_id=?", (st, inv["invoice_id"]))
    c.commit()
    c.close()
    return h.redirect("/desk/invoice/%d?ok=明细已按治疗项目同步" % int(vid))
    _ = due


def r_invoice_void(h, sess, vid):
    """整张结算单作废。

    is_void 与 status 同时写：前者的存在意义是「这条记录不该被统计」，
    后者给人看。历史上出现过只有 status 变动、is_void 没动的情况，
    报表与列表就会打架，所以这里两个都写。
    """
    if not sess:
        return h.redirect("/login")
    back = "/desk/invoice/%d" % int(vid)
    if not same_clinic(sess, vid=vid):
        return deny(h, "/desk/appointments")
    if sess.get("desk") not in ("frontdesk", "manager", "hq", "finance", "admin"):
        return deny(h, back, msg="作废结算单要前台、店长或财务来做")
    c = con()
    inv = c.execute("SELECT * FROM INVOICE WHERE visit_id=?", (int(vid),)).fetchone()
    if not inv:
        c.close()
        return h.redirect("/desk/appointments")
    if int(inv["is_void"] or 0) == 1:
        c.close()
        return h.redirect(back + "?err=这张单已经作废了")
    got = money_float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
        " WHERE invoice_id=? AND IFNULL(is_void,0)=0", (inv["invoice_id"],)).fetchone()[0])
    if got > 0.01:
        c.close()
        return h.redirect(
            back + "?err=这张单已收 %s 元，要先退费才能作废" % money(got))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE INVOICE SET is_void=1, status='已作废', void_reason=?,"
              " void_at=?, void_account_id=? WHERE invoice_id=?",
              ("前台撤销开单", now, sess.get("account_id"), inv["invoice_id"]))
    c.commit()
    audit(sess, "INVOICE", inv["invoice_id"], "status", inv["status"], "已作废", con=c)
    c.close()
    return h.redirect("/desk/invoices?ok=结算单 %s 已作废" % (inv["invoice_no"] or ""))


def r_invoice_pay(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    if not same_clinic(sess, vid=vid):
        return deny(h, "/desk/appointments")
    # 只有前台/财务/店长能收钱，牙医和助手不碰钱箱
    if sess.get("role") not in ("receptionist", "finance", "supervisor", "ops"):
        return deny(h, "/desk/invoice/%d" % int(vid))
    f = h.form()
    amt = money_float(f.get("amount"))
    method = f.get("method") or "现金"
    if method not in PAY_METHODS:
        return h.redirect("/desk/invoice/%d?err=收款方式不在可选范围内" % int(vid))
    if amt != amt or amt in (float("inf"), float("-inf")):
        return h.redirect("/desk/invoice/%d?err=实收金额不是有效数字" % int(vid))
    if amt <= 0:
        return h.redirect("/desk/invoice/%d?err=实收金额必须大于 0" % int(vid))
    c = con()
    inv = c.execute("SELECT * FROM INVOICE WHERE visit_id=?", (int(vid),)).fetchone()
    if not inv:
        c.close()
        return h.redirect("/desk/invoice/%d" % int(vid))
    if int(inv["is_void"] or 0) == 1:
        c.close()
        return h.redirect("/desk/invoice/%d?err=这张结算单已作废，不能再收款" % int(vid))
    due0 = money_float(c.execute(
        "SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE WHERE invoice_id=?",
        (inv["invoice_id"],)).fetchone()[0])
    got0 = money_float(c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT WHERE invoice_id=? AND IFNULL(is_void,0)=0",
        (inv["invoice_id"],)).fetchone()[0])
    rest = due0 - got0
    if rest <= 0.01:
        c.close()
        return h.redirect("/desk/invoice/%d?err=这张单已经收满了" % int(vid))
    if amt > rest + 0.01:
        c.close()
        return h.redirect(
            "/desk/invoice/%d?err=实收超过未收金额（未收 %s 元），请核对后再录"
            % (int(vid), money(rest)))
    no = next_no(c, "PAYMENT", "PAY", 80000)
    cur = c.execute("INSERT INTO PAYMENT(invoice_id, payment_no, amount, method, paid_datetime)"
                    " VALUES(?,?,?,?,?)", (inv["invoice_id"], no, amt, method,
                                           datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    pay_id = cur.lastrowid
    tot = c.execute("SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
                    " WHERE invoice_id=? AND IFNULL(is_void,0)=0",
                    (inv["invoice_id"],)).fetchone()[0]
    due = c.execute("SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE WHERE invoice_id=?",
                    (inv["invoice_id"],)).fetchone()[0]
    got = money_float(tot)
    if got >= money_float(due) - 0.01:
        st = "已收款"
    elif got > 0.01:
        st = "部分收款"
    else:
        st = "待收款"
    c.execute("UPDATE INVOICE SET status=? WHERE invoice_id=?", (st, inv["invoice_id"]))
    c.commit()
    c.close()
    # ref 必须是 payment_id：写哪张表就指哪张表的主键，否则「PAYMENT 的审计」
    # 里会混进 invoice_id，事后谁也说不清这条记录指向哪儿。
    audit(sess, "PAYMENT", pay_id, "amount", None, amt)
    return h.redirect("/desk/invoice/%d" % int(vid))


def p_patient_detail(sess, pid):
    c = con()
    p = c.execute("SELECT * FROM PATIENT WHERE patient_id=?", (pid,)).fetchone()
    if not p:
        c.close()
        return S.page("页面不存在",
                      '<h1>404</h1><p class="sub">没有这位患者的档案。</p>'
                      '<p><a class="btn" href="/desk/patients">回患者检索</a></p>',
                      sess, "/desk/patients")
    # 患者没有 clinic_id，用他最近一次就诊的门店判归属；
    # 一次都没就诊过的患者（刚注册）不做门店限制。
    lastv = c.execute(
        "SELECT v.visit_id FROM VISIT v"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " WHERE a.patient_id=? ORDER BY v.visit_id DESC LIMIT 1", (pid,)).fetchone()
    if lastv and not same_clinic(sess, vid=lastv["visit_id"]):
        c.close()
        return S.page("无权查看",
                    '<div class="panel"><div class="h">无法打开</div>'
                    '<div class="bd"><p style="margin:0 0 12px">这位患者不在本店就诊，换一家店再看。</p>'
                    '<a class="btn" href="/desk/patients">返回</a></div></div>',
                    sess, "/desk/patients")

    visits = c.execute(
        "SELECT v.visit_id, v.visit_datetime, v.diagnosis, d.name AS dname,"
        " c.clinic_name, i.invoice_no, i.status AS ist"
        " FROM VISIT v LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id"
        " WHERE a.patient_id=? ORDER BY v.visit_datetime DESC LIMIT 20", (pid,)).fetchall()
    al = c.execute("SELECT * FROM ALLERGY WHERE patient_id=?", (pid,)).fetchall()
    c.close()
    body = panel("基本信息", '<dl class="kv">'
                 '<dt>姓名</dt><dd>%s</dd><dt>电话</dt><dd>%s</dd>'
                 '<dt>出生日期</dt><dd>%s</dd><dt>过敏</dt><dd>%s</dd></dl>'
                 % (esc(p["name"]), esc(p["phone"] or "—"), esc(p["date_of_birth"] or "—"),
                    "、".join(esc(a["allergy_name"]) for a in al) or "无记录"))
    rows = [[esc(S.fmt_dt(v["visit_datetime"])), esc(v["clinic_name"]), esc(v["dname"]),
             esc(v["diagnosis"] or "—"), esc(v["invoice_no"] or "—"),
             btn("看明细", "/visit/%d" % v["visit_id"], "btn ghost sm")] for v in visits]
    body += panel("历史就诊", table(["时间", "门店", "牙医", "诊断", "结算单", ""], rows))
    return S.page("患者 %s" % p["name"], body, sess, "/desk/patients")


def r_patient_detail(h, sess, pid):
    if not sess:
        return h.redirect("/login")
    _c = con()
    _ok = _c.execute("SELECT 1 FROM PATIENT WHERE patient_id=?",
                     (int(pid),)).fetchone()
    _c.close()
    if not _ok:
        return h.send(404, S.page("页面不存在",
                                  '<h1>404</h1><p class="sub">没有这位患者的档案。</p>'
                                  '<p><a class="btn" href="/desk/patients">回患者检索</a></p>',
                                  sess, "/desk/patients"))
    p = p_patient_detail(sess, int(pid))
    if p is None:
        return h.redirect("/desk/patients")
    return h.send(200, p)


def r_patients2(h, sess):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    q = (qs.get("q") or [""])[0].strip()
    c = con()
    if q:
        rows = c.execute("SELECT * FROM PATIENT WHERE name LIKE ? OR phone LIKE ?"
                         " ORDER BY patient_id DESC LIMIT 60",
                         ("%" + q + "%", "%" + q + "%")).fetchall()
    else:
        rows = c.execute("SELECT * FROM PATIENT ORDER BY patient_id DESC LIMIT 30").fetchall()
    c.close()
    out = [[esc(r["name"]), esc(r["phone"] or "—"), esc(r["date_of_birth"] or "—"),
            btn("明细", "/desk/patient/%d" % r["patient_id"], "btn ghost sm")] for r in rows]
    body = panel("患者检索",
                 '<form method="get" class="f" style="margin-bottom:14px">'
                 '<input name="q" value="%s" placeholder="姓名或电话">'
                 '<button class="btn">搜索</button></form>' % esc(q) +
                 table(["姓名", "电话", "出生日期", ""], out))
    return h.send(200, S.page("患者检索", body, sess, "/desk/patients"))


# ------------------------------------------------------------------ 牙医
def p_doctor(sess):
    did = sess.get("dentist_id")
    c = con()
    if not did:
        c.close()
        return S.page("诊台", '<div class="msg err">这个账号没有绑定牙医档案。</div>', sess, "/desk")
    t = today()
    rows = c.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name AS pname,"
        " p.phone, r.slot_start, r.slot_end, cc.clinic_name, v.visit_id, v.diagnosis"
        " FROM APPOINTMENT a"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN CLINIC cc ON r.clinic_id=cc.clinic_id"
        " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " WHERE r.dentist_id=? AND date(a.appointment_datetime)=?"
        " ORDER BY a.appointment_datetime", (did, t)).fetchall()
    n_all = len(rows)
    n_done = sum(1 for r in rows if r["visit_id"])
    n_wait = sum(1 for r in rows if r["status"] == "已预约")
    out = []
    for r in rows:
        if r["visit_id"]:
            act = btn("写病历", "/desk/visit/%d" % r["visit_id"])
        else:
            act = '<span class="muted">未到诊</span>'
        out.append([esc(hhmm(r["appointment_datetime"])), esc(r["pname"]),
                    esc(r["phone"] or "—"), esc(r["clinic_name"]),
                    S.badge(r["status"]), esc(r["diagnosis"] or "—"), act])
    c.close()
    body = ('<div class="grid g3">%s%s%s</div>'
            % (S.stat(n_all, "今日接诊", "含已到诊与未到"),
               S.stat(n_done, "已开诊", "可以写病历"),
               S.stat(n_wait, "还没到店", "患者到前台登记后出现")))
    body += panel("今日患者", table(["时间", "患者", "电话", "门店", "状态", "诊断", ""], out))
    return S.page("我的诊台", body, sess, "/desk")


IMG_TYPES = ("口内照", "全景片", "根尖片", "CBCT", "模型扫描")


def _imaging_panel(c, vid):
    """就诊页的影像资料面板：列表 + 登记入口。

    注意 p_visit_edit 在组装 body 之前已经把 c 关掉了，所以这里必须自己开连接。
    """
    db = con()
    rows = db.execute(
        "SELECT image_id, image_type, tooth_fdi, image_url, taken_datetime"
        " FROM IMAGE_RECORD WHERE visit_id=? ORDER BY image_id DESC", (vid,)).fetchall()
    tr = []
    for r in rows:
        loc = r["image_url"] or ""
        show = esc(loc)
        if loc and ("/" in loc or "\\" in loc):
            show = '<span style="word-break:break-all">%s</span>' % esc(loc)
        tr.append([esc(r["image_type"] or "—"), esc(r["tooth_fdi"] or "—"),
                   show or "—", esc((r["taken_datetime"] or "")[:16])])
    db.close()
    opts = "".join('<option>%s</option>' % t for t in IMG_TYPES)
    form = (
        '<form method="post" action="/desk/visit/%d/image" class="f">'
        '<label>类型</label><select name="image_type">%s</select>'
        '<label>牙位</label><input name="tooth_fdi" placeholder="如 16，可留空" style="width:140px">'
        '<label>存放位置</label>'
        '<input name="image_url" placeholder="本地路径或 PACS 编号" style="min-width:320px">'
        '<button class="btn">登记</button></form>'
        % (vid, opts))
    note = ('<p class="sub" style="margin:8px 0 0">这一版不做文件上传：'
            '影像存在拍摄设备或 PACS 里，这里只登记位置与类型，方便医生写病历时查得到。'
            '要做真正的上传，需要接对象存储或 DICOM 服务。</p>')
    return panel("影像资料（%d 张）" % len(rows),
                 table(["类型", "牙位", "存放位置", "拍摄时间"], tr,
                       "这次就诊还没有影像记录") + form + note)


def p_visit_edit(sess, vid, flash="", err=""):
    c = con()
    v = c.execute(
        "SELECT v.*, p.name AS pname, p.date_of_birth, p.phone, cc.clinic_name,"
        " a.patient_id FROM VISIT v"
        " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN CLINIC cc ON v.clinic_id=cc.clinic_id"
        " WHERE v.visit_id=?", (vid,)).fetchone()
    if not v:
        c.close()
        return None
    # 同店可看（会诊、交接），跨店不行；写操作另有 can_bill 把关
    if not same_clinic(sess, vid=int(vid) if str(vid).isdigit() else None):
        c.close()
        return S.page("无权查看",
                    '<div class="panel"><div class="h">无法打开</div>'
                    '<div class="bd"><p style="margin:0 0 12px">这条病历不属于本店。</p>'
                    '<a class="btn" href="/desk/appointments">返回</a></div></div>',
                    sess, "/desk/appointments")
    al = c.execute("SELECT allergy_name, severity FROM ALLERGY WHERE patient_id=?",
                   (v["patient_id"],)).fetchall() if v["patient_id"] else []
    items = c.execute("SELECT i.*, t.item_name FROM TREATMENT_ITEM i"
                      " LEFT JOIN TREATMENT_CATALOG t ON i.catalog_id=t.catalog_id"
                      " WHERE i.visit_id=?", (vid,)).fetchall()
    cat = c.execute("SELECT * FROM TREATMENT_CATALOG ORDER BY catalog_id").fetchall()
    c.close()
    alert = ""
    if al:
        alert = ('<div class="msg err">过敏史：%s</div>'
                 % "、".join("%s（%s）" % (esc(a["allergy_name"]), esc(a["severity"] or "未分级")) for a in al))
    info = panel("患者", '<dl class="kv"><dt>姓名</dt><dd>%s</dd>'
                 '<dt>电话</dt><dd>%s</dd><dt>门店</dt><dd>%s</dd>'
                 '<dt>就诊时间</dt><dd>%s</dd></dl>'
                 % (esc(v["pname"]), esc(v["phone"] or "—"), esc(v["clinic_name"]),
                    esc(S.fmt_dt(v["visit_datetime"]))))
    form = panel(
        "病历",
        '<form method="post" action="/desk/visit/%d">'
        '<div class="f2">'
        '<div><label>主诉</label><input name="chief_complaint" value="%s" style="width:100%%"></div>'
        '<div><label>诊断</label><input name="diagnosis" value="%s" style="width:100%%"></div>'
        '<div style="grid-column:1/-1"><label>现病史</label>'
        '<textarea name="present_history">%s</textarea></div>'
        '<div style="grid-column:1/-1"><label>检查所见</label>'
        '<textarea name="examination">%s</textarea></div>'
        '<div style="grid-column:1/-1"><label>处置记录</label>'
        '<textarea name="treatment_note">%s</textarea></div>'
        '<div style="grid-column:1/-1;margin-top:6px">'
        '<button class="btn">保存病历</button></div>'
        '</div></form>'
        % (vid, esc(v["chief_complaint"] or ""), esc(v["diagnosis"] or ""),
           esc(v["present_history"] or ""), esc(v["examination"] or ""),
           esc(v["treatment_note"] or "")))
    opts = "".join('<option value="%d" data-price="%s">%s · %s 元</option>'
                   % (x["catalog_id"], x["standard_unit_price"], esc(x["item_name"]),
                      money(x["standard_unit_price"])) for x in cat)
    add = panel(
        "登记治疗项目",
        '<form method="post" action="/desk/visit/%d/item" class="f">'
        '<label>项目</label><select name="catalog_id" style="min-width:220px">%s</select>'
        '<label>牙位</label><input name="tooth_fdi" placeholder="如 16" style="width:80px">'
        '<label>数量</label><input name="units" value="1" style="width:70px">'
        '<label>实收单价</label><input name="price" placeholder="留空按标准价" style="width:110px">'
        '<button class="btn">加入本次</button></form>' % (vid, opts))
    rows = [[esc(i["item_name"]), esc(i["tooth_fdi"] or "—"), num(i["standard_units"] or 1),
             money(ti_price(i)), money(ti_amount(i)),
             esc("是" if i["added_during_visit"] else "否")] for i in items]
    total = sum(ti_amount(i) for i in items)
    lst = panel("本次项目（合计 %s 元）" % money(total),
                table(["项目", "牙位", "数量", "单价", "金额", "就诊中追加"], rows),
                right=btn("去开结算单", "/desk/invoice/%d" % vid))
    img = _imaging_panel(c, vid)
    body = (S.flash_ok(flash) + S.flash_err(err) + alert + info + form + add
            + lst + img)
    return S.page("写病历", body, sess, "/desk")


def r_visit_image(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    if not own_visit(sess, vid):
        return deny(h, "/desk/appointments", msg="不是你接诊的，不能登记")
    f = h.form()
    typ = (f.get("image_type") or "").strip()
    if typ not in IMG_TYPES:
        return h.redirect("/desk/visit/%d?err=影像类型不在可选范围内" % int(vid))
    loc = (f.get("image_url") or "").strip()
    if not loc:
        return h.redirect("/desk/visit/%d?err=存放位置必填，否则以后找不回来" % int(vid))
    tooth = (f.get("tooth_fdi") or "").strip() or None
    c = con()
    pid = c.execute(
        "SELECT a.patient_id FROM VISIT v LEFT JOIN APPOINTMENT a"
        " ON v.appointment_id=a.appointment_id WHERE v.visit_id=?",
        (int(vid),)).fetchone()
    c.execute("INSERT INTO IMAGE_RECORD(patient_id, visit_id, tooth_fdi, image_type,"
              " image_url, taken_datetime) VALUES(?,?,?,?,?,?)",
              (pid["patient_id"] if pid else None, int(vid), tooth, typ, loc,
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    new_id = c.execute("SELECT MAX(image_id) FROM IMAGE_RECORD").fetchone()[0]
    c.commit()
    try:
        audit(sess, "IMAGE_RECORD", new_id, "image_url", "", loc,
              patient_id=pid["patient_id"] if pid else None, con=c)
        c.commit()
    except Exception as e:
        sys.stderr.write("[audit image] %s\n" % e)
    c.close()
    return h.redirect("/desk/visit/%d?ok=影像已登记" % int(vid))



def r_visit_edit(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    # 编号非法、或者数字但库里没有，都走 404。
    # 早先这里把 None 交给 h.send(200, None)，页面回显 traceback 且状态码还是 200。
    bad = (str(vid) in ("0", "") or not str(vid).isdigit())
    if not bad:
        c0 = con()
        bad = not c0.execute("SELECT 1 FROM VISIT WHERE visit_id=?", (int(vid),)).fetchone()
        c0.close()
    if bad:
        return h.send(404, S.page(
            "找不到这次就诊",
            '<h1>找不到这次就诊</h1><p class="sub">编号 %s 不存在，可能已经被删掉了。</p>'
            '<a class="btn" href="/desk/appointments">回预约队列</a>' % esc(str(vid)),
            sess, "/desk/appointments"))
    # 只读页不按主治医生收窄——会诊、交接班、店长复核都要看；
    # 真正写库的 r_visit_save / r_visit_item 才校验 own_visit。
    return h.send(200, p_visit_edit(sess, int(vid)))


def sess_vid(h):
    return h.path.rsplit("/", 1)[-1]


def r_visit_save(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    if not own_visit(sess, vid):
        return deny(h, "/desk/appointments", msg="这次就诊不是你接诊的，不能改")
    # 不再叠 same_clinic：own_visit 已按「这次就诊的接诊医生」判定，
    # 牙医跨店接诊是常态（DENTIST 挂 ROSTER，不挂门店）。
    f = h.form()
    c = con()
    # 记下改前的值，写进 AUDIT_LOG，出医疗纠纷时能查是谁改的
    before = c.execute("SELECT chief_complaint, diagnosis FROM VISIT WHERE visit_id=?",
                       (int(vid),)).fetchone()
    c.execute("UPDATE VISIT SET chief_complaint=?, present_history=?, examination=?,"
              " diagnosis=?, treatment_note=?, treated=1 WHERE visit_id=?",
              (f.get("chief_complaint") or None, f.get("present_history") or None,
               f.get("examination") or None, f.get("diagnosis") or None,
               f.get("treatment_note") or None, int(vid)))
    c.commit()
    c.close()
    audit(sess, "VISIT", vid, "diagnosis",
          (before["diagnosis"] if before else "") or "",
          f.get("diagnosis") or "", )
    return h.redirect("/desk/visit/%d" % int(vid))


def r_visit_item(h, sess, vid):
    if not sess:
        return h.redirect("/login")
    if not own_visit(sess, vid):
        return deny(h, "/desk/appointments", msg="这次就诊不是你接诊的，不能改")
    # 不再叠 same_clinic：own_visit 已按「这次就诊的接诊医生」判定，
    # 牙医跨店接诊是常态（DENTIST 挂 ROSTER，不挂门店）。
    f = h.form()
    cid = int(f.get("catalog_id") or 0)
    c = con()
    cat = c.execute("SELECT * FROM TREATMENT_CATALOG WHERE catalog_id=?", (cid,)).fetchone()
    if not cat:
        c.close()
        return h.redirect("/desk/visit/%d" % int(vid))
    # 数量与单价必须有界。负数会让应收变负、单据永久卡在「待收款」收不上来；
    # 这里按口腔门诊的常识给上限（一次最多 99 个单位、单价不超过 100 万）。
    try:
        units = float(f.get("units") or 1)
    except ValueError:
        units = 1.0
    if not (0 < units <= 99):
        c.close()
        return deny(h, "/desk/visit/%d" % int(vid),
                    msg="数量要在 0 到 99 之间（填的是 %s）" % f.get("units"))
    price = f.get("price") or ""
    agreed = money_float(price) if price.strip() else None
    if agreed is not None and not (0 <= agreed <= 1000000):
        c.close()
        return deny(h, "/desk/visit/%d" % int(vid),
                    msg="实收单价要在 0 到 1000000 之间（填的是 %s）" % price)

    # 已开单：收了钱就不许再动明细；没在钱只提示去同步，不然治疗 500、账单 200。
    inv = c.execute("SELECT invoice_id FROM INVOICE WHERE visit_id=?"
                    " AND IFNULL(is_void,0)=0", (int(vid),)).fetchone()
    if inv:
        paid = c.execute("SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
                         " WHERE invoice_id=?", (inv["invoice_id"],)).fetchone()[0]
        if paid and paid > 0.001:
            c.close()
            return deny(h, "/desk/invoice/%d" % int(vid),
                        msg="这张单已经收了 %.0f 元，不能再加项目。"
                            "要加的话先作废这张单重开。" % paid)
        # 未收款：允许加，但明确告诉医生要去同步明细
        c.close()
        c = con()
    n = c.execute("SELECT IFNULL(MAX(line_no),0)+1 FROM TREATMENT_ITEM WHERE visit_id=?",
                  (int(vid),)).fetchone()[0]
    c.execute("INSERT INTO TREATMENT_ITEM(visit_id, line_no, catalog_id, dentist_id,"
              " tooth_fdi, standard_units, standard_unit_price, agreed_price,"
              " added_during_visit) VALUES(?,?,?,?,?,?,?,?,1)",
              (int(vid), n, cid, sess.get("dentist_id"), f.get("tooth_fdi") or None,
               units, cat["standard_unit_price"], agreed))
    c.commit()
    # 已经有未收款的单：直接把这条明细补进去，别让人再手动点一次同步
    inv = c.execute("SELECT invoice_id FROM INVOICE WHERE visit_id=?"
                    " AND IFNULL(is_void,0)=0", (int(vid),)).fetchone()
    if inv:
        _rebuild_lines(c, inv["invoice_id"], int(vid))
        c.commit()
    c.close()
    audit(sess, "TREATMENT_ITEM", vid, "insert", "",
          "%s ×%s" % (cat["item_name"], units))
    return h.redirect("/desk/visit/%d" % int(vid))


# ------------------------------------------------------------------ 助手
def p_assist(sess):
    c = con()
    cid = staff_clinic(sess)
    t = today()
    wh, args = "", ()
    if cid:
        wh, args = " AND cc.clinic_id=?", (cid,)
    n_visit = c.execute("SELECT COUNT(*) FROM VISIT v LEFT JOIN CLINIC cc ON v.clinic_id=cc.clinic_id"
                        " WHERE date(v.visit_datetime)=?" + wh, (t,) + args).fetchone()[0]
    n_issue = c.execute("SELECT COUNT(*) FROM MATERIAL_ISSUE WHERE date(issued_datetime)=?",
                        (t,)).fetchone()[0]
    n_low = c.execute("SELECT COUNT(*) FROM STOCK_LEDGER WHERE on_hand_qty < 50").fetchone()[0]
    c.close()
    body = ('<div class="grid g3">%s%s%s</div>'
            % (S.stat(n_visit, "今日就诊", "本店" if cid else "全部门店"),
               S.stat(n_issue, "今日领用", "耗材出库行"),
               S.stat(n_low, "库存偏低", "低于 50 的物料")))
    body += panel("助手的活",
                  '<p>治疗中途要加耗材，就在下面的「耗材领用」里登记，'
                  '登记时会写进领用记录，方便月底算成本。</p>'
                  '<p style="margin-top:12px">'
                  + btn("耗材领用", "/desk/materials")
                  + " " + btn("患者检索", "/desk/patients", "btn ghost") + '</p>')
    return S.page("助手台", body, sess, "/desk")


def p_materials(sess, flash="", err=""):
    c = con()
    mats = c.execute(
        "SELECT b.batch_id, m.material_name, m.unit, b.batch_serial_no, b.expiry_date,"
        " (SELECT IFNULL(SUM(on_hand_qty),0) FROM STOCK_LEDGER s WHERE s.material_id=m.material_id) AS qty"
        " FROM MATERIAL_BATCH b JOIN MATERIAL m ON b.material_id=m.material_id"
        " ORDER BY m.material_name LIMIT 60").fetchall()
    recent = c.execute(
        "SELECT i.issue_no, i.quantity, i.issued_datetime, m.material_name, m.unit,"
        " b.batch_serial_no FROM MATERIAL_ISSUE i"
        " LEFT JOIN MATERIAL_BATCH b ON i.batch_id=b.batch_id"
        " LEFT JOIN MATERIAL m ON b.material_id=m.material_id"
        " ORDER BY i.issue_id DESC LIMIT 15").fetchall()
    c.close()
    opts = "".join('<option value="%d">%s · 批次 %s（效期 %s，库存 %s）</option>'
                   % (m["batch_id"], esc(m["material_name"]), esc(m["batch_serial_no"] or "—"),
                      esc(m["expiry_date"] or "—"), num(m["qty"])) for m in mats)
    body = S.flash_ok(flash) + S.flash_err(err)
    body += panel("领用登记",
                  '<form method="post" action="/desk/materials" class="f">'
                  '<select name="batch_id" style="min-width:320px">%s</select>'
                  '<label>数量</label><input name="quantity" value="1" style="width:80px">'
                  '<button class="btn">登记领用</button></form>' % opts)
    rows = [[esc(r["issue_no"] or "—"), esc(r["material_name"]),
             num(r["quantity"]), esc(r["unit"] or ""),
             esc(S.fmt_dt(r["issued_datetime"]))] for r in recent]
    body += panel("最近领用", table(["领用单号", "物料", "数量", "单位", "时间"], rows))
    return S.page("耗材领用", body, sess, "/desk/materials")


def r_materials(h, sess):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_materials(sess))


def r_materials_do(h, sess):
    """耗材领用：按领用人门店扣账、校验数量与效期、同事务写流水。

    验收实测过三个要命的毛病，都在这一个函数里：
      · 领 9,999 支能把库存扣成 −9,933，`STOCK_MOVEMENT` 一条不写；
      · 账套用 `WHERE material_id=? LIMIT 1` 任意取一条，能扣别家店的账；
      · `issue_no` 用 `COUNT(*)`，并发下会撞号。
    """
    if not sess:
        return h.redirect("/login")
    if sess.get("role") not in ("assistant", "dentist", "supervisor"):
        return deny(h, "/desk/materials")
    f = h.form()
    bid = int(f.get("batch_id") or 0)
    try:
        qty = float(f.get("quantity") or 0)
    except ValueError:
        qty = 0
    # NaN/Inf 会让 SQLite 存进 NULL 或 inf，把账套彻底写坏，必须在入口挡掉
    if not math.isfinite(qty) or qty > 1000000:
        return deny(h, "/desk/materials", "数量不是一个有效数字")
    if not bid or qty <= 0:
        return deny(h, "/desk/materials", "请选择批次并填写大于 0 的数量")
    cid = staff_clinic(sess)
    if not cid:
        return deny(h, "/desk/materials", "当前账号没有绑定门店，无法扣减库存")

    c = con()
    try:
        b = c.execute("SELECT * FROM MATERIAL_BATCH WHERE batch_id=?", (bid,)).fetchone()
        if not b:
            return deny(h, "/desk/materials", "批次不存在")
        if b["expiry_date"] and str(b["expiry_date"]) < datetime.now().strftime("%Y-%m-%d"):
            return deny(h, "/desk/materials",
                        "这批耗材已于 %s 过期，不能再领用" % b["expiry_date"])
        led = c.execute(
            "SELECT ledger_id, on_hand_qty FROM STOCK_LEDGER"
            " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
            (cid, b["material_id"])).fetchone()
        if not led:
            return deny(h, "/desk/materials", "本店没有这种耗材的库存账，请先入库")
        have = float(led["on_hand_qty"] or 0)
        if qty > have:
            return deny(h, "/desk/materials",
                        "库存不足：本店现有 %s，这次要领 %s" % (num(have), num(qty)))

        # 有未归档的就诊就用它，否则留空（报表会归到「未归属」而不是丢掉）
        vid = None
        if sess.get("role") == "dentist":
            r = c.execute(
                "SELECT v.visit_id FROM VISIT v JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                " JOIN ROSTER ro ON a.roster_id=ro.roster_id"
                " JOIN DENTIST d ON ro.dentist_id=d.dentist_id"
                " WHERE d.employee_no=(SELECT staff_no FROM STAFF WHERE staff_id=?)"
                "   AND v.clinic_id=? AND date(v.visit_datetime)=date('now')"
                " ORDER BY v.visit_id DESC LIMIT 1", (sess.get("staff_id"), cid)).fetchone()
            if r:
                vid = r["visit_id"]

        no = next_no(c, "MATERIAL_ISSUE", "MI", 90000)
        c.execute("INSERT INTO MATERIAL_ISSUE(issue_no, batch_id, visit_id, clinic_id,"
                  " quantity, issued_datetime, issued_by) VALUES(?,?,?,?,?,?,?)",
                  (no, bid, vid, cid, qty,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sess.get("staff_id")))
        iid = c.execute("SELECT MAX(issue_id) FROM MATERIAL_ISSUE").fetchone()[0]
        # 批次余量同样要条件扣减：入库量 - 已领量 不足就整笔回滚。
        # 批次是可选的（有些耗材不吃批号），所以只在给了 batch_id 时才校验。
        if bid not in (None, "", 0):
            curb = c.execute(
                "UPDATE MATERIAL_BATCH SET issued_qty=IFNULL(issued_qty,0)+?"
                " WHERE batch_id=?"
                "   AND IFNULL(received_qty,0)-IFNULL(issued_qty,0)>=?",
                (qty, bid, qty))
            if curb.rowcount != 1:
                c.rollback()
                c.close()
                return deny(h, "/desk/materials",
                            msg="这一批的货不够了：换个批次，或者先做入库")
        # 条件更新：只有库存够的时候才扣得动。并发下后到的那条
        # WHERE 不再成立，rowcount=0，直接回滚，不会扣成负数。
        cur = c.execute(
            "UPDATE STOCK_LEDGER SET on_hand_qty=IFNULL(on_hand_qty,0)-?"
            " WHERE ledger_id=? AND IFNULL(on_hand_qty,0)>=?",
            (qty, led["ledger_id"], qty))
        if cur.rowcount != 1:
            c.rollback()
            room = c.execute("SELECT IFNULL(on_hand_qty,0) FROM STOCK_LEDGER"
                             " WHERE ledger_id=?", (led["ledger_id"],)).fetchone()[0]
            c.close()
            return deny(h, "/desk/materials",
                        "库存不够，最多还能领 %s" % num(room))
        c.execute("INSERT INTO STOCK_MOVEMENT(ledger_id, movement_type, quantity,"
                  " source_type, source_no, moved_datetime)"
                  " VALUES(?,?,?,?,?,?)",
                  (led["ledger_id"], "出库", -qty, "领用", no,
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        c.commit()
    finally:
        c.close()

    audit(sess, "MATERIAL_ISSUE", iid, "insert", None,
          "%s ×%s" % (b["batch_serial_no"] or b["batch_id"], num(qty)))
    return h.redirect("/desk/materials?ok=" + S.quote(
        "已领用 %s，本店剩余 %s" % (num(qty), num(have - qty))))


# ------------------------------------------------------------------ 店长
def p_leaves(sess, flash=""):
    c = con()
    cid = staff_clinic(sess)
    wh, args = "", ()
    if cid:
        wh, args = " WHERE l.clinic_id=?", (cid,)
    rows = c.execute(
        "SELECT l.*, d.name AS dname, cc.clinic_name FROM DENTIST_LEAVE l"
        " LEFT JOIN DENTIST d ON l.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC cc ON l.clinic_id=cc.clinic_id" + wh +
        " ORDER BY l.leave_id DESC LIMIT 40", args).fetchall()
    c.close()
    out = []
    for r in rows:
        act = ""
        if r["approval_status"] in ("待审批", None):
            act = (post_btn("批准", "/desk/leaves/%d/ok" % r["leave_id"])
                   + " " + post_btn("驳回", "/desk/leaves/%d/no" % r["leave_id"], "btn ghost sm"))
        out.append([esc(r["dname"]), esc(r["clinic_name"]),
                    esc(S.fmt_dt(r["leave_start"])), esc(S.fmt_dt(r["leave_end"])),
                    esc(r["leave_type"] or "—"), esc(r["leave_reason"] or "—"),
                    S.badge(r["approval_status"] or "待审批"), act])
    body = S.flash_ok(flash)
    body += panel("请假申请", table(["牙医", "门店", "开始", "结束", "类型", "事由", "状态", ""], out),
                  right=btn("新建请假", "/desk/leaves/new"))
    return S.page("请假审批", body, sess, "/desk/leaves")


def p_leave_new(sess, err=""):
    c = con()
    cid = staff_clinic(sess) or 1
    ds = c.execute("SELECT d.dentist_id, d.name FROM DENTIST d ORDER BY d.dentist_id").fetchall()
    c.close()
    opts = "".join('<option value="%d">%s</option>' % (d["dentist_id"], esc(d["name"])) for d in ds)
    body = S.flash_err(err) + panel(
        "登记请假",
        '<form method="post" action="/desk/leaves/new" class="f2">'
        '<div><label>牙医</label><select name="dentist_id" style="width:100%%">%s</select></div>'
        '<div><label>类型</label><select name="leave_type" style="width:100%%">'
        '<option>事假</option><option>病假</option><option>年假</option><option>培训</option></select></div>'
        '<div><label>开始</label><input type="date" name="leave_start" style="width:100%%"></div>'
        '<div><label>结束</label><input type="date" name="leave_end" style="width:100%%"></div>'
        '<div style="grid-column:1/-1"><label>事由</label>'
        '<textarea name="leave_reason"></textarea></div>'
        '<div style="grid-column:1/-1;margin-top:8px"><button class="btn">提交</button></div>'
        '</form>' % opts)
    return S.page("登记请假", body, sess, "/desk/leaves")


def r_leave_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if h.command == "POST":
        f = h.form()
        did = int(f.get("dentist_id") or 0)
        d0 = (f.get("leave_start") or "").strip()
        d1 = (f.get("leave_end") or "").strip()
        if not did:
            return h.redirect("/desk/leaves/new?err=请选择是哪位牙医请假")
        if not d0 or not d1:
            return h.redirect("/desk/leaves/new?err=请填写请假的开始与结束时间")
        if d1 < d0:
            return h.redirect("/desk/leaves/new?err=结束时间不能早于开始时间")
        c = con()
        # 这里任何异常都必须关连接：连接持着写事务不放，之后全站写操作
        # 与登录都会 500 database is locked（SQLite 单写者）。
        try:
            mine = staff_clinic(sess)
            # 请假要落在「这位牙医实际坐诊的门店」：店长给自己店的牙医登记时就是本店，
            # 牙医自报时取他排班最多的那家店。不能一律写填表人的门店。
            row = c.execute(
                "SELECT clinic_id, COUNT(*) n FROM ROSTER WHERE dentist_id=?"
                "   AND IFNULL(is_void,0)=0" + (" AND clinic_id=?" if mine else "") +
                " GROUP BY clinic_id ORDER BY n DESC LIMIT 1",
                (did, mine) if mine else (did,)).fetchone()
            lc = (row["clinic_id"] if row else (mine or 1))
            c.execute("INSERT INTO DENTIST_LEAVE(dentist_id, clinic_id, leave_start,"
                      " leave_end, leave_type, leave_reason, approval_status)"
                      " VALUES(?,?,?,?,?,?,?)",
                      (did, lc, d0, d1, f.get("leave_type"),
                       f.get("leave_reason"), "待审批"))
            lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            audit(sess, "DENTIST_LEAVE", lid, "approval_status", "", "待审批", con=c)
            c.commit()
        except Exception as e:  # noqa: BLE001
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass
            msg = str(e).split(":")[-1].strip()[:60] or "未知错误"
            return h.redirect("/desk/leaves/new?err=登记失败：%s" % msg)
        finally:
            c.close()
        return h.redirect("/desk/leaves")
    return h.send(200, p_leave_new(sess))


def r_leave_act(h, sess, lid, act):
    if not sess:
        return h.redirect("/login")
    lid = int(lid)
    if not own_row(sess, "DENTIST_LEAVE", "leave_id", "clinic_id", lid):
        return deny(h, "/desk/leaves")
    st = "已批准" if act == "ok" else "已驳回"
    killed, affected, skipped = 0, 0, 0
    c = con()
    try:
        lv = c.execute("SELECT * FROM DENTIST_LEAVE WHERE leave_id=?", (lid,)).fetchone()
        if act == "ok" and lv:
            d0 = (lv["leave_start"] or "")[:10]
            d1 = (lv["leave_end"] or d0)[:10]
            t0 = (lv["leave_start"] or "")[11:16]
            t1 = (lv["leave_end"] or "")[11:16]
            if d1 < today():
                # 过去的假批了也没意义，还会把历史排班追溯作废
                c.close()
                return h.redirect("/desk/leaves?err=这条请假已经过期，不需要再审批")
            # 只停「这人 + 这家店 + 时段真的重叠」的排班。
            # 原来按 dentist_id 全量停，一个店的店长批假会误杀掉别家店的排班。
            rows = c.execute(
                "SELECT roster_id, slot_start, slot_end FROM ROSTER"
                " WHERE dentist_id=? AND clinic_id=? AND IFNULL(is_void,0)=0"
                " AND roster_date BETWEEN ? AND ?"
                " AND (? = '' OR slot_start < ?) AND (? = '' OR slot_end > ?)",
                (lv["dentist_id"], lv["clinic_id"], d0, d1, t1, t1, t0, t0)).fetchall()
            for r in rows:
                c.execute("UPDATE ROSTER SET is_void=1, void_reason=?, void_at=?,"
                          " void_account_id=? WHERE roster_id=?",
                          ("牙医请假 %s %s 至 %s %s" % (d0, t0 or "全天", d1, t1 or "全天"),
                           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           sess.get("account_id"), r["roster_id"]))
                killed += 1
                for a in c.execute(
                        "SELECT appointment_id FROM APPOINTMENT WHERE roster_id=?"
                        " AND IFNULL(is_void,0)=0 AND status='已预约'",
                        (r["roster_id"],)).fetchall():
                    c.execute("UPDATE APPOINTMENT SET status='已取消',"
                              " cancellation_category='医生停诊', void_reason=?, void_at=?,"
                              " void_account_id=? WHERE appointment_id=?",
                              ("牙医请假停诊（请假单 %d），系统自动取消" % lid,
                               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                               sess.get("account_id"), a["appointment_id"]))
                    c.execute(
                        "INSERT INTO AUDIT_LOG(patient_id, record_table, record_id_ref,"
                        " changed_field, old_value, new_value, operator_name, changed_datetime)"
                        " VALUES((SELECT patient_id FROM APPOINTMENT WHERE appointment_id=?),"
                        " ?,?,?,?,?,?,?)",
                        (a["appointment_id"], "APPOINTMENT", str(a["appointment_id"]),
                         "status", "已预约", "已取消",
                         (sess or {}).get("display") or "system",
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    _notify_stop(c, a["appointment_id"], d0, t0, d1, t1)
                    affected += 1
        c.execute("UPDATE DENTIST_LEAVE SET approval_status=?, approver_staff_id=?,"
                  " approved_date=? WHERE leave_id=?",
                  (st, sess.get("staff_id"), today(), lid))
        c.commit()
    except Exception as e:
        c.rollback()
        sys.stderr.write("leave_act 失败: %r\n" % (e,))
        return h.redirect("/desk/leaves?err=操作失败：" + str(e)[:60])
    finally:
        c.close()
    audit(sess, "DENTIST_LEAVE", lid, "approval_status", None, st)
    msg = "已批准" if act == "ok" else "已驳回"
    if killed:
        msg += "，停诊 %d 个排班、取消 %d 条预约" % (killed, affected)
    return h.redirect("/desk/leaves?ok=" + msg)



def p_shifts(sess, flash=""):
    c = con()
    cid = staff_clinic(sess)
    wh, args = "", ()
    if cid:
        wh, args = " WHERE s.clinic_id=?", (cid,)
    rows = c.execute(
        "SELECT s.*, d.name AS dname, cc.clinic_name FROM SHIFT_REQUEST s"
        " LEFT JOIN DENTIST d ON s.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC cc ON s.clinic_id=cc.clinic_id" + wh +
        " ORDER BY s.request_id DESC LIMIT 40", args).fetchall()
    c.close()
    out = []
    for r in rows:
        act = ""
        if (r["request_status"] or "待审批") == "待审批":
            act = (post_btn("批准", "/desk/shifts/%d/ok" % r["request_id"])
                   + " " + post_btn("驳回", "/desk/shifts/%d/no" % r["request_id"], "btn ghost sm"))
        out.append([esc(r["dname"]), esc(r["clinic_name"]), esc(r["request_date"]),
                    "%s — %s" % (esc(r["slot_start"] or ""), esc(r["slot_end"] or "")),
                    esc(r["direction"] or "—"), esc(r["reason"] or "—"),
                    S.badge(r["request_status"] or "待审批"), act])
    body = S.flash_ok(flash)
    body += panel("调班申请", table(["牙医", "门店", "日期", "时段", "方向", "事由", "状态", ""], out))
    return S.page("调班审批", body, sess, "/desk/shifts")


def r_shift_act(h, sess, sid, act):
    if not sess:
        return h.redirect("/login")
    sid = int(sid)
    if not own_row(sess, "SHIFT_REQUEST", "request_id", "clinic_id", sid):
        return deny(h, "/desk/shifts")
    st = "已批准" if act == "ok" else "已驳回"
    made = 0
    c = con()
    try:
        sr = c.execute("SELECT * FROM SHIFT_REQUEST WHERE request_id=?", (sid,)).fetchone()
        c.execute("UPDATE SHIFT_REQUEST SET request_status=?, approver_staff_id=?,"
                  " approved_date=? WHERE request_id=?",
                  (st, sess.get("staff_id"), today(), sid))
        if act == "ok" and sr:
            # 调班批准要落一条替班记录，否则「谁替谁」永远查不到。
            # 申请表里没有「想跟谁换」这一列，只能取同店同日另一位牙医；
            # 取不到就只记调出，别编一个不存在的人。
            sub_did = None
            cand = c.execute(
                "SELECT DISTINCT dentist_id FROM ROSTER WHERE clinic_id=?"
                " AND roster_date=? AND dentist_id<>? AND IFNULL(is_void,0)=0"
                " LIMIT 1", (sr["clinic_id"], sr["request_date"],
                             sr["dentist_id"])).fetchone()
            if cand:
                sub_did = cand[0]
            dup = c.execute(
                "SELECT COUNT(*) FROM SHIFT_SUBSTITUTION WHERE request_id=?",
                (sid,)).fetchone()[0]
            if not dup:
                rid = c.execute(
                    "SELECT roster_id FROM ROSTER WHERE clinic_id=? AND dentist_id=?"
                    " AND roster_date=? ORDER BY slot_start LIMIT 1",
                    (sr["clinic_id"], sr["dentist_id"], sr["request_date"])).fetchone()
                c.execute(
                    "INSERT INTO SHIFT_SUBSTITUTION(roster_id, absent_dentist_id,"
                    " substitute_dentist_id, source_clinic_id, effective_from,"
                    " effective_to, reason_type, request_id)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (rid[0] if rid else None, sr["dentist_id"], sub_did,
                     sr["clinic_id"], sr["request_date"], sr["request_date"],
                     sr["direction"] or "调班", sid))
                made = 1
        c.commit()
    except Exception as e:
        c.rollback()
        sys.stderr.write("shift_act 失败: %r\n" % (e,))
        return h.redirect("/desk/shifts?err=操作失败：" + str(e)[:60])
    finally:
        c.close()
    audit(sess, "SHIFT_REQUEST", sid, "request_status", None, st)
    return h.redirect("/desk/shifts?ok=" + ("已批准" if act == "ok" else "已驳回")
                      + ("，已生成替班记录" if made else ""))



def p_complaints(sess, flash=""):
    c = con()
    cid = staff_clinic(sess)
    wh, args = "", ()
    if cid:
        wh, args = " WHERE m.clinic_id=?", (cid,)
    rows = c.execute(
        "SELECT m.*, p.name AS pname, cc.clinic_name FROM COMPLAINT m"
        " LEFT JOIN PATIENT p ON m.patient_id=p.patient_id"
        " LEFT JOIN CLINIC cc ON m.clinic_id=cc.clinic_id" + wh +
        " ORDER BY m.complaint_id DESC LIMIT 40", args).fetchall()
    c.close()
    out = []
    for r in rows:
        act = ""
        if (r["status"] or "待处理") == "待处理":
            act = ('<a class="btn sm" href="/desk/complaints/%d/done">处理</a>'
                   % r["complaint_id"])
        out.append([esc(r["filed_date"]), esc(r["pname"]), esc(r["clinic_name"]),
                    esc(r["channel"] or "—"), esc((r["content"] or "")[:40]),
                    esc(r["resolution"] or "—"), S.badge(r["status"] or "待处理"), act])
    body = S.flash_ok(flash)
    body += panel("投诉处理", table(["日期", "患者", "门店", "渠道", "内容", "处理结果", "状态", ""], out),
                  right=btn("登记投诉", "/desk/complaints/new"))
    return S.page("投诉", body, sess, "/desk/complaints")


def p_complaint_new(sess, err=""):
    c = con()
    cid = staff_clinic(sess) or 1
    ps = c.execute("SELECT patient_id, name FROM PATIENT ORDER BY patient_id DESC LIMIT 80").fetchall()
    c.close()
    opts = "".join('<option value="%d">%s</option>' % (p["patient_id"], esc(p["name"])) for p in ps)
    body = S.flash_err(err) + panel(
        "登记投诉",
        '<form method="post" action="/desk/complaints/new" class="f2">'
        '<div><label>患者</label><select name="patient_id" style="width:100%%">%s</select></div>'
        '<div><label>渠道</label><select name="channel" style="width:100%%">'
        '<option>电话</option><option>到店</option><option>小程序</option><option>回访</option>'
        '</select></div>'
        '<div style="grid-column:1/-1"><label>内容</label><textarea name="content"></textarea></div>'
        '<div style="grid-column:1/-1;margin-top:8px"><button class="btn">提交</button></div>'
        '</form>' % opts)
    return S.page("登记投诉", body, sess, "/desk/complaints")


def r_complaint_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if h.command == "POST":
        f = h.form()
        c = con()
        c.execute("INSERT INTO COMPLAINT(patient_id, clinic_id, channel, content, filed_date, status)"
                  " VALUES(?,?,?,?,?,?)",
                  (int(f.get("patient_id") or 0), staff_clinic(sess) or 1,
                   f.get("channel"), f.get("content"), today(), "待处理"))
        c.commit()
        nid = c.execute("SELECT MAX(complaint_id) FROM COMPLAINT").fetchone()[0]
        c.close()
        audit(sess, "COMPLAINT", nid, "insert", None, (f.get("content") or "")[:40])
        return h.redirect("/desk/complaints?ok=已登记投诉")
    return h.send(200, p_complaint_new(sess))


def r_complaint_form(h, sess, cid):
    """处理投诉的表单页。"""
    if not sess:
        return h.redirect("/login")
    if not own_row(sess, "COMPLAINT", "complaint_id", "clinic_id", cid):
        return deny(h, "/desk/complaints")
    c = con()
    r = c.execute(
        "SELECT m.*, p.name AS pname FROM COMPLAINT m"
        " LEFT JOIN PATIENT p ON p.patient_id=m.patient_id"
        " WHERE m.complaint_id=?", (int(cid),)).fetchone()
    c.close()
    if not r:
        return h.redirect("/desk/complaints?err=没有这条投诉")
    info = table(["项目", "内容"], [
        ["患者", esc(r["pname"] or "—")],
        ["投诉日期", esc(r["filed_date"] or "—")],
        ["渠道", esc(r["channel"] or "—")],
        ["原文", esc(r["content"] or "—")],
        ["当前状态", esc(r["status"] or "待处理")],
    ])
    done = (r["status"] or "") == "已处理"
    if done:
        formbody = ('<p class="sub">这条已经处理过，处理结论是：</p><p>%s</p>'
                    '<a class="btn ghost" href="/desk/complaints">返回</a>'
                    % esc(r["resolution"] or "—"))
    else:
        formbody = (
            '<label class="f">处理结论（必填，会写进记录）</label>'
            '<textarea name="resolution" rows="4" required '
            'placeholder="例：已电话回访致歉，退还本次挂号费，赠送洁牙一次"></textarea>'
            '<label class="f" style="margin-top:12px">'
            '<input type="checkbox" name="notify" value="1" checked> '
            '把结论作为站内通知发给患者</label>'
            '<div class="row" style="margin-top:14px">'
            '<button class="btn" type="submit">保存并标记已处理</button>'
            '<a class="btn ghost" href="/desk/complaints">返回</a></div>')
    body = ('<div class="panel"><div class="h">投诉内容</div><div class="bd">'
            + info + '</div></div>'
            + '<form class="panel" method="post" action="/desk/complaints/%d/done">'
              '<div class="h">处理结论</div><div class="bd">%s</div></form>'
              % (int(cid), formbody))
    return h.send(200, S.page("处理投诉", body, sess, "/desk/complaints"))


def r_complaint_done(h, sess, cid):
    if not sess:
        return h.redirect("/login")
    if not own_row(sess, "COMPLAINT", "complaint_id", "clinic_id", cid):
        return deny(h, "/desk/complaints")
    f = h.form()
    res = (f.get("resolution") or "").strip()
    if len(res) < 4:
        return h.redirect("/desk/complaints/%d/done?err=处理结论至少要写几个字" % int(cid))
    c = con()
    row = c.execute("SELECT patient_id FROM COMPLAINT WHERE complaint_id=?",
                    (int(cid),)).fetchone()
    c.execute("UPDATE COMPLAINT SET status='已处理', resolution=? WHERE complaint_id=?",
              (res, int(cid)))
    c.commit()
    c.close()
    audit(sess, "COMPLAINT", cid, "status", "待处理", "已处理")
    if f.get("notify") and row and row["patient_id"]:
        try:
            import biz2
            biz2.notify(sess, row["patient_id"], "投诉处理",
                        "您反映的问题已处理", res, "COMPLAINT", int(cid))
        except Exception as e:
            sys.stderr.write("[complaint notify] %s\n" % e)
    return h.redirect("/desk/complaints?ok=已记录处理结论")


def p_perf(sess):
    c = con()
    cid = staff_clinic(sess)
    wh, args = "", ()
    if cid:
        wh, args = " AND r.clinic_id=?", (cid,)
    rows = c.execute(
        "SELECT d.name AS dname, COUNT(v.visit_id) AS n_visit,"
        " (SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
        "   JOIN INVOICE i ON l.invoice_id=i.invoice_id WHERE i.visit_id IN"
        "   (SELECT v2.visit_id FROM VISIT v2 JOIN APPOINTMENT a2 ON v2.appointment_id=a2.appointment_id"
        "    JOIN ROSTER r2 ON a2.roster_id=r2.roster_id WHERE r2.dentist_id=d.dentist_id)) AS revenue"
        " FROM DENTIST d"
        " LEFT JOIN ROSTER r ON r.dentist_id=d.dentist_id"
        " LEFT JOIN APPOINTMENT a ON a.roster_id=r.roster_id"
        " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " WHERE 1=1" + wh +
        " GROUP BY d.dentist_id ORDER BY revenue DESC", args).fetchall()
    c.close()
    out = [[esc(r["dname"]), num(r["n_visit"]), money(r["revenue"])] for r in rows]
    body = panel("牙医业绩（按结算金额）", table(["牙医", "接诊人次", "累计结算金额"], out))
    return S.page("业绩", body, sess, "/desk/performance")


# ------------------------------------------------------------------ 总部运营
def p_hq(sess):
    c = con()
    t = today()
    n_clinic = c.execute("SELECT COUNT(*) FROM CLINIC").fetchone()[0]
    n_today = c.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE date(appointment_datetime)=?",
                        (t,)).fetchone()[0]
    n_dentist = c.execute("SELECT COUNT(*) FROM DENTIST WHERE active=1").fetchone()[0]
    rev = c.execute("SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
                    " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
                    " WHERE i.invoice_date>=?", (t[:8] + "01",)).fetchone()[0]
    rows = []
    for cl in c.execute("SELECT * FROM CLINIC ORDER BY clinic_id").fetchall():
        n = c.execute("SELECT COUNT(*) FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
                      " WHERE r.clinic_id=? AND date(a.appointment_datetime)=?",
                      (cl["clinic_id"], t)).fetchone()[0]
        money_cl = c.execute("SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
                             " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
                             " JOIN VISIT v ON i.visit_id=v.visit_id"
                             " WHERE v.clinic_id=?", (cl["clinic_id"],)).fetchone()[0]
        rows.append([esc(cl["clinic_name"]), esc(cl["region"] or "—"),
                     esc(cl["phone"] or "—"), num(n), money(money_cl)])
    c.close()
    body = ('<div class="grid g3">%s%s%s</div>'
            % (S.stat(n_clinic, "在营门店", "连锁总数"),
               S.stat(n_today, "今日预约", "全部门店"),
               S.stat(money(rev), "本月已结算", "元")))
    body += panel("门店对比", table(["门店", "所在区域", "电话", "今日预约", "累计结算"], rows))
    return S.page("总部看板", body, sess, "/desk")


def p_clinics(sess):
    c = con()
    rows = []
    for cl in c.execute("SELECT * FROM CLINIC ORDER BY clinic_id").fetchall():
        nd = c.execute("SELECT COUNT(DISTINCT dentist_id) FROM ROSTER WHERE clinic_id=?",
                       (cl["clinic_id"],)).fetchone()[0]
        rows.append([esc(cl["clinic_name"]), esc(cl["region"] or "—"),
                     esc(cl["postal_address"] or "—"), esc(cl["manager_name"] or "—"),
                     esc(cl["phone"] or "—"), num(nd),
                     esc(cl["service_scope"] or "—"),
                     esc(cl["license_no"] or "—"), esc(cl["license_valid_until"] or "—")])
    c.close()
    body = panel("门店", table(["门店", "区域", "地址", "负责人", "电话", "可排班牙医",
                              "诊疗科目", "执业许可证", "有效期至"], rows))
    return S.page("门店", body, sess, "/desk/clinics")


def p_requisitions(sess):
    c = con()
    rows = c.execute(
        "SELECT s.*, d.name AS dname, f.clinic_name AS fname, t.clinic_name AS tname"
        " FROM SHIFT_REQUISITION s"
        " LEFT JOIN DENTIST d ON s.dentist_id=d.dentist_id"
        " LEFT JOIN CLINIC f ON s.from_clinic_id=f.clinic_id"
        " LEFT JOIN CLINIC t ON s.to_clinic_id=t.clinic_id"
        " ORDER BY s.requisition_id DESC LIMIT 40").fetchall()
    c.close()
    out = []
    for r in rows:
        act = ""
        if (r["requisition_status"] or "待审批") == "待审批":
            act = post_btn("批准", "/desk/requisitions/%d/ok" % r["requisition_id"])
        out.append([esc(r["dname"]), esc(r["fname"]), esc(r["tname"]),
                    esc(r["requisition_date"]),
                    "%s—%s" % (esc(r["start_time"] or ""), esc(r["end_time"] or "")),
                    esc(r["requisition_reason"] or "—"),
                    S.badge(r["requisition_status"] or "待审批"), act])
    body = panel("跨店征调单",
                 '<p class="muted">医生请假或某店临时缺人时，由总部从别店征调。'
                 '批准后这张单据就是调度依据。</p>'
                 + table(["牙医", "调出门店", "调入门店", "日期", "时段", "原因", "状态", ""], out))
    return S.page("跨店征调", body, sess, "/desk/requisitions")


def r_requisition_act(h, sess, rid, act):
    if not sess:
        return h.redirect("/login")
    # 跨店征调是总部的调度权；店长只能批「调进本店」的那一条。
    if sess.get("desk") not in ("hq", "manager", "admin"):
        return deny(h, "/desk/requisitions", msg="跨店征调要总部或店长来批")
    st = "已批准" if act == "ok" else "已驳回"
    c = con()
    rq = c.execute("SELECT * FROM SHIFT_REQUISITION WHERE requisition_id=?",
                   (int(rid),)).fetchone()
    c.execute("UPDATE SHIFT_REQUISITION SET requisition_status=?, approver_account_id=?,"
              " approved_at=? WHERE requisition_id=?",
              (st, sess.get("account_id"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(rid)))
    made = 0
    if act == "ok" and rq:
        # 征调批准后必须在调入门店真的排上班，否则只是改了个状态
        # 按起止时间精确判重：同一天同一个医生可能有上午/下午两段
        has = c.execute(
            "SELECT roster_id FROM ROSTER WHERE clinic_id=? AND dentist_id=?"
            " AND roster_date=? AND slot_start=? AND slot_end=?",
            (rq["to_clinic_id"], rq["dentist_id"], rq["requisition_date"],
             rq["start_time"], rq["end_time"])).fetchone()
        if not has:
            # 征调是已批准的人力安排，生成即为已发布；否则患者永远看不到，
            # 而直接 POST 又能下进来（列表隐藏 + 下单不校验 = 最坏组合）。
            c.execute(
                "INSERT INTO ROSTER(clinic_id, dentist_id, roster_date, slot_start,"
                " slot_end, slot_capacity, roster_status, is_published)"
                " VALUES(?,?,?,?,?,?,?,1)",
                (rq["to_clinic_id"], rq["dentist_id"], rq["requisition_date"],
                 rq["start_time"], rq["end_time"], 6, "征调排班"))
            made = 1
            # 同一天同一个医生不能同时在两家店出诊：把调出店重叠的排班停掉
            c.execute(
                "UPDATE ROSTER SET is_void=1, void_reason=?, void_at=?, void_account_id=?"
                " WHERE clinic_id=? AND dentist_id=? AND roster_date=?"
                " AND IFNULL(is_void,0)=0 AND slot_start < ? AND slot_end > ?",
                ("已征调至门店 %s" % rq["to_clinic_id"],
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sess.get("account_id"),
                 rq["from_clinic_id"], rq["dentist_id"], rq["requisition_date"],
                 rq["end_time"], rq["start_time"]))
    c.commit()
    c.close()
    audit(sess, "SHIFT_REQUISITION", rid, "requisition_status", None, st)
    return h.redirect("/desk/requisitions?ok=" + ("已批准" if act == "ok" else "已驳回")
                      + ("，已在调入门店生成排班" if made else ""))


def p_quality(sess):
    c = con()
    rows = c.execute(
        "SELECT q.*, cc.clinic_name FROM QUALITY_INCIDENT q"
        " LEFT JOIN CLINIC cc ON q.clinic_id=cc.clinic_id"
        " ORDER BY q.incident_id DESC LIMIT 40").fetchall()
    c.close()
    out = [[esc(r["occurred_date"]), esc(r["clinic_name"]), esc(r["incident_type"] or "—"),
            esc((r["description"] or "")[:50]), esc(r["severity"] or "—"),
            S.badge(r["status"] or "待处理")] for r in rows]
    body = panel("质量事件", table(["日期", "门店", "类型", "描述", "严重度", "状态"], out))
    return S.page("质量事件", body, sess, "/desk/quality")


def p_accounts(sess):
    c = con()
    rows = c.execute("SELECT * FROM USER_ACCOUNT ORDER BY account_id").fetchall()
    out = []
    for r in rows:
        out.append([esc(r["login_name"]), esc(S.ROLE_CN.get(r["role"], r["role"])),
                    esc(r["account_status"] or "正常"),
                    esc(S.fmt_dt(r["registered_at"])), esc(S.fmt_dt(r["last_login_at"]) or "—")])
    c.close()
    body = panel("账号", table(["登录名", "角色", "状态", "注册时间", "最近登录"], out))
    return S.page("账号", body, sess, "/desk/accounts")


def p_audit(sess):
    c = con()
    rows = c.execute("SELECT * FROM AUDIT_LOG ORDER BY audit_log_id DESC LIMIT 50").fetchall()
    c.close()
    out = [[esc(S.fmt_dt(r["changed_datetime"])), esc(r["record_table"]),
            esc(r["changed_field"] or "—"), esc(r["old_value"] or "—"),
            esc(r["new_value"] or "—"), esc(r["operator_name"] or "—")] for r in rows]
    body = panel("审计日志", table(["时间", "表", "字段", "原值", "新值", "操作人"], out,
                                   "还没有审计记录——目前只有变更留痕表被写入时才产生。"))
    return S.page("审计日志", body, sess, "/desk/audit")


# ------------------------------------------------------------------ 财务
def p_invoices(sess, q="", st=""):
    c = con()
    wh, args = ["1=1"], []
    # 前台/牙医/助手只看本店；总部与财务看全连锁
    _cid = staff_clinic(sess)
    if _cid is not None:
        wh.append("v.clinic_id=?")
        args.append(_cid)
    if q:
        wh.append("(i.invoice_no LIKE ? OR p.name LIKE ?)")
        args += ["%" + q + "%", "%" + q + "%"]
    if st:
        wh.append("i.status=?")
        args.append(st)
    SEL = ("SELECT i.*, p.name AS pname, cc.clinic_name,"
           " (SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
           "   WHERE l.invoice_id=i.invoice_id) AS due,"
           " (SELECT IFNULL(SUM(y.amount),0) FROM PAYMENT y"
           "   WHERE y.invoice_id=i.invoice_id AND IFNULL(y.is_void,0)=0) AS paid"
           " FROM INVOICE i LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
           " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
           " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
           " LEFT JOIN CLINIC cc ON v.clinic_id=cc.clinic_id"
           " WHERE " + " AND ".join(wh))
    rows = c.execute(SEL + " ORDER BY i.invoice_id DESC LIMIT 300",
                     tuple(args)).fetchall()
    # 统计卡走全量：这里不能复用 rows（那是 LIMIT 300 之后的窗口值）
    agg = c.execute(
        "SELECT COUNT(*) n, IFNULL(SUM(due),0) t, IFNULL(SUM(paid),0) pd,"
        "       IFNULL(SUM(CASE WHEN due > paid + 0.01 THEN due - paid ELSE 0 END),0) gap"
        " FROM (SELECT (SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
        "              WHERE l.invoice_id=i.invoice_id) due,"
        "              (SELECT IFNULL(SUM(y.amount),0) FROM PAYMENT y"
        "              WHERE y.invoice_id=i.invoice_id AND IFNULL(y.is_void,0)=0) paid"
        "       FROM INVOICE i LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        "       LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        "       LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        "       WHERE " + " AND ".join(wh) + ")",
        tuple(args)).fetchone()
    c.close()
    out = []
    for r in rows:
        gap = money_float(r["due"]) - money_float(r["paid"])
        out.append([('<a href="/desk/invoice/%s">%s</a>'
                     % (r["invoice_id"], esc(r["invoice_no"]))),
                    esc(r["pname"]), esc(r["clinic_name"]),
                    esc(r["invoice_date"]), money(r["due"]), money(r["paid"]),
                    ('<b style="color:#c2410c">%s</b>' % money(gap)) if gap > 0.01 else "—",
                    S.badge(inv_state(money_float(r["due"]), money_float(r["paid"])))])
    body = ('<div class="grid g3">%s%s%s</div>'
            % (S.stat(agg["n"], "结算单", "当前筛选下的全量"),
               S.stat(money(agg["t"]), "应收", "全量，非本页小计"),
               S.stat(money(agg["gap"]), "未收", "全量；本页最多列 300 条")))
    body += panel("结算单",
                  '<form method="get" class="f" style="margin-bottom:14px">'
                  '<input name="q" value="%s" placeholder="单号或患者">'
                  '<select name="st"><option value="">全部状态</option>'
                  '<option %s>待收款</option><option %s>已收款</option></select>'
                  '<button class="btn">筛选</button></form>'
                  % (esc(q), "selected" if st == "待收款" else "",
                     "selected" if st == "已收款" else "") +
                  table(["单号", "患者", "门店", "日期", "应收", "已收", "未收", "状态"], out))
    return S.page("结算单", body, sess, "/desk/invoices")


def r_invoices(h, sess):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    return h.send(200, p_invoices(sess, (qs.get("q") or [""])[0], (qs.get("st") or [""])[0]))


def p_reports(sess):
    """门店经营报表：分「收入 → 直接成本 → 毛利 → 运营费用 → 净利」五段。

    两个口径在这里定死，别处不要再另算一套：
      · 直接成本 = 标准成本（STANDARD_COST 当前版本 × 治疗项目用量）。耗材领用
        只是直接成本的一部分，拿它当全部成本会算出 85% 的净利率。
      · 耗材实际发生额单独列一列，按**就诊门店**归集（领用人只用于库存稽核）。
    """
    c = con()
    ver = c.execute("SELECT IFNULL(MAX(version_id),0) v FROM COST_VERSION").fetchone()["v"]
    rows = []
    tot = dict(rev=0.0, std=0.0, mat=0.0, opex=0.0, alloc=0.0, n=0)
    for cl in c.execute("SELECT * FROM CLINIC ORDER BY clinic_id").fetchall():
        cid = cl["clinic_id"]
        rev = money_float(c.execute(
            "SELECT IFNULL(SUM(l.line_subtotal),0) FROM INVOICE_LINE l"
            " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
            " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
            " WHERE v.clinic_id=? AND IFNULL(i.is_void,0)=0"
            "   AND IFNULL(i.status,'')<>'已作废'", (cid,)).fetchone()[0])
        # 标准成本：按这次就诊用掉的治疗项目 × 当前版本标准成本
        std = money_float(c.execute(
            "SELECT IFNULL(SUM(ti.standard_units * IFNULL(sc.standard_cost,0)),0)"
            " FROM TREATMENT_ITEM ti"
            " JOIN VISIT v ON ti.visit_id=v.visit_id"
            " LEFT JOIN STANDARD_COST sc ON sc.catalog_id=ti.catalog_id"
            "   AND sc.version_id=?"
            " WHERE v.clinic_id=?", (ver, cid)).fetchone()[0])
        # 耗材：按就诊门店归集。领用单确实带 visit_id（104 条全有），
        # 按领用人算会把余杭的成本整笔算到城西/滨江头上。
        mat = money_float(c.execute(
            "SELECT IFNULL(SUM(iss.quantity * b.purchase_unit_price),0)"
            " FROM MATERIAL_ISSUE iss"
            " JOIN MATERIAL_BATCH b ON iss.batch_id=b.batch_id"
            " LEFT JOIN VISIT v ON iss.visit_id=v.visit_id"
            " WHERE v.clinic_id=?", (cid,)).fetchone()[0])
        opex = money_float(c.execute(
            "SELECT IFNULL(SUM(amount),0) FROM OPERATING_EXPENSE WHERE clinic_id=?",
            (cid,)).fetchone()[0])
        alloc = money_float(c.execute(
            "SELECT IFNULL(SUM(allocated_amount),0) FROM EXPENSE_ALLOCATION"
            " WHERE clinic_id=?", (cid,)).fetchone()[0])
        n = c.execute("SELECT COUNT(*) FROM VISIT WHERE clinic_id=?",
                      (cid,)).fetchone()[0]
        # 门店级：本店费用 + 从别店分进来的 - 本店分出去的
        alloc_in = money_float(c.execute(
            "SELECT IFNULL(SUM(allocated_amount),0) FROM EXPENSE_ALLOCATION"
            " WHERE clinic_id=?", (cid,)).fetchone()[0])
        alloc_out = money_float(c.execute(
            "SELECT IFNULL(SUM(a.allocated_amount),0) FROM EXPENSE_ALLOCATION a"
            " JOIN OPERATING_EXPENSE e ON a.expense_id=e.expense_id"
            " WHERE e.clinic_id=? AND a.clinic_id<>?", (cid, cid)).fetchone()[0])
        opex_shown = opex + alloc_in - alloc_out
        gross = rev - std
        net = gross - opex_shown
        for k, v in (("rev", rev), ("std", std), ("mat", mat),
                     ("opex", opex), ("alloc", alloc), ("n", n)):
            tot[k] += v
        rows.append([esc(cl["clinic_name"]), num(n), money(rev), money(std),
                     money(gross), ("%.1f%%" % (100.0 * gross / rev)) if rev else "—",
                     money(mat), money(opex_shown), money(net),
                     ("%.1f%%" % (100.0 * net / rev)) if rev else "—"])
    null_issue, null_mat = c.execute(
        "SELECT COUNT(*), IFNULL(SUM(iss.quantity * b.purchase_unit_price),0)"
        " FROM MATERIAL_ISSUE iss JOIN MATERIAL_BATCH b ON iss.batch_id=b.batch_id"
        " LEFT JOIN VISIT v ON iss.visit_id=v.visit_id"
        " WHERE v.visit_id IS NULL").fetchone()
    # 没有就诊记录的结算单：它的收入不属于任何门店，但必须计入合计，
    # 否则「合计收入」和账面总额永远差这一块，且页面上看不出来。
    orphan_n, orphan_rev = c.execute(
        "SELECT COUNT(*), IFNULL(SUM(l.line_subtotal),0)"
        " FROM INVOICE i"
        " LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
        " JOIN INVOICE_LINE l ON l.invoice_id=i.invoice_id"
        " WHERE v.visit_id IS NULL AND IFNULL(i.is_void,0)=0"
        "   AND IFNULL(i.status,'')<>'已作废'").fetchone()
    alloc_total = money_float(c.execute(
        "SELECT IFNULL(SUM(allocated_amount),0) FROM EXPENSE_ALLOCATION").fetchone()[0])
    dr = c.execute("SELECT MIN(d), MAX(d) FROM ("
                   " SELECT date(invoice_date) d FROM INVOICE"
                   " WHERE IFNULL(is_void,0)=0)").fetchone()
    d0, d1 = dr[0], dr[1]
    c.close()
    tot["rev"] += money_float(orphan_rev)      # 合计口径要含无就诊记录的收入
    gross = tot["rev"] - tot["std"]
    # 合并层面：分摊是门店之间的内部转移，加总后应抵销，不能再扣一遍
    net = gross - tot["opex"]
    if orphan_rev and orphan_rev > 0.01:
        rows.append(["未归属（无就诊记录）", "—", money(orphan_rev), "—", "—", "—",
                     "—", "—", "—", "—"])
    if null_mat and null_mat > 0.01:
        rows.append(["未归属（无关联就诊）", "—", "—", "—", "—", "—",
                     money(null_mat), "—", "—", "—"])
    rows.append(["<b>合计</b>", "<b>%s</b>" % num(tot["n"]), "<b>%s</b>" % money(tot["rev"]),
                 "<b>%s</b>" % money(tot["std"]), "<b>%s</b>" % money(gross),
                 "<b>%.1f%%</b>" % (100.0 * gross / tot["rev"]) if tot["rev"] else "—",
                 "<b>%s</b>" % money(tot["mat"] + (null_mat or 0)),
                 "<b>%s</b>" % money(tot["opex"]),
                 "<b>%s</b>" % money(net),
                 "<b>%.1f%%</b>" % (100.0 * net / tot["rev"]) if tot["rev"] else "—"])
    body = panel("门店经营（累计）",
                 table(["门店", "就诊人次", "收入", "直接成本", "毛利", "毛利率",
                        "耗材实际", "运营费用", "净利", "净利率"], rows),
                 right=btn("耗材明细", "/desk/materials", "btn ghost sm"))
    body += ('<div class="card" style="margin-top:16px"><h3>口径说明</h3>'
             '<p><b>直接成本</b>取标准成本（<code>STANDARD_COST</code> 版本 %d 对治疗项目'
             '用量），不是耗材领用——把领用当全部成本会算出八成以上的净利率，量级不成立。</p>'
             '<p><b>耗材实际</b>＝领用数量 × 批次采购单价，按<b>就诊门店</b>归集；'
             '没有关联就诊的领用（当前 %d 笔、%s 元）归「未归属」，不进任何门店损益——'
             '这是数据缺口，不是成本消失。</p>'
             '<p><b>运营费用</b>合计只算 <code>OPERATING_EXPENSE</code> 全额。'
             '<code>EXPENSE_ALLOCATION</code> 是门店之间的<b>内部转移</b>：门店级计入分进来的、'
             '扣掉分出去的，合计层面抵销，不再重复扣一遍（上一版重复计入 %s 元，'
             '净利被低估了同样的数）。</p>'
             '<p>期间不一致要留意：收入覆盖 %s 至 %s，运营费用是 2026Q4 <b>整季</b>口径，'
             '两者相减只能看趋势，不能当精确净利。</p>'
             '<p>3–4 成毛利率对口腔连锁是正常区间；这里没有扣医生提成、技工费与税费。</p></div>'
             % (ver, null_issue, money(null_mat), money(alloc_total), d0 or "—", d1 or "—"))
    return S.page("经营报表", body, sess, "/desk/reports")


# ------------------------------------------------------------------ 注册
MENU_FULL = {
    "patient": [("/me", "我的首页", "home"), ("/me/book", "去预约", "plus"),
                ("/me/appointments", "我的预约", "cal"), ("/me/visits", "就诊与账单", "doc")],
    "frontdesk": [("/desk", "前台看板", "home"), ("/desk/appointments", "预约排队", "cal"),
                  ("/desk/book", "代客预约", "plus"), ("/desk/walkin", "散客挂号", "plus"),
                  ("/desk/patients", "患者检索", "doc")],
    "doctor": [("/desk", "我的诊台", "home"), ("/desk/schedule", "我的排班", "cal"),
               ("/desk/performance", "业绩", "doc")],
    "assistant": [("/desk", "助手台", "home"), ("/desk/materials", "耗材领用", "doc"),
                  ("/desk/patients", "患者检索", "doc")],
    "manager": [("/desk", "店长看板", "home"), ("/desk/schedule", "门店排班", "cal"),
                ("/desk/leaves", "请假审批", "doc"), ("/desk/shifts", "调班审批", "cal"),
                ("/desk/complaints", "投诉", "doc"), ("/desk/performance", "业绩", "db")],
    "hq": [("/desk", "总部看板", "home"), ("/desk/clinics", "门店", "home"),
           ("/desk/requisitions", "跨店征调", "cal"), ("/desk/quality", "质量事件", "doc"),
           ("/desk/invoices", "结算单", "doc"), ("/desk/reports", "经营报表", "db"),
           ("/desk/accounts", "账号", "home"), ("/desk/audit", "审计日志", "db"),
           ("/db-status", "数据状态", "db")],
    "finance": [("/desk", "财务看板", "home"), ("/desk/invoices", "结算单", "doc"),
                ("/desk/reports", "经营报表", "db"), ("/db-status", "数据状态", "db")],
}


def register(mod):
    """mod 是正在运行的 server 模块。

    python app/server.py 时本文件叫 __main__，biz 里若 import server 会
    重新加载一份副本、拿到另一个 ROUTES 列表，路由全注册到副本上，
    而请求由 __main__.Handler 处理 —— 表现就是所有新页面 404。
    """
    global S
    S = mod
    S.CSS += EXTRA_CSS
    S.MENU.clear()
    for k, v in MENU_FULL.items():
        S.MENU[k] = v

    def g(p, fn):
        S.ROUTES.append(("GET", __import__("re").compile("^" + p + "$"), fn))

    def po(p, fn):
        S.ROUTES.append(("POST", __import__("re").compile("^" + p + "$"), fn))

    g(r"/desk/book", r_desk_book_list)
    g(r"/desk/book/(\d+)", r_desk_book_pick)
    po(r"/desk/book/do", r_desk_book_do)
    g(r"/me/visit/(\d+)", r_visit_detail)
    g(r"/me/reschedule/(\d+)", r_reschedule_form)
    po(r"/me/reschedule/(\d+)", r_reschedule_do)

    g(r"/visit/(\d+)", r_visit_detail)
    g(r"/desk/appointments", r_queue2)
    po(r"/desk/checkin/(\d+)", r_checkin)
    g(r"/desk/reschedule/(\d+)", r_desk_reschedule_form)
    po(r"/desk/reschedule/(\d+)", r_desk_reschedule_do)
    po(r"/desk/noshow/(\d+)", r_desk_noshow)
    po(r"/desk/cancel/(\d+)", r_desk_cancel)
    g(r"/desk/walkin", r_walkin_form)
    po(r"/desk/walkin", r_walkin_do)
    g(r"/desk/patient/(\d+)", r_patient_detail)
    g(r"/desk/patients", r_patients2)
    g(r"/desk/invoice/(\d+)", r_invoice)
    po(r"/desk/invoice/(\d+)/create", r_invoice_create)
    po(r"/desk/invoice/(\d+)/pay", r_invoice_pay)
    po(r"/desk/invoice/(\d+)/void", r_invoice_void)
    po(r"/desk/invoice/(\d+)/sync", r_invoice_sync)
    g(r"/desk/invoice/(\d+)/refund", r_refund_form)
    po(r"/desk/invoice/(\d+)/refund", r_refund_do)

    g(r"/desk/visit/(\d+)", r_visit_edit)
    po(r"/desk/visit/(\d+)/image", r_visit_image)
    po(r"/desk/visit/(\d+)", r_visit_save)
    po(r"/desk/visit/(\d+)/item", r_visit_item)

    g(r"/desk/materials", r_materials)
    po(r"/desk/materials", r_materials_do)

    g(r"/desk/leaves", lambda h, s: h.send(200, p_leaves(s)))
    g(r"/desk/leaves/new", r_leave_new)
    po(r"/desk/leaves/new", r_leave_new)
    po(r"/desk/leaves/(\d+)/(ok|no)", r_leave_act)
    g(r"/desk/shifts", lambda h, s: h.send(200, p_shifts(s)))
    po(r"/desk/shifts/(\d+)/(ok|no)", r_shift_act)
    g(r"/desk/complaints", lambda h, s: h.send(200, p_complaints(s)))
    g(r"/desk/complaints/new", r_complaint_new)
    g(r"/desk/complaints/(\d+)/done", r_complaint_form)
    po(r"/desk/complaints/new", r_complaint_new)
    po(r"/desk/complaints/(\d+)/done", r_complaint_done)
    g(r"/desk/performance", lambda h, s: h.send(200, p_perf(s)))

    g(r"/desk/clinics", lambda h, s: h.send(200, p_clinics(s)))
    g(r"/desk/requisitions", lambda h, s: h.send(200, p_requisitions(s)))
    po(r"/desk/requisitions/(\d+)/(ok|no)", r_requisition_act)
    g(r"/desk/quality", lambda h, s: h.send(200, p_quality(s)))
    # /desk/accounts 交给 biz2（带重置口令 / 停用启用），这里不再注册只读版
    g(r"/desk/audit", lambda h, s: h.send(200, p_audit(s)))
    g(r"/desk/invoices", r_invoices)
    g(r"/desk/reports", lambda h, s: h.send(200, p_reports(s)))

def _todo(title, rows, empty="今天没有待办"):
    """待办队列：一行一件事 + 一个按钮。rows = [(hot?, 主文, 副文, 按钮HTML)]"""
    if not rows:
        return ('<div class="todo"><div class="hd">%s</div>'
                '<div class="empty none">%s</div></div>') % (esc(title), esc(empty))
    body = "".join(
        '<div class="it%s"><div class="t"><b>%s</b><span>%s</span></div>%s</div>'
        % (" hot" if hot == "hot" else (" warm" if hot == "warm" else ""), t1, t2, bt)
        for hot, t1, t2, bt in rows)
    return ('<div class="todo"><div class="hd">%s<span class="n">%d</span>'
            '</div>%s</div>') % (esc(title), len(rows), body)


def _meter(pct, cls=""):
    p = max(0.0, min(100.0, float(pct or 0)))
    return ('<div class="meter"><i class="%s" style="width:%.1f%%"></i></div>'
            % (cls, p))


def frontdesk_home(c, sess, t):
    """前台首页：现在谁该到、谁没到、谁还没开单。"""
    cid = staff_clinic(sess)
    if not cid:
        return '<div class="empty deny">这个账号还没绑定门店，看不到队列。</div>'
    now = datetime.now()
    hm = now.strftime("%H:%M")
    # 未来 60 分钟要到的人（含已过时间还没到诊的）
    soon = c.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name pname,"
        " p.phone, dn.name dname"
        " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
        " WHERE r.clinic_id=? AND date(a.appointment_datetime)=?"
        "   AND IFNULL(a.is_void,0)=0 AND a.status='已预约'"
        "   AND time(a.appointment_datetime)<=time(?,'+60 minutes')"
        " ORDER BY a.appointment_datetime LIMIT 8", (cid, t, hm)).fetchall()
    rows = []
    for r in soon:
        mins = int((datetime.strptime(r["appointment_datetime"][:16], "%Y-%m-%d %H:%M")
                    - now.replace(second=0, microsecond=0)).total_seconds() // 60)
        if mins < 0:
            tag, hot = "已过号 %d 分钟" % (-mins), "hot"
        elif mins <= 15:
            tag, hot = "%d 分钟后到" % mins, "hot"
        else:
            tag, hot = "%d 分钟后到" % mins, ""
        rows.append((hot, "%s · %s" % (hhmm(r["appointment_datetime"]), r["pname"]),
                     "%s · %s · %s" % (r["dname"], r["phone"] or "无电话", tag),
                     post_btn("登记到诊", "/desk/checkin/%d" % r["appointment_id"],
                              cls="btn sm")))
    out = _todo("现在该到（未来 60 分钟）", rows, "未来一小时没有预约要到")

    # 已到诊但还没开结算单
    nopay = c.execute(
        "SELECT a.appointment_id, a.appointment_datetime, p.name pname,"
        " v.visit_id, IFNULL(SUM(l.line_subtotal),0) amt"
        " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id AND IFNULL(i.is_void,0)=0"
        " LEFT JOIN INVOICE_LINE l ON l.invoice_id=i.invoice_id"
        " WHERE r.clinic_id=? AND date(a.appointment_datetime)=? AND a.status='已到诊'"
        " GROUP BY v.visit_id HAVING i.invoice_id IS NULL"
        " ORDER BY a.appointment_datetime LIMIT 8", (cid, t)).fetchall()
    rows = [(("warm" if r["amt"] else ""),
             "%s · %s" % (hhmm(r["appointment_datetime"]), r["pname"]),
             "已到诊，还没开结算单",
             post_btn("开结算单", "/desk/invoice/%d/create" % r["visit_id"], cls="btn sm"))
            for r in nopay]
    out += _todo("已到诊未开单", rows, "今天的都开完了")

    # 今日时间轴（按时间排，状态点着色）
    day = c.execute(
        "SELECT a.appointment_datetime, a.status, p.name pname, dn.name dname,"
        " v.visit_id, i.invoice_id"
        " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
        " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id AND IFNULL(i.is_void,0)=0"
        " WHERE r.clinic_id=? AND date(a.appointment_datetime)=? AND IFNULL(a.is_void,0)=0"
        " ORDER BY a.appointment_datetime", (cid, t)).fetchall()
    body = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (esc(hhmm(r["appointment_datetime"])), esc(r["pname"]), esc(r["dname"]),
           S.badge(r["status"]),
           (btn("写病历", "/desk/visit/%d" % r["visit_id"]) if r["visit_id"]
            else (btn("开结算单", "/desk/invoice/%d/create" % r["visit_id"])
                  if r["status"] == "已到诊" and r["visit_id"] and not r["invoice_id"]
                  else '<span class="muted">—</span>')))
        for r in day)
    timeline = ('<div class="panel"><h3><span>今日时间轴</span><span>%d 个号</span></h3>'
                '<div class="bd">%s</div></div>') % (
        len(day),
        ('<table class="tbl dense"><thead><tr><th>时间</th><th>患者</th><th>牙医</th>'
         '<th>状态</th><th>操作</th></tr></thead><tbody>%s</tbody></table>' % body)
        if day else '<div class="empty">今天还没有预约</div>')

    quick = ('<div class="panel"><h3><span>常用</span></h3><div class="bd">'
             '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">'
             '<a class="btn" href="/desk/book" style="padding:16px 8px;text-align:center">代客预约</a>'
             '<a class="btn" href="/desk/walkin" style="padding:16px 8px;text-align:center">散客挂号</a>'
             '<a class="btn" href="/desk/patients" style="padding:16px 8px;text-align:center">患者检索</a>'
             '<a class="btn" href="/desk/recalls" style="padding:16px 8px;text-align:center">复诊回访</a>'
             '</div></div></div>')
    return out + '<div class="two"><div>%s</div><div>%s</div></div>' % (timeline, quick)


def doctor_home(c, sess, t):
    """牙医首页：下一个是谁、哪个病历还没写。"""
    did = sess.get("dentist_id")
    if not did:
        return '<div class="empty deny">这个账号还没绑定牙医档案，看不到今天的患者。</div>'
    rows = c.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name pname,"
        " v.visit_id, IFNULL(v.chief_complaint,'') cc, IFNULL(v.diagnosis,'') dg"
        " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
        " WHERE r.dentist_id=? AND date(a.appointment_datetime)=?"
        "   AND IFNULL(a.is_void,0)=0"
        " ORDER BY a.appointment_datetime", (did, t)).fetchall()
    now = datetime.now()
    # 当前诊位：已到诊但主诉还空着的那位
    cur = None
    for r in rows:
        if r["status"] == "已到诊" and not (r["cc"] or "").strip():
            cur = r
            break
    if cur:
        focus = ('<div class="todo"><div class="hd">当前诊位<span class="n">待写病历</span></div>'
                 '<div class="it hot"><div class="t"><b>%s · %s</b>'
                 '<span>%s 已到诊，病历还没写</span></div>%s</div></div>') % (
            hhmm(cur["appointment_datetime"]), esc(cur["pname"]),
            esc(hhmm(cur["appointment_datetime"])),
            btn("写病历", "/desk/visit/%d" % cur["visit_id"], cls="btn"))
    else:
        nxt = None
        for r in rows:
            if r["status"] == "已预约":
                nxt = r
                break
        if nxt:
            focus = ('<div class="todo"><div class="hd">下一个患者</div>'
                     '<div class="it"><div class="t"><b>%s · %s</b>'
                     '<span>%s 预约，还没到诊</span></div>%s</div></div>') % (
                hhmm(nxt["appointment_datetime"]), esc(nxt["pname"]),
                esc(hhmm(nxt["appointment_datetime"])),
                '<span class="muted">等患者到诊</span>')
        else:
            focus = '<div class="todo"><div class="hd">今天的诊次</div><div class="empty none">今天的号都看完了</div></div>'

    body = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (esc(hhmm(r["appointment_datetime"])), esc(r["pname"]), S.badge(r["status"]),
           (btn("写病历", "/desk/visit/%d" % r["visit_id"])
            if r["visit_id"] else '<span class="muted">—</span>'))
        for r in rows)
    timeline = ('<div class="panel"><h3><span>今日患者</span><span>%d 位</span></h3>'
                '<div class="bd">%s</div></div>') % (
        len(rows),
        ('<table class="tbl dense"><thead><tr><th>时间</th><th>患者</th>'
         '<th>状态</th><th>操作</th></tr></thead><tbody>%s</tbody></table>' % body)
        if rows else '<div class="empty">今天没有排班</div>')

    # VISIT 没有 dentist_id（列名事故第 11 次）：牙医挂在 ROSTER 上，
    # 路径是 VISIT.appointment_id → APPOINTMENT.roster_id → ROSTER.dentist_id。
    plans = c.execute(
        "SELECT p.plan_id, p.plan_no, p.created_date, p.plan_description"
        " FROM TREATMENT_PLAN p"
        " JOIN VISIT v ON p.visit_id=v.visit_id"
        " JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " WHERE r.dentist_id=? ORDER BY p.created_date DESC LIMIT 5", (did,)).fetchall()
    pr = "".join('<div class="it"><div class="t"><b>%s</b><span>%s</span></div></div>'
                 % (esc(r["plan_no"]), esc((r["plan_description"] or "")[:40]))
                 for r in plans)
    side = ('<div class="panel"><h3><span>在管治疗计划</span></h3><div class="bd">'
            '<div class="todo" style="border:0;margin:0">%s</div></div></div>') % (
        pr or '<div class="empty">还没有治疗计划</div>')
    return focus + '<div class="two"><div>%s</div><div>%s</div></div>' % (timeline, side)


def desk_extra(sess):
    """给各角色工作台补上真正要看的清单——只有四个数字不算工作台。"""
    d = sess.get("desk")
    t = today()
    c = con()
    out = ""
    if d == "frontdesk":
        out += frontdesk_home(c, sess, t)
    elif d == "doctor":
        out += doctor_home(c, sess, t)
    elif d == "manager":
        cid = staff_clinic(sess)
        if cid:
            rows = c.execute(
                "SELECT a.appointment_datetime, p.name pname, dn.name dname, a.status, v.visit_id"
                " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
                " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
                " LEFT JOIN DENTIST dn ON r.dentist_id=dn.dentist_id"
                " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
                " WHERE r.clinic_id=? AND date(a.appointment_datetime)=?"
                " ORDER BY a.appointment_datetime LIMIT 12", (cid, t)).fetchall()
            out += panel("本店今日预约",
                         table(["时间", "患者", "牙医", "状态"],
                               [[esc(hhmm(r["appointment_datetime"])), esc(r["pname"]),
                                 esc(r["dname"]), S.badge(r["status"])] for r in rows]),
                         right=btn("全部", "/desk/appointments"))
            lv = c.execute(
                "SELECT l.*, dn.name dname FROM DENTIST_LEAVE l"
                " LEFT JOIN DENTIST dn ON l.dentist_id=dn.dentist_id"
                " WHERE l.approval_status='待审批' AND l.clinic_id=?"
                " ORDER BY l.leave_id DESC LIMIT 8", (cid,)).fetchall()
            out += panel("待审批请假",
                         table(["牙医", "类型", "起", "止", "事由", ""],
                               [[esc(r["dname"]), esc(r["leave_type"]),
                                 esc((r["leave_start"] or "")[:16]), esc((r["leave_end"] or "")[:16]),
                                 esc(r["leave_reason"]),
                                 post_btn("批准", "/desk/leaves/%d/ok" % r["leave_id"])] for r in lv])
                         if lv else '<p class="muted">暂无待审批请假。</p>',
                         right=btn("全部", "/desk/leaves"))
            cp = c.execute(
                "SELECT * FROM COMPLAINT WHERE status='待处理' AND clinic_id=?"
                " ORDER BY complaint_id DESC LIMIT 8", (cid,)).fetchall()
            out += panel("待处理投诉",
                         table(["渠道", "内容", "时间", ""],
                               [[esc(r["channel"]), esc(r["content"]),
                                 esc((r["filed_date"] or "")[:16]),
                                 post_btn("已处理", "/desk/complaints/%d/done" % r["complaint_id"])]
                                for r in cp]) if cp else '<p class="muted">暂无待处理投诉。</p>',
                         right=btn("全部", "/desk/complaints"))
    elif d == "hq":
        rows = c.execute(
            "SELECT cc.clinic_id, cc.clinic_name,"
            " (SELECT COUNT(*) FROM ROSTER r WHERE r.clinic_id=cc.clinic_id AND r.roster_date=?) nd,"
            " (SELECT COUNT(*) FROM APPOINTMENT a JOIN ROSTER r2 ON a.roster_id=r2.roster_id"
            "   WHERE r2.clinic_id=cc.clinic_id AND date(a.appointment_datetime)=?) na,"
            " (SELECT IFNULL(SUM(pay.amount),0) FROM PAYMENT pay"
            "   JOIN INVOICE i ON pay.invoice_id=i.invoice_id"
            "   JOIN VISIT v ON i.visit_id=v.visit_id"
            "   WHERE v.clinic_id=cc.clinic_id AND date(pay.paid_datetime)>=?) np"
            " FROM CLINIC cc ORDER BY cc.clinic_id",
            (t, t, (date.today() - timedelta(days=30)).isoformat())).fetchall()
        out += panel("各店近况",
                     table(["门店", "今日排班", "今日预约", "近 30 天收款"],
                           [[esc(r["clinic_name"]), num(r["nd"]), num(r["na"]), money(r["np"])]
                            for r in rows]))
        rq = c.execute(
            "SELECT q.*, f.clinic_name fname, tt.clinic_name tname, dn.name dname"
            " FROM SHIFT_REQUISITION q"
            " LEFT JOIN CLINIC f ON q.from_clinic_id=f.clinic_id"
            " LEFT JOIN CLINIC tt ON q.to_clinic_id=tt.clinic_id"
            " LEFT JOIN DENTIST dn ON q.dentist_id=dn.dentist_id"
            " WHERE q.requisition_status='待审批' ORDER BY q.requisition_id DESC LIMIT 8").fetchall()
        out += panel("待审批跨店征调",
                     table(["调入门店", "牙医", "日期", "原因", ""],
                           [[esc(r["tname"]), esc(r["dname"]), esc(r["requisition_date"]),
                             esc(r["requisition_reason"]),
                             post_btn("批准", "/desk/requisitions/%d/ok" % r["requisition_id"])]
                            for r in rq]) if rq else '<p class="muted">暂无待审批征调。</p>',
                     right=btn("全部", "/desk/requisitions"))
        qi = c.execute(
            "SELECT * FROM QUALITY_INCIDENT WHERE status IN ('待处理','处理中')"
            " ORDER BY incident_id DESC LIMIT 6").fetchall()
        out += panel("未闭环质量事件",
                     table(["类型", "描述", "严重度", "状态"],
                           [[esc(r["incident_type"]), esc(r["description"]),
                             esc(r["severity"]), S.badge(r["status"])] for r in qi])
                     if qi else '<p class="muted">质量事件已全部闭环。</p>',
                     right=btn("全部", "/desk/quality"))
    elif d == "finance":
        rows = c.execute(
            "SELECT i.invoice_no, p.name pname, cc.clinic_name,"
            " (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l WHERE l.invoice_id=i.invoice_id) due,"
            " (SELECT IFNULL(SUM(amount),0) FROM PAYMENT y WHERE y.invoice_id=i.invoice_id) paid"
            " FROM INVOICE i LEFT JOIN VISIT v ON i.visit_id=v.visit_id"
            " LEFT JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
            " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
            " LEFT JOIN CLINIC cc ON v.clinic_id=cc.clinic_id"
            " WHERE i.status<>'已收款' ORDER BY i.invoice_id DESC LIMIT 10").fetchall()
        out += panel("未结清结算单",
                     table(["单号", "患者", "门店", "应收", "已收", "欠款"],
                           [[esc(r["invoice_no"]), esc(r["pname"] or "—"),
                             esc(r["clinic_name"] or "—"), money(r["due"]), money(r["paid"]),
                             money(float(r["due"] or 0) - float(r["paid"] or 0))] for r in rows])
                     if rows else '<p class="muted">所有结算单均已结清。</p>',
                     right=btn("全部", "/desk/invoices"))
        day = c.execute(
            "SELECT method, COUNT(*) n, IFNULL(SUM(amount),0) s FROM PAYMENT"
            " WHERE date(paid_datetime)=date('now','localtime') GROUP BY method").fetchall()
        out += panel("今日收款方式分布",
                     table(["方式", "笔数", "金额"],
                           [[esc(r["method"]), num(r["n"]), money(r["s"])] for r in day])
                     if day else '<p class="muted">今天还没有收款。</p>')
    elif d == "assistant":
        rows = c.execute(
            "SELECT mi.*, m.material_name, m.unit FROM MATERIAL_ISSUE mi"
            " LEFT JOIN MATERIAL_BATCH b ON mi.batch_id=b.batch_id"
            " LEFT JOIN MATERIAL m ON b.material_id=m.material_id"
            " ORDER BY mi.issue_id DESC LIMIT 10").fetchall()
        out += panel("最近领用",
                     table(["单号", "物料", "数量", "时间"],
                           [[esc(r["issue_no"]), esc(r["material_name"]),
                             "%s %s" % (num(r["quantity"]), esc(r["unit"] or "")),
                             esc((r["issued_datetime"] or "")[:16])] for r in rows])
                     if rows else '<p class="muted">还没有领用记录。</p>',
                     right=btn("去领用", "/desk/materials"))
        low = c.execute(
            "SELECT m.material_name, m.unit, m.reorder_point, SUM(s.on_hand_qty) qty"
            " FROM STOCK_LEDGER s JOIN MATERIAL m ON s.material_id=m.material_id"
            " WHERE s.is_void=0 GROUP BY m.material_id" " HAVING qty <= CAST(m.reorder_point AS REAL)"
            " ORDER BY qty LIMIT 10").fetchall()
        out += panel("低于补货点的物料",
                     table(["物料", "现有", "补货点"],
                           [[esc(r["material_name"]),
                             "%s %s" % (num(r["qty"]), esc(r["unit"] or "")),
                             num(r["reorder_point"])] for r in low])
                     if low else '<p class="muted">各物料库存都在补货点之上。</p>')
    c.close()
    return out

# ---------------------------------------------------------------- 代客预约
# 前台每天要接一堆电话：“我明天上午想找陆医生”。患者端那套流程是给本人
# 登录用的，前台这里要能替任意患者建，所以单独一组页面，但确认与成功页
# 复用同一套（编号规则、余位校验都一致，不另造一套）。

def p_desk_book(sess, q="", err=""):
    q = (q or "").strip()
    c = con()
    if q:
        rows = c.execute(
            "SELECT * FROM PATIENT WHERE name LIKE ? OR phone LIKE ?"
            " ORDER BY patient_id DESC LIMIT 40",
            ("%" + q + "%", "%" + q + "%")).fetchall()
    else:
        rows = c.execute("SELECT * FROM PATIENT ORDER BY patient_id DESC"
                         " LIMIT 20").fetchall()
    c.close()
    tr = []
    for r in rows:
        tr.append([esc(r["name"]), esc(r["patient_no"]),
                   esc(r["phone"] or "—"), esc(r["first_visit_date"] or "—"),
                   '<a class="btn sm" href="/desk/book/%d">给 TA 约</a>'
                   % r["patient_id"]])
    form = ('<form class="f" method="get" action="/desk/book" style="margin-bottom:14px">'
            '<input name="q" value="%s" placeholder="姓名或手机号" style="min-width:240px">'
            '<button class="btn sm">搜索</button>'
            '<a class="btn ghost sm" href="/desk/walkin">新患者当场建档</a></form>' % esc(q))
    body = (S.flash_err(err) + panel("代客预约 · 先找患者",
            form + table(["姓名", "病案号", "手机", "初诊日期", ""], tr,
                         "没有匹配的患者")))
    return S.page("代客预约", body, sess, "/desk/book")


def p_desk_book_pick(sess, pid, day=None, err=""):
    cid = staff_clinic(sess) or 1
    day = day or today()
    c = con()
    p = c.execute("SELECT * FROM PATIENT WHERE patient_id=?", (pid,)).fetchone()
    if not p:
        c.close()
        return None
    cl = c.execute("SELECT * FROM CLINIC WHERE clinic_id=?", (cid,)).fetchone()
    days = [(date.today() + timedelta(days=i)).isoformat() for i in range(10)]
    rows = c.execute(
        "SELECT r.*, d.name AS dn,"
        " r.slot_capacity - (SELECT COUNT(*) FROM APPOINTMENT x"
        "   WHERE x.roster_id=r.roster_id AND IFNULL(x.is_void,0)=0"
        "   AND x.status IN ('已预约','已到诊')) AS left_n"
        " FROM ROSTER r LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE r.clinic_id=? AND r.roster_date=? AND IFNULL(r.is_reserved,0)=0"
        " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))"
        " ORDER BY r.slot_start", (cid, day, _T, _T, _HM)).fetchall()
    c.close()

    chips = "".join('<a class="chip %s" href="/desk/book/%d?d=%s">%s</a>'
                    % ("on" if x == day else "", pid, x, x[5:]) for x in days)
    tr = []
    for r in rows:
        left = int(r["left_n"] or 0)
        if left <= 0:
            continue
        tr.append(['%s — %s' % (esc(r["slot_start"]), esc(r["slot_end"])),
                   esc(r["dn"]), '剩 %d 位' % left,
                   '<form method="post" action="/desk/book/do" style="margin:0">'
                   '<input type="hidden" name="patient_id" value="%d">'
                   '<input type="hidden" name="roster_id" value="%d">'
                   '<input type="hidden" name="date" value="%s">'
                   '<button class="btn sm">登记这条</button></form>'
                   % (pid, r["roster_id"], day)])
    head = ('<p style="margin:0 0 4px"><b>%s</b>　%s　%s</p>'
            '<p class="muted" style="margin:0 0 14px">%s · %s</p>'
            % (esc(p["name"]), esc(p["phone"] or "无电话"),
               esc(p["patient_no"]), esc(cl["clinic_name"] if cl else ""),
               esc(cl["postal_address"] if cl else "")))
    body = (S.flash_err(err) + panel("代客预约 · 选时间",
            head + '<div class="chips" style="margin-bottom:14px">%s</div>' % chips +
            table(["时段", "牙医", "余位", ""], tr, "这天本店已无余位"),
            right=btn("换一个患者", "/desk/book", "btn ghost sm")))
    return S.page("代客预约", body, sess, "/desk/book")


def r_desk_book_list(h, sess):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    q = (qs.get("q") or [""])[0]
    err = (qs.get("err") or [""])[0]
    return h.send(200, p_desk_book(sess, q, err))


def r_desk_book_pick(h, sess, pid):
    if not sess:
        return h.redirect("/login")
    qs = S.parse_qs((h.path.split("?", 1) + [""])[1])
    d = (qs.get("d") or [""])[0] or None
    p = p_desk_book_pick(sess, int(pid), d)
    if p is None:
        return h.redirect("/desk/book")
    return h.send(200, p)


def r_desk_book_do(h, sess):
    if not sess:
        return h.redirect("/login")
    f = h.form()
    pid = int(f.get("patient_id") or 0)
    rid = int(f.get("roster_id") or 0)
    if not pid or not rid:
        return h.redirect("/desk/book")
    c = con()
    try:
        r = c.execute("SELECT * FROM ROSTER WHERE roster_id=?", (rid,)).fetchone()
        if not r:
            return h.redirect("/desk/book/%d?err=排班不存在" % pid)
        if not same_clinic(sess, cid=r["clinic_id"]):
            return deny(h, "/desk/book/%d" % pid)
        # 「数容量」和「写预约」必须是一个动作：先 COUNT 再 INSERT 的话，
        # 八个窗口同时点能进六个（容量 1 的时段也一样）。
        try:
            c.commit()
            c.execute("BEGIN IMMEDIATE")
        except Exception:  # noqa: BLE001
            c.rollback()
            return h.redirect("/desk/book/%d?err=系统正忙，请稍后重试" % pid)
        used = c.execute(
            "SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=?"
            " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')",
            (rid,)).fetchone()[0]
        if used >= int(r["slot_capacity"] or 0):
            c.rollback()
            return h.redirect("/desk/book/%d?err=这个时段刚被约满" % pid)
        day8 = (r["roster_date"] or "").replace("-", "")
        base = c.execute("SELECT IFNULL(MAX(CAST(SUBSTR(appointment_no,10) AS INTEGER)),0)"
                         " FROM APPOINTMENT WHERE appointment_no LIKE ?",
                         ("A%s%%" % day8,)).fetchone()[0]
        no = "A%s%04d" % (day8, int(base) + 1)
        while c.execute("SELECT 1 FROM APPOINTMENT WHERE appointment_no=?",
                        (no,)).fetchone():
            base += 1
            no = "A%s%04d" % (day8, int(base) + 1)
        c.execute("INSERT INTO APPOINTMENT (appointment_no, patient_id, roster_id,"
                  " appointment_datetime, status, visit_reason) VALUES (?,?,?,?,?,?)",
                  (no, pid, rid, "%s %s:00" % (r["roster_date"], r["slot_start"]),
                   "已预约", "前台代客预约"))
        aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        audit(sess, "APPOINTMENT", aid, "status", "", "已预约", patient_id=pid, con=c)
        c.commit()
    except Exception as e:  # noqa: BLE001
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        return h.redirect("/desk/book/%d?err=预约失败：%s"
                          % (pid, str(e).split(":")[-1].strip()[:40]))
    finally:
        c.close()
    return h.redirect("/me/book/done/%d" % aid)

