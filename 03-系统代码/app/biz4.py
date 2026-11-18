# -*- coding: utf-8 -*-
"""采购到付款全链路 + 库存总览。

这条链在文档里是完整的（采购单→入库→对账→应付→付款），但代码里一直是断的：
`PURCHASE_ORDER` 有 8 条种子，界面上一个入口都没有，`ACCOUNT_PAYABLE` 的 4 条
是凭空造的，跟采购单对不上。这里把它接通：

    采购单（下单）→ 入库单（收货，生成批次 + 加库存 + 出库流水）
                 → 对账单（按供应商汇总本期入库金额）
                 → 应付账款（对账确认后挂牌子）
                 → 付款记录（付一笔，应付状态自己走）

约定与 biz / biz2 一致：`S` 由 server 注入，页头页脚和菜单都复用 server 的。
"""
import datetime
import math
import sqlite3

S = None
BIZ = None


def _db():
    return BIZ.con()


def _q(sess, key, default=""):
    from urllib.parse import parse_qs, urlparse
    p = (sess or {}).get("_path") or ""
    d = parse_qs(urlparse(p).query)
    v = d.get(key)
    return v[0] if v else default


# ---------------------------------------------------------------- 小部件

def _table(head, rows, empty="没有数据"):
    if not rows:
        return '<div class="empty">%s</div>' % BIZ.esc(empty)
    th = "".join("<th>%s</th>" % h for h in head)
    tr = []
    for r in rows:
        tr.append("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r))
    return ('<div class="tw"><table class="tbl"><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>' % (th, "".join(tr)))


def _tag(txt, cls="g"):
    return '<span class="tag %s">%s</span>' % (cls, BIZ.esc(str(txt)))


def _kv(rows):
    return "".join('<div class="kvr"><span>%s</span><b>%s</b></div>' % (k, v) for k, v in rows)


# ---------------------------------------------------------------- 采购单

def p_po(sess):
    if not sess:
        return None
    c = _db()
    rows = c.execute(
        "SELECT po.po_id, po.po_no, po.order_date, po.expected_date, po.status,"
        " s.supplier_name, IFNULL(t.payment_days,0) pd,"
        " (SELECT COUNT(*) FROM PURCHASE_ORDER_LINE WHERE po_id=po.po_id) nl,"
        " (SELECT IFNULL(SUM(quantity*unit_price),0) FROM PURCHASE_ORDER_LINE"
        "  WHERE po_id=po.po_id) amt"
        " FROM PURCHASE_ORDER po"
        " LEFT JOIN SUPPLIER s ON po.supplier_id=s.supplier_id"
        " LEFT JOIN SETTLEMENT_TERM t ON po.term_id=t.term_id"
        " WHERE IFNULL(po.is_void,0)=0 ORDER BY po.po_id DESC").fetchall()
    c.close()
    body = '<div class="pg-h"><h1>采购单</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("新建采购单", "/desk/po/new", "btn")
    rows2 = []
    for r in rows:
        rows2.append([
            BIZ.esc(r["po_no"]), BIZ.esc(r["supplier_name"] or "—"),
            BIZ.esc(r["order_date"] or "—"), BIZ.esc(r["expected_date"] or "—"),
            "%d 项" % r["nl"], BIZ.money(r["amt"]),
            _tag(r["status"] or "—", "g" if r["status"] == "已入库" else "y"),
            '<a class="btn sm" href="/desk/po/%d">查看</a>' % r["po_id"],
        ])
    body += _table(["采购单号", "供应商", "下单日", "预计到货", "项数",
                    "金额", "状态", "操作"], rows2, "还没有采购单")
    return S.page("采购单", body, sess, "/desk/po")


def p_po_new(sess, err=""):
    if not sess:
        return None
    c = _db()
    sup = c.execute("SELECT supplier_id, supplier_name FROM SUPPLIER"
                    " WHERE IFNULL(is_void,0)=0 ORDER BY supplier_id").fetchall() \
        if _has_void(c, "SUPPLIER") else \
        c.execute("SELECT supplier_id, supplier_name FROM SUPPLIER ORDER BY supplier_id").fetchall()
    terms = c.execute("SELECT term_id, term_code, payment_days FROM SETTLEMENT_TERM"
                      " ORDER BY term_id").fetchall()
    mats = c.execute("SELECT material_id, material_code, material_name, unit"
                     " FROM MATERIAL ORDER BY material_id").fetchall()
    clis = c.execute("SELECT clinic_id, clinic_name FROM CLINIC"
                     " ORDER BY clinic_id").fetchall()
    mycid = BIZ.staff_clinic(sess)
    c.close()
    body = '<div class="pg-h"><h1>新建采购单</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("返回", "/desk/po", "btn ghost")
    if err:
        body += '<div class="alert err">%s</div>' % BIZ.esc(err)
    body += BIZ.panel("下单信息",
                    '<form method="post" action="/desk/po/new" style="display:grid;gap:14px;max-width:620px">'
                    '<div><label>采购门店</label><select name="clinic_id">%s</select></div>'
                    '<div><label>供应商</label><select name="supplier_id">%s</select></div>'
                    '<div><label>结算条款</label><select name="term_id">%s</select></div>'
                    '<div><label>预计到货</label><input name="expected_date" value="%s" '
                    'style="width:180px"></div>'
                    '<div><label>物料（一行一个，格式：物料编号 数量 单价，用空格隔开）</label>'
                    '<textarea name="lines" rows="6" placeholder="M001 20 12.5&#10;M002 5 480">%s</textarea></div>'
                    '<div><button class="btn">保存</button></div></form>'
                    % ("".join('<option value="%d"%s>%s</option>'
                               % (r["clinic_id"],
                                  " selected" if r["clinic_id"] == mycid else "",
                                  BIZ.esc(r["clinic_name"])) for r in clis),
                       "".join('<option value="%d">%s</option>' % (r["supplier_id"], BIZ.esc(r["supplier_name"]))
                               for r in sup),
                       "".join('<option value="%d">%s（账期 %d 天）</option>'
                               % (r["term_id"], BIZ.esc(r["term_code"]), r["payment_days"]) for r in terms),
                       (datetime.date.today() + datetime.timedelta(days=7)).isoformat(),
                       "&#10;".join("%s 10 %s" % (r["material_code"], 10) for r in mats[:2])))
    return S.page("新建采购单", body, sess, "/desk/po")


def _has_void(c, table):
    return any(r[1] == "is_void" for r in c.execute("PRAGMA table_info(%s)" % table))


def r_po_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("hq", "manager", "admin"):
        return BIZ.deny(h, "/desk/po", msg="采购要总部或店长来建")
    f = h.form()
    try:
        sid = int(f.get("supplier_id") or 0)
        tid = int(f.get("term_id") or 0) or None
    except ValueError:
        return BIZ.deny(h, "/desk/po/new", msg="供应商或条款不合法")
    if not sid:
        return BIZ.deny(h, "/desk/po/new", msg="请选供应商")
    # 采购单必须记清是给哪家店买的：收货入库要往这家的账套里加库存
    try:
        cid = int(f.get("clinic_id") or 0)
    except ValueError:
        cid = 0
    if not cid:
        return BIZ.deny(h, "/desk/po/new", msg="请选采购门店")
    exp = (f.get("expected_date") or "").strip()
    lines = []
    for raw in (f.get("lines") or "").splitlines():
        parts = raw.split()
        if len(parts) != 3:
            continue
        code, qty, price = parts
        try:
            lines.append((code, int(float(qty)), float(price)))
        except ValueError:
            return BIZ.deny(h, "/desk/po/new", msg="这一行看不懂：%s" % raw)
    if not lines:
        return BIZ.deny(h, "/desk/po/new", msg="至少填一行物料：物料编号 数量 单价")
    c = _db()
    no = BIZ.next_no(c, "PURCHASE_ORDER", "PO", 50000)
    c.execute("INSERT INTO PURCHASE_ORDER(po_no, clinic_id, supplier_id, term_id,"
              " order_date, expected_date, status) VALUES(?,?,?,?,?,?,?)",
              (no, cid, sid, tid, datetime.date.today().isoformat(), exp or None, "已下达"))
    pid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    n = 0
    for code, qty, price in lines:
        m = c.execute("SELECT material_id FROM MATERIAL WHERE material_code=?",
                      (code,)).fetchone()
        if not m:
            c.rollback()
            c.close()
            return BIZ.deny(h, "/desk/po/new", msg="没有这个物料编号：%s" % code)
        if qty <= 0 or price < 0:
            c.rollback()
            c.close()
            return BIZ.deny(h, "/desk/po/new", msg="数量和单价要为正数")
        n += 1
        c.execute("INSERT INTO PURCHASE_ORDER_LINE(po_id, line_no, material_id,"
                  " quantity, unit_price) VALUES(?,?,?,?,?)",
                  (pid, n, m["material_id"], qty, price))
    BIZ.audit(sess, "PURCHASE_ORDER", pid, "po_no", "", no, con=c)
    c.commit()
    c.close()
    return h.redirect("/desk/po/%d?ok=%s" % (pid, S.quote("采购单 %s 已保存" % no)))


def p_po_one(sess, po_id, flash=""):
    if not sess:
        return None
    c = _db()
    po = c.execute("SELECT po.*, s.supplier_name, IFNULL(t.payment_days,0) pd"
                   " FROM PURCHASE_ORDER po"
                   " LEFT JOIN SUPPLIER s ON po.supplier_id=s.supplier_id"
                   " LEFT JOIN SETTLEMENT_TERM t ON po.term_id=t.term_id"
                   " WHERE po.po_id=?", (po_id,)).fetchone()
    if not po:
        c.close()
        return None
    lines = c.execute(
        "SELECT l.*, m.material_code, m.material_name, m.unit FROM PURCHASE_ORDER_LINE l"
        " JOIN MATERIAL m ON l.material_id=m.material_id"
        " WHERE l.po_id=? ORDER BY l.line_no", (po_id,)).fetchall()
    got = c.execute("SELECT IFNULL(SUM(quantity),0) FROM RECEIPT_LINE rl"
                    " JOIN RECEIPT_NOTE rn ON rl.receipt_id=rn.receipt_id"
                    " WHERE rn.po_id=? AND IFNULL(rn.is_void,0)=0", (po_id,)).fetchone()[0]
    c.close()
    body = '<div class="pg-h"><h1>采购单 %s</h1><div class="pg-a">%s</div></div>' % (
        BIZ.esc(po["po_no"]),
        BIZ.btn("返回列表", "/desk/po", "btn ghost"))
    if flash:
        body += '<div class="alert ok">%s</div>' % BIZ.esc(flash)
    amt = sum((l["quantity"] or 0) * (l["unit_price"] or 0) for l in lines)
    body += BIZ.panel("概况", _kv([
        ("供应商", BIZ.esc(po["supplier_name"] or "—")),
        ("账期", "%d 天" % po["pd"]),
        ("下单 / 预计到货", "%s / %s" % (BIZ.esc(po["order_date"] or "—"),
                                        BIZ.esc(po["expected_date"] or "—"))),
        ("状态", _tag(po["status"] or "—")),
        ("合计金额", BIZ.money(amt) + " 元"),
        ("已收货数量", "%s" % got),
    ]))
    rows = []
    for l in lines:
        rows.append([BIZ.esc(l["material_code"]), BIZ.esc(l["material_name"]),
                     "%s %s" % (l["quantity"], BIZ.esc(l["unit"] or "")),
                     BIZ.money(l["unit_price"]),
                     BIZ.money((l["quantity"] or 0) * (l["unit_price"] or 0))])
    body += BIZ.panel("明细", _table(["编号", "物料", "数量", "单价", "金额"], rows))
    if po["status"] != "已入库":
        body += BIZ.panel(
            "收货入库",
            "<p>收货会建一张入库单、按行生成批次、把数量加进库存，并写一条入库流水。"
            "数量可以少于采购量（分批到货）。</p>",
            right=BIZ.post_btn("按采购量全部收货", "/desk/po/%d/receive" % po_id, "btn",
                             confirm="按采购量全额入库，继续？"))
    return S.page("采购单", body, sess, "/desk/po")


def r_po_one(h, sess, po_id):
    if not sess:
        return h.redirect("/login")
    p = p_po_one(sess, int(po_id), _q(sess, "ok"))
    if p is None:
        return h.redirect("/desk/po")
    return h.send(200, p)


def r_po_receive(h, sess, po_id):
    """按采购量全额收货：入库单 + 批次 + 库存 + 流水，一个事务。"""
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("hq", "manager", "admin"):
        return BIZ.deny(h, "/desk/po", msg="收货要总部或店长来操作")
    po_id = int(po_id)
    c = _db()
    po = c.execute("SELECT * FROM PURCHASE_ORDER WHERE po_id=?", (po_id,)).fetchone()
    if not po:
        c.close()
        return h.redirect("/desk/po")
    if po["status"] == "已入库":
        c.close()
        return BIZ.deny(h, "/desk/po/%d" % po_id, msg="这张采购单已经全额入库了")
    # 入库门店取采购单上写的那家；老单没有 clinic_id 才退回下单人门店
    clinic = po["clinic_id"] or BIZ.staff_clinic(sess) or 1
    lines = c.execute("SELECT * FROM PURCHASE_ORDER_LINE WHERE po_id=?", (po_id,)).fetchall()
    if not lines:
        c.close()
        return BIZ.deny(h, "/desk/po/%d" % po_id, msg="这张采购单没有明细")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        # 先抢状态：WHERE 排除已入库，并发时只有第一条能改到，
        # 后到的那条 rowcount=0，立刻回滚，不会重复入库。
        cur = c.execute("UPDATE PURCHASE_ORDER SET status='已入库'"
                        " WHERE po_id=? AND IFNULL(status,'')<>'已入库'", (po_id,))
        if cur.rowcount != 1:
            c.rollback()
            c.close()
            return BIZ.deny(h, "/desk/po/%d" % po_id,
                            msg="这张采购单刚刚已经被收过货了，请刷新页面")
        no = BIZ.next_no(c, "RECEIPT_NOTE", "RC", 60000)
        c.execute("INSERT INTO RECEIPT_NOTE(receipt_no, po_id, clinic_id, received_date,"
                  " status) VALUES(?,?,?,?,?)",
                  (no, po_id, clinic, datetime.date.today().isoformat(), "已入库"))
        rid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        n = 0
        for l in lines:
            n += 1
            # 批次号：物料编号-收货单号，保证唯一且能从批次反查到这批货
            batch_no = "%s-%s" % (l["material_id"], no)
            exp = (datetime.date.today() + datetime.timedelta(days=730)).isoformat()
            c.execute("INSERT INTO MATERIAL_BATCH(material_id, batch_serial_no,"
                      " expiry_date, purchase_unit_price, received_qty, issued_qty)"
                      " VALUES(?,?,?,?,?,0)",
                      (l["material_id"], batch_no, exp, l["unit_price"], l["quantity"]))
            bid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("INSERT INTO RECEIPT_LINE(receipt_id, line_no, material_id,"
                      " batch_id, quantity) VALUES(?,?,?,?,?)",
                      (rid, n, l["material_id"], bid, l["quantity"]))
            led = c.execute("SELECT ledger_id FROM STOCK_LEDGER WHERE clinic_id=?"
                            " AND material_id=? AND IFNULL(is_void,0)=0",
                            (clinic, l["material_id"])).fetchone()
            if led:
                c.execute("UPDATE STOCK_LEDGER SET on_hand_qty=IFNULL(on_hand_qty,0)+?"
                          " WHERE ledger_id=?", (l["quantity"], led["ledger_id"]))
                lid = led["ledger_id"]
            else:
                c.execute("INSERT INTO STOCK_LEDGER(clinic_id, material_id, on_hand_qty)"
                          " VALUES(?,?,?)", (clinic, l["material_id"], l["quantity"]))
                lid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            c.execute("INSERT INTO STOCK_MOVEMENT(ledger_id, movement_type, direction,"
                      " quantity, source_type, source_no, moved_datetime)"
                      " VALUES(?,?,?,?,?,?,?)",
                      (lid, "采购入库", "入库", l["quantity"], "RECEIPT_NOTE", no, now))
        BIZ.audit(sess, "PURCHASE_ORDER", po_id, "status", po["status"], "已入库", con=c)
        c.commit()
    except Exception as e:
        c.rollback()
        c.close()
        return BIZ.deny(h, "/desk/po/%d" % po_id, msg="入库失败：%s" % e)
    c.close()
    return h.redirect("/desk/po/%d?ok=%s" % (po_id, S.quote("已入库，入库单 %s" % no)))


# ---------------------------------------------------------------- 对账与应付

def p_statements(sess):
    if not sess:
        return None
    c = _db()
    rows = c.execute(
        "SELECT st.*, s.supplier_name,"
        " (SELECT IFNULL(SUM(amount),0) FROM STATEMENT_LINE WHERE statement_id=st.statement_id) amt"
        " FROM STATEMENT st LEFT JOIN SUPPLIER s ON st.supplier_id=s.supplier_id"
        " WHERE IFNULL(st.is_void,0)=0 ORDER BY st.statement_id DESC").fetchall()
    c.close()
    body = '<div class="pg-h"><h1>供应商对账</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("发起对账", "/desk/statements/new", "btn")
    body += BIZ.panel("怎么用",
                    "<p>选一个供应商和一段期间，系统把这段期间**已入库**的采购收货按物料汇总成金额，"
                    "生成对账单；确认无误后点「挂应付」，这笔钱才进入应付账款。</p>")
    r2 = []
    for r in rows:
        r2.append([BIZ.esc(r["statement_no"]), BIZ.esc(r["supplier_name"] or "—"),
                   "%s ~ %s" % (BIZ.esc(r["period_start"] or "—"),
                                BIZ.esc(r["period_end"] or "—")),
                   BIZ.money(r["amt"]), _tag(r["status"] or "—",
                                           "g" if r["status"] == "已挂应付" else "y"),
                   '<a class="btn sm" href="/desk/statements/%d">查看</a>' % r["statement_id"]])
    body += _table(["对账单号", "供应商", "期间", "金额", "状态", "操作"], r2)
    return S.page("供应商对账", body, sess, "/desk/statements")


def p_statement_new(sess, err=""):
    if not sess:
        return None
    c = _db()
    sups = c.execute("SELECT supplier_id, supplier_name FROM SUPPLIER ORDER BY supplier_id").fetchall()
    c.close()
    t0 = datetime.date.today()
    body = '<div class="pg-h"><h1>发起对账</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("返回", "/desk/statements", "btn ghost")
    if err:
        body += '<div class="alert err">%s</div>' % BIZ.esc(err)
    body += BIZ.panel("对账期间",
                    '<form method="post" action="/desk/statements/new" style="display:grid;gap:14px;max-width:560px">'
                    '<div><label>供应商</label><select name="supplier_id">%s</select></div>'
                    '<div><label>开始</label><input name="d0" value="%s" style="width:180px"></div>'
                    '<div><label>结束</label><input name="d1" value="%s" style="width:180px"></div>'
                    '<div><button class="btn">生成对账单</button></div></form>'
                    % ("".join('<option value="%d">%s</option>'
                               % (r["supplier_id"], BIZ.esc(r["supplier_name"])) for r in sups),
                       (t0 - datetime.timedelta(days=30)).isoformat(), t0.isoformat()))
    return S.page("发起对账", body, sess, "/desk/statements")


def r_statement_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("finance", "hq", "admin"):
        return BIZ.deny(h, "/desk/statements", msg="对账要财务或总部来发起")
    f = h.form()
    try:
        sid = int(f.get("supplier_id") or 0)
    except ValueError:
        sid = 0
    d0 = (f.get("d0") or "").strip()
    d1 = (f.get("d1") or "").strip()
    if not sid or not d0 or not d1:
        return BIZ.deny(h, "/desk/statements/new", msg="供应商和起止日期都要填")
    if d0 > d1:
        return BIZ.deny(h, "/desk/statements/new", msg="开始日期不能晚于结束")
    c = _db()
    # 同供应商同期间只允许一张对账单。没这道检查时，脚本每跑一次就多一张单、
    # 多挂一条应付——生产库里就这样堆出了 23 张重复单、225 万虚增应付。
    old = c.execute("SELECT statement_id FROM STATEMENT"
                    " WHERE supplier_id=? AND period_start=? AND period_end=?"
                    " AND IFNULL(is_void,0)=0", (sid, d0, d1)).fetchone()
    if old:
        c.close()
        return h.redirect("/desk/statements/%d?err=这个供应商在这段时间已经对过账了，"
                          "直接看那张单" % int(old["statement_id"]))
    rows = c.execute(
        "SELECT m.material_id, m.material_name, SUM(rl.quantity) q,"
        "       IFNULL(SUM(rl.quantity * IFNULL(b.purchase_unit_price,0)),0) amt"
        " FROM RECEIPT_LINE rl"
        " JOIN RECEIPT_NOTE rn ON rl.receipt_id=rn.receipt_id"
        " JOIN PURCHASE_ORDER po ON rn.po_id=po.po_id"
        " JOIN MATERIAL m ON rl.material_id=m.material_id"
        " LEFT JOIN MATERIAL_BATCH b ON rl.batch_id=b.batch_id"
        " WHERE IFNULL(rn.is_void,0)=0 AND IFNULL(po.is_void,0)=0 AND po.supplier_id=?"
        "   AND rn.received_date>=? AND rn.received_date<=?"
        " GROUP BY m.material_id ORDER BY m.material_id", (sid, d0, d1)).fetchall()
    if not rows:
        c.close()
        return BIZ.deny(h, "/desk/statements/new",
                        msg="这个供应商在 %s 至 %s 之间没有入库记录" % (d0, d1))
    no = BIZ.next_no(c, "STATEMENT", "ST", 40000)
    c.execute("INSERT INTO STATEMENT(statement_no, supplier_id, period_start, period_end,"
              " status) VALUES(?,?,?,?,?)", (no, sid, d0, d1, "待确认"))
    stid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for n, r in enumerate(rows, 1):
        c.execute("INSERT INTO STATEMENT_LINE(statement_id, line_no, source_type,"
                  " source_no, amount) VALUES(?,?,?,?,?)",
                  (stid, n, "入库", r["material_name"], round(r["amt"], 2)))
    c.commit()
    c.close()
    return h.redirect("/desk/statements/%d?ok=%s" % (stid, S.quote("对账单 %s 已生成" % no)))


def p_statement_one(sess, stid, flash=""):
    if not sess:
        return None
    c = _db()
    st = c.execute("SELECT st.*, s.supplier_name FROM STATEMENT st"
                   " LEFT JOIN SUPPLIER s ON st.supplier_id=s.supplier_id"
                   " WHERE st.statement_id=?", (stid,)).fetchone()
    if not st:
        c.close()
        return None
    lines = c.execute("SELECT * FROM STATEMENT_LINE WHERE statement_id=?"
                      " ORDER BY line_no", (stid,)).fetchall()
    pay = c.execute("SELECT * FROM ACCOUNT_PAYABLE WHERE statement_id=?", (stid,)).fetchone()
    c.close()
    body = '<div class="pg-h"><h1>对账单 %s</h1><div class="pg-a">%s</div></div>' % (
        BIZ.esc(st["statement_no"]),
        BIZ.btn("返回", "/desk/statements", "btn ghost"))
    if flash:
        body += '<div class="alert ok">%s</div>' % BIZ.esc(flash)
    amt = sum(l["amount"] or 0 for l in lines)
    body += BIZ.panel("概况", _kv([
        ("供应商", BIZ.esc(st["supplier_name"] or "—")),
        ("期间", "%s ~ %s" % (BIZ.esc(st["period_start"] or "—"),
                             BIZ.esc(st["period_end"] or "—"))),
        ("合计", BIZ.money(amt) + " 元"),
        ("状态", _tag(st["status"] or "—")),
    ]))
    rows = [[BIZ.esc(l["source_type"] or ""), BIZ.esc(l["source_no"] or ""),
             BIZ.money(l["amount"])] for l in lines]
    body += BIZ.panel("明细", _table(["来源", "物料", "金额"], rows))
    if not pay:
        body += BIZ.panel("确认无误后挂账",
                        "<p>挂账后这笔钱会进应付账款，付款时按应付单走。</p>",
                        right=BIZ.post_btn("挂应付", "/desk/statements/%d/payable" % stid,
                                         "btn", confirm="确认对账单金额无误？"))
    else:
        body += BIZ.panel("已经挂账",
                        _kv([("应付单号", BIZ.esc(pay["payable_no"])),
                             ("金额", BIZ.money(pay["payable_amount"]) + " 元"),
                             ("状态", _tag(pay["status"] or "—"))]),
                        right=BIZ.btn("去付款", "/desk/payables", "btn"))
    return S.page("对账单", body, sess, "/desk/statements")


def r_statement_one(h, sess, stid):
    if not sess:
        return h.redirect("/login")
    p = p_statement_one(sess, int(stid), _q(sess, "ok"))
    if p is None:
        return h.redirect("/desk/statements")
    return h.send(200, p)


def r_statement_payable(h, sess, stid):
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("finance", "hq", "admin"):
        return BIZ.deny(h, "/desk/statements", msg="挂账要财务来做")
    stid = int(stid)
    c = _db()
    st = c.execute("SELECT * FROM STATEMENT WHERE statement_id=?", (stid,)).fetchone()
    if not st:
        c.close()
        return h.redirect("/desk/statements")
    if c.execute("SELECT 1 FROM ACCOUNT_PAYABLE WHERE statement_id=?", (stid,)).fetchone():
        c.close()
        return BIZ.deny(h, "/desk/statements/%d" % stid, msg="这张对账单已经挂过账了")
    amt = c.execute("SELECT IFNULL(SUM(amount),0) FROM STATEMENT_LINE"
                    " WHERE statement_id=?", (stid,)).fetchone()[0]
    no = BIZ.next_no(c, "ACCOUNT_PAYABLE", "AP", 30000)
    c.execute("INSERT INTO ACCOUNT_PAYABLE(supplier_id, po_id, statement_id, payable_no,"
              " payable_amount, status) VALUES(?,?,?,?,?,?)",
              (st["supplier_id"], None, stid, no, amt, "未付款"))
    c.execute("UPDATE STATEMENT SET status='已挂应付' WHERE statement_id=?", (stid,))
    BIZ.audit(sess, "STATEMENT", stid, "status", st["status"], "已挂应付", con=c)
    c.commit()
    c.close()
    return h.redirect("/desk/statements/%d?ok=%s" % (stid, S.quote("已挂应付 %s" % no)))


# ---------------------------------------------------------------- 应付与付款

def r_po_void(h, sess, po_id):
    """作废采购单。已收货的不能作废——货已进库，批次和库存流水都产生了。"""
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("hq", "manager", "admin"):
        return BIZ.deny(h, "/desk/po", msg="作废采购单要总部或店长")
    c = _db()
    po = c.execute("SELECT * FROM PURCHASE_ORDER WHERE po_id=?", (int(po_id),)).fetchone()
    if not po:
        c.close()
        return h.redirect("/desk/po?err=采购单不存在")
    if (po["status"] or "") == "已入库":
        c.close()
        return h.redirect("/desk/po?err=这张采购单已经收货入库，不能作废；"
                                 "要冲回来请在库存里做一笔盘点或调拨")
    if int(po["is_void"] or 0) == 1:
        c.close()
        return h.redirect("/desk/po?err=这张采购单已经作废了")
    c.execute("UPDATE PURCHASE_ORDER SET is_void=1, status='已作废' WHERE po_id=?",
              (int(po_id),))
    c.commit()
    BIZ.audit(sess, "PURCHASE_ORDER", int(po_id), "status", po["status"], "已作废", con=c)
    c.close()
    return h.redirect("/desk/po?ok=采购单 %s 已作废" % (po["po_no"] or ""))


def r_payable_void(h, sess, apid):
    """作废应付账单。已经付过款的不能作废，要先冲正。"""
    if not sess:
        return h.redirect("/login")
    if sess.get("role") not in ("finance", "ops", "supervisor"):
        return BIZ.deny(h, "/desk/payables", msg="作废应付要财务或店长")
    c = _db()
    ap = c.execute("SELECT * FROM ACCOUNT_PAYABLE WHERE payable_id=?", (int(apid),)).fetchone()
    if not ap:
        c.close()
        return h.redirect("/desk/payables?err=应付单不存在")
    if int(ap["is_void"] or 0) == 1:
        c.close()
        return h.redirect("/desk/payables?err=这张应付单已经作废了")
    paid = c.execute(
        "SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD WHERE payable_id=?"
        " AND IFNULL(is_void,0)=0", (int(apid),)).fetchone()[0]
    if (paid or 0) > 0.01:
        c.close()
        return h.redirect("/desk/payables?err=这张应付单已付 %s 元，要先作废付款记录才能作废"
                                 % BIZ.money(paid))
    c.execute("UPDATE ACCOUNT_PAYABLE SET is_void=1, status='已作废', void_reason=?"
              " WHERE payable_id=?", ("总部撤销应付", int(apid)))
    c.commit()
    BIZ.audit(sess, "ACCOUNT_PAYABLE", int(apid), "status", ap["status"], "已作废", con=c)
    c.close()
    return h.redirect("/desk/payables?ok=应付单 %s 已作废" % (ap["payable_no"] or ""))


def p_payables(sess, flash=""):
    if not sess:
        return None
    c = _db()
    rows = c.execute(
        "SELECT ap.*, s.supplier_name,"
        " (SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD"
        "  WHERE payable_id=ap.payable_id AND IFNULL(is_void,0)=0) paid"
        " FROM ACCOUNT_PAYABLE ap LEFT JOIN SUPPLIER s ON ap.supplier_id=s.supplier_id"
        " WHERE IFNULL(ap.is_void,0)=0 ORDER BY ap.payable_id DESC").fetchall()
    c.close()
    body = '<div class="pg-h"><h1>应付账款</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("供应商对账", "/desk/statements", "btn ghost")
    if flash:
        body += '<div class="alert ok">%s</div>' % BIZ.esc(flash)
    r2, tot, unpaid = [], 0.0, 0.0
    for r in rows:
        due = (r["payable_amount"] or 0) - (r["paid"] or 0)
        tot += r["payable_amount"] or 0
        if due > 0.01:
            unpaid += due
        # 状态按金额派生：库里那个 status 是种子数据写死的，不可信
        if due <= 0.01:
            st_cn, st_cls = "已付清", "g"
        elif (r["paid"] or 0) > 0.01:
            st_cn, st_cls = "部分付款", "y"
        else:
            st_cn, st_cls = "未付款", "r"
        ops = BIZ.btn("付款", "/desk/payables/%d/pay" % r["payable_id"], "btn sm") \
            if due > 0.01 else "—"
        if due > 0.01:
            ops += " " + BIZ.post_btn("作废", "/desk/payables/%d/void" % r["payable_id"],
                                      "btn ghost sm", confirm="作废后这笔应付不再计入欠款，确定？")
        r2.append([BIZ.esc(r["payable_no"]), BIZ.esc(r["supplier_name"] or "—"),
                   BIZ.money(r["payable_amount"]), BIZ.money(r["paid"]), BIZ.money(due),
                   _tag(st_cn, st_cls), ops])
    body += BIZ.panel("欠款合计", _kv([("应付总额", BIZ.money(tot) + " 元"),
                                    ("尚未支付", BIZ.money(unpaid) + " 元")]))
    body += _table(["应付单号", "供应商", "金额", "已付", "未付", "状态", "操作"], r2)
    return S.page("应付账款", body, sess, "/desk/payables")


def p_payable_pay(sess, apid, err=""):
    if not sess:
        return None
    c = _db()
    ap = c.execute("SELECT ap.*, s.supplier_name FROM ACCOUNT_PAYABLE ap"
                   " LEFT JOIN SUPPLIER s ON ap.supplier_id=s.supplier_id"
                   " WHERE ap.payable_id=?", (apid,)).fetchone()
    if not ap:
        c.close()
        return None
    paid = c.execute("SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD"
                     " WHERE payable_id=? AND IFNULL(is_void,0)=0", (apid,)).fetchone()[0]
    c.close()
    due = (ap["payable_amount"] or 0) - paid
    body = '<div class="pg-h"><h1>付供应商款</h1><div class="pg-a">%s</div></div>' % \
        BIZ.btn("返回", "/desk/payables", "btn ghost")
    if err:
        body += '<div class="alert err">%s</div>' % BIZ.esc(err)
    body += BIZ.panel("这一笔", _kv([
        ("应付单号", BIZ.esc(ap["payable_no"])),
        ("供应商", BIZ.esc(ap["supplier_name"] or "—")),
        ("应付", BIZ.money(ap["payable_amount"]) + " 元"),
        ("已付", BIZ.money(paid) + " 元"),
        ("未付", BIZ.money(due) + " 元"),
    ]))
    if due <= 0.01:
        body += BIZ.panel("不用再付了", "<p>这笔应付已经结清。</p>")
        return S.page("付款", body, sess, "/desk/payables")
    body += BIZ.panel("付款",
                    '<form method="post" action="/desk/payables/%d/pay" style="display:grid;gap:14px;max-width:520px">'
                    '<div><label>付款金额（未付 %s 元）</label>'
                    '<input name="amount" value="%s" style="width:180px"></div>'
                    '<div><label>付款方式</label><select name="method">'
                    '<option>银行转账</option><option>现金</option><option>承兑汇票</option>'
                    '</select></div>'
                    '<div><button class="btn">确认付款</button></div></form>'
                    % (apid, BIZ.money(due), BIZ.money(due)))
    return S.page("付款", body, sess, "/desk/payables")


def r_payable_pay_form(h, sess, apid):
    if not sess:
        return h.redirect("/login")
    p = p_payable_pay(sess, int(apid))
    if p is None:
        return h.redirect("/desk/payables")
    return h.send(200, p)


def r_payable_pay(h, sess, apid):
    if not sess:
        return h.redirect("/login")
    if sess.get("desk") not in ("finance", "hq", "admin"):
        return BIZ.deny(h, "/desk/payables", msg="付款要财务来做")
    apid = int(apid)
    f = h.form()
    c = _db()
    ap = c.execute("SELECT * FROM ACCOUNT_PAYABLE WHERE payable_id=?", (apid,)).fetchone()
    if not ap:
        c.close()
        return h.redirect("/desk/payables")
    back = "/desk/payables"
    try:
        amt = float(f.get("amount") or 0)
    except ValueError:
        c.close()
        return BIZ.deny(h, back, msg="付款金额要填数字")
    if amt != amt or amt <= 0:
        c.close()
        return BIZ.deny(h, back, msg="付款金额必须大于 0")
    paid = c.execute("SELECT IFNULL(SUM(amount),0) FROM PAYMENT_RECORD"
                     " WHERE payable_id=? AND IFNULL(is_void,0)=0", (apid,)).fetchone()[0]
    due = (ap["payable_amount"] or 0) - paid
    if amt > due + 0.01:
        c.close()
        return BIZ.deny(h, back, msg="付款超过未付金额（未付 %s 元）" % BIZ.money(due))
    method = (f.get("method") or "").strip() or "银行转账"
    no = BIZ.next_no(c, "PAYMENT_RECORD", "PR", 20000)
    c.execute("INSERT INTO PAYMENT_RECORD(payable_id, supplier_id, record_no, amount,"
              " method, paid_date) VALUES(?,?,?,?,?,?)",
              (apid, ap["supplier_id"], no, amt, method,
               datetime.date.today().isoformat()))
    left = due - amt
    c.execute("UPDATE ACCOUNT_PAYABLE SET status=? WHERE payable_id=?",
              ("已付款" if left <= 0.01 else "部分付款", apid))
    BIZ.audit(sess, "ACCOUNT_PAYABLE", apid, "status", ap["status"],
              "已付款" if left <= 0.01 else "部分付款", con=c)
    c.commit()
    c.close()
    return h.redirect("/desk/payables?ok=" + S.quote("已付 %s 元，单号 %s" % (BIZ.money(amt), no)))


# ---------------------------------------------------------------- 库存总览

def p_stock(sess):
    if not sess:
        return None
    c = _db()
    cid = BIZ.staff_clinic(sess)
    where, args = "", ()
    if cid:
        where, args = " AND l.clinic_id=?", (cid,)
    rows = c.execute(
        "SELECT l.ledger_id, l.clinic_id, l.on_hand_qty, m.material_code, m.material_name,"
        " m.unit, m.reorder_point, cl.clinic_name,"
        " (SELECT IFNULL(SUM(quantity),0) FROM STOCK_MOVEMENT sm"
        "  WHERE sm.ledger_id=l.ledger_id) mv"
        " FROM STOCK_LEDGER l JOIN MATERIAL m ON l.material_id=m.material_id"
        " LEFT JOIN CLINIC cl ON l.clinic_id=cl.clinic_id"
        " WHERE IFNULL(l.is_void,0)=0" + where +
        " ORDER BY m.material_code", args).fetchall()
    moves = c.execute(
        "SELECT sm.*, m.material_name, cl.clinic_name FROM STOCK_MOVEMENT sm"
        " JOIN STOCK_LEDGER l ON sm.ledger_id=l.ledger_id"
        " JOIN MATERIAL m ON l.material_id=m.material_id"
        " LEFT JOIN CLINIC cl ON l.clinic_id=cl.clinic_id"
        " ORDER BY sm.movement_id DESC LIMIT 20").fetchall()
    c.close()
    body = '<div class="pg-h"><h1>库存</h1></div>'
    low, total = 0, 0.0
    r2 = []
    for r in rows:
        qty = r["on_hand_qty"] or 0
        total += qty
        try:
            rp = float(r["reorder_point"] or 0)
        except (TypeError, ValueError):
            rp = 0
        warn = rp > 0 and qty <= rp
        if warn:
            low += 1
        r2.append([BIZ.esc(r["clinic_name"] or "—"), BIZ.esc(r["material_code"]),
                   BIZ.esc(r["material_name"]),
                   "%s %s" % (BIZ.num(qty), BIZ.esc(r["unit"] or "")),
                   BIZ.num(rp) if rp else "—",
                   _tag("低于补货点", "r") if warn else _tag("正常", "g"),
                   BIZ.num(r["mv"])])
    body += BIZ.panel("概览", _kv([("账套条数", "%d" % len(rows)),
                                ("低于补货点", "%d 项" % low),
                                ("库存合计数量", BIZ.num(total))]))
    body += BIZ.panel("各门店库存", _table(
        ["门店", "编号", "物料", "现有", "补货点", "状态", "累计变动"], r2))
    m2 = [[BIZ.esc(m["moved_datetime"] or ""), BIZ.esc(m["clinic_name"] or "—"),
           BIZ.esc(m["material_name"]), BIZ.esc(m["movement_type"] or ""),
           BIZ.esc(m["direction"] or ""), BIZ.num(m["quantity"]),
           BIZ.esc(m["source_no"] or "")] for m in moves]
    body += BIZ.panel("最近 20 条出入库流水",
                    _table(["时间", "门店", "物料", "类型", "方向", "数量", "来源单号"], m2))
    return S.page("库存", body, sess, "/desk/stock")


# ---------------------------------------------------------------- 注册

# ---------------------------------------------------------------- 批次与效期

def p_batches(sess, ok=""):
    db = _db()
    rows = db.execute(
        "SELECT b.batch_serial_no, b.expiry_date, b.purchase_unit_price,"
        "       IFNULL(b.received_qty,0) AS rq, IFNULL(b.issued_qty,0) AS iq,"
        "       IFNULL(b.received_qty,0) - IFNULL(b.issued_qty,0) AS left_qty,"
        "       m.material_code, m.material_name, m.unit,"
        "       CAST(julianday(b.expiry_date) - julianday(date('now')) AS INT) AS left_days"
        "  FROM MATERIAL_BATCH b JOIN MATERIAL m ON m.material_id = b.material_id"
        " ORDER BY (b.expiry_date IS NULL), b.expiry_date").fetchall()
    tr = []
    exp = soon = 0
    for r in rows:
        d = r["left_days"]
        if d is None:
            tag = '<span class="badge">未登记效期</span>'
        elif d < 0:
            tag = '<span class="badge r">已过期 %d 天</span>' % (-d)
            exp += 1
        elif d <= 90:
            tag = '<span class="badge y">%d 天后到期</span>' % d
            soon += 1
        else:
            tag = '<span class="badge g">%d 天</span>' % d
        left = float(r["left_qty"] or 0)
        left_cell = ('<b>%s</b>' % BIZ.num(left)) if left > 0 else \
                    '<span style="color:#b91c1c">已领完</span>'
        tr.append([BIZ.esc(r["material_code"]), BIZ.esc(r["material_name"]),
                   BIZ.esc(r["batch_serial_no"]), BIZ.esc(r["expiry_date"] or "—"),
                   BIZ.num(r["rq"]), BIZ.num(r["iq"]), left_cell,
                   BIZ.money(r["purchase_unit_price"]), tag])
    head = ('<div class="row"><div><b>批次与效期</b>'
            '<div class="sub">共 %d 个批次，已过期 %d 个、90 天内到期 %d 个</div></div>'
            '<div>%s</div></div>' % (len(rows), exp, soon,
                                     BIZ.btn("回库存总览", "/desk/stock", "btn ghost")))
    body = BIZ.panel("", head) if False else ""
    body = ('<div class="panel"><div class="h">%s</div><div class="bd">%s'
            '<div class="note">说明：「入库」是这批货进来的总量，「已领」是按批次领走的总量，'
            '两者相减就是这批还剩多少。领用时会校验批次余量，不够就整笔拒绝，'
            '所以不会出现「收 140 领 179」；但库存账套是按门店按物料的，两者维度不同，'
            '对不上要分别看。</div>'
            '</div></div>'
            % ("批次与效期", _table(["物料编码", "物料", "批次号", "效期",
                                     "入库", "已领", "剩余", "进价", "剩余天数"], tr)))
    return S.page("批次与效期", body, sess, "/desk/stock/batches")


# ---------------------------------------------------------------- 盘点

def p_count(sess, err="", ok=""):
    db = _db()
    cl = db.execute("SELECT clinic_id, clinic_name FROM CLINIC ORDER BY clinic_id").fetchall()
    mats = db.execute("SELECT material_id, material_code, material_name, unit"
                      " FROM MATERIAL ORDER BY material_code").fetchall()
    opts = "".join('<option value="%s">%s（%s）</option>'
                   % (c["clinic_id"], BIZ.esc(c["clinic_name"]),
                      BIZ.esc(str(c["clinic_id"]))) for c in cl)
    mopts = "".join('<option value="%s">%s %s</option>'
                    % (m["material_id"], BIZ.esc(m["material_code"]),
                       BIZ.esc(m["material_name"])) for m in mats)
    form = ('<form method="post" action="/desk/stock/count" class="f">'
            '<label class="fl">门店<select name="clinic_id">%s</select></label>'
            '<label class="fl">物料<select name="material_id">%s</select></label>'
            '<label class="fl">实盘数量<input name="qty" value="" placeholder="例如 48"></label>'
            '<button class="btn">记一笔盘点</button></form>'
            '<div class="note">盘点只记差异：系统数量 → 实盘数量，差多少就写一条「盘点」方向的流水，'
            '账套直接改成实盘数。不新建盘点表，这样「账套现值 = 流水净额」仍然成立。</div>'
            % (opts, mopts))
    db2 = _db()
    hist = db2.execute(
        "SELECT m.material_code, m.material_name, s.direction, s.quantity, s.source_no,"
        "       s.moved_datetime, c.clinic_name"
        "  FROM STOCK_MOVEMENT s JOIN STOCK_LEDGER l ON l.ledger_id = s.ledger_id"
        "  JOIN MATERIAL m ON m.material_id = l.material_id"
        "  JOIN CLINIC c ON c.clinic_id = l.clinic_id"
        " WHERE s.source_type = '盘点' ORDER BY s.movement_id DESC LIMIT 30").fetchall()
    tr = [[BIZ.esc(r["clinic_name"]), BIZ.esc(r["material_code"]),
           BIZ.esc(r["material_name"]),
           "多出" if r["direction"] == "入库" else "短缺",
           BIZ.money(abs(r["quantity"] or 0)), BIZ.esc(r["source_no"] or "—"),
           BIZ.esc((r["moved_datetime"] or "")[:16])] for r in hist]
    body = ('<div class="panel"><div class="h">盘点</div><div class="bd">%s%s</div></div>'
            % (form, ""))
    body += ('<div class="panel"><div class="h">盘点记录（最近 30 条）</div>'
             '<div class="bd">%s</div></div>'
             % _table(["门店", "物料编码", "物料", "方向", "数量", "盘点单号", "时间"], tr,
                      "还没有盘点记录"))
    return S.page("盘点", body, sess, "/desk/stock/count")


def r_count(h, sess, *a):
    if sess.get("desk") not in ("manager", "hq", "ops", "admin"):
        return BIZ.deny(h, "/desk/stock")
    f = h.form()
    cid = int(f.get("clinic_id") or 0)
    mid = int(f.get("material_id") or 0)
    # 店长只能盘本店；总部/运营不受限（原来谁都能盘任意店）
    if not BIZ.same_clinic(sess, cid=cid):
        return BIZ.deny(h, "/desk/stock")
    try:
        qty = float(f.get("qty") or "")
    except ValueError:
        return h.redirect("/desk/stock/count?err=实盘数量要填数字")
    if not isinstance(qty, float) or qty != qty or qty in (float("inf"), float("-inf")) \
            or qty > 1000000:
        return h.redirect("/desk/stock/count?err=实盘数量不是一个有效数字")
    if qty < 0:
        return h.redirect("/desk/stock/count?err=实盘数量不能是负数")
    db = _db()
    led = db.execute("SELECT ledger_id, IFNULL(on_hand_qty,0) q FROM STOCK_LEDGER"
                     " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                     (cid, mid)).fetchone()
    if not led:
        db.close()
        return h.redirect("/desk/stock/count?err=这个门店还没有这种物料的账套")
    cur = led["q"]
    diff = qty - cur
    if abs(diff) < 0.0001:
        db.close()
        return h.redirect("/desk/stock/count?ok=数量一致，不用调")
    no = _next_no(db, "COUNT", "PD", 60000)
    try:
        # 账套 += 差额（不赋绝对值），流水记带符号的差额——两者必须同号，
        # 否则「账套 = SUM(流水)」这个不变量会被盘点自己打破。
        # 带上「我看到的旧值」做乐观锁：中间被别人改过就 rowcount=0，
        # 不会出现两个人各写一条差额流水、账套却只加一次的情况。
        row_upd = db.execute(
            "UPDATE STOCK_LEDGER SET on_hand_qty=IFNULL(on_hand_qty,0)+?"
            " WHERE ledger_id=? AND IFNULL(on_hand_qty,0)=?",
            (diff, led["ledger_id"], cur))
        if row_upd.rowcount != 1:
            db.rollback()
            db.close()
            return h.redirect("/desk/stock/count"
                              "?err=这张账套刚被别的操作改过，请刷新后重新盘")
        db.execute("INSERT INTO STOCK_MOVEMENT(ledger_id, movement_type, direction,"
                   " quantity, source_type, source_no, moved_datetime)"
                   " VALUES(?,?,?,?,?,?,datetime('now','localtime'))",
                   (led["ledger_id"], "盘点", "入库" if diff > 0 else "出库",
                    diff, "盘点", no))
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        return h.redirect("/desk/stock/count?err=盘点失败：%s" % BIZ.esc(str(e)[:60]))
    db.close()
    BIZ.audit(sess, "STOCK_LEDGER", led["ledger_id"], "on_hand_qty", cur, qty)
    return h.redirect("/desk/stock/count?ok=%s：%s → %s" % (no, cur, qty))


# ---------------------------------------------------------------- 调拨

def p_transfer(sess, err="", ok=""):
    db = _db()
    cl = db.execute("SELECT clinic_id, clinic_name FROM CLINIC ORDER BY clinic_id").fetchall()
    mats = db.execute("SELECT material_id, material_code, material_name"
                      " FROM MATERIAL ORDER BY material_code").fetchall()
    # 「到」默认选第二家，否则两个下拉都停在第一家，点提交必报「不能同一家」
    def _opts(sel):
        return "".join('<option value="%s"%s>%s</option>'
                       % (c["clinic_id"], " selected" if c["clinic_id"] == sel else "",
                          BIZ.esc(c["clinic_name"])) for c in cl)
    ids = [c["clinic_id"] for c in cl]
    from_opts = _opts(ids[0] if ids else 0)
    to_opts = _opts(ids[1] if len(ids) > 1 else 0)
    mopts = "".join('<option value="%s">%s %s</option>'
                    % (m["material_id"], BIZ.esc(m["material_code"]),
                       BIZ.esc(m["material_name"])) for m in mats)
    form = ('<form method="post" action="/desk/stock/transfer" class="f">'
            '<label class="fl">从<select name="from_id">%s</select></label>'
            '<label class="fl">到<select name="to_id">%s</select></label>'
            '<label class="fl">物料<select name="material_id">%s</select></label>'
            '<label class="fl">数量<input name="qty" placeholder="例如 5"></label>'
            '<button class="btn">确认调拨</button></form>'
            '<div class="note">调拨一次写两条流水（调出店的「出库」、调入店的「入库」），'
            '同一事务，任何一步失败整体回滚；数量不能超过调出店现有库存。</div>'
            % (from_opts, to_opts, mopts))
    hist = db.execute(
        "SELECT s.source_no, s.moved_datetime, m.material_code, m.material_name,"
        "       c.clinic_name, s.direction, s.quantity"
        "  FROM STOCK_MOVEMENT s JOIN STOCK_LEDGER l ON l.ledger_id = s.ledger_id"
        "  JOIN MATERIAL m ON m.material_id = l.material_id"
        "  JOIN CLINIC c ON c.clinic_id = l.clinic_id"
        " WHERE s.source_type = '调拨' ORDER BY s.movement_id DESC LIMIT 30").fetchall()
    tr = [[BIZ.esc(r["source_no"] or "—"), BIZ.esc(r["material_code"]),
           BIZ.esc(r["material_name"]), BIZ.esc(r["clinic_name"]),
           "调入" if r["direction"] == "入库" else "调出",
           BIZ.money(r["quantity"]), BIZ.esc((r["moved_datetime"] or "")[:16])] for r in hist]
    body = '<div class="panel"><div class="h">跨店调拨</div><div class="bd">%s</div></div>' % form
    body += ('<div class="panel"><div class="h">调拨记录（最近 30 条）</div><div class="bd">%s</div></div>'
             % _table(["调拨单号", "物料编码", "物料", "门店", "方向", "数量", "时间"], tr,
                      "还没有调拨记录"))
    return S.page("跨店调拨", body, sess, "/desk/stock/transfer")


def r_transfer(h, sess, *a):
    if sess.get("desk") not in ("manager", "hq", "ops", "admin"):
        return BIZ.deny(h, "/desk/stock")
    f = h.form()
    a = int(f.get("from_id") or 0)
    b = int(f.get("to_id") or 0)
    mid = int(f.get("material_id") or 0)
    try:
        qty = float(f.get("qty") or "")
    except ValueError:
        return h.redirect("/desk/stock/transfer?err=数量要填数字")
    # nan 与任何数比较都是 False，`qty <= 0` 拦不住它；写进库会变成 NULL。
    if not math.isfinite(qty):
        return h.redirect("/desk/stock/transfer?err=数量不是有效数字")
    if qty <= 0:
        return h.redirect("/desk/stock/transfer?err=数量必须大于 0")
    if qty > 1000000:
        return h.redirect("/desk/stock/transfer?err=数量太大了，核对一下")
    if a == b:
        return h.redirect("/desk/stock/transfer?err=调出门店和调入门店不能是同一家")
    # 店长只能从本店调出（调入门店可以是别家，那是业务需要；但存货不能被别店随便拿走）
    if not BIZ.same_clinic(sess, cid=a):
        return BIZ.deny(h, "/desk/stock")
    db = _db()
    src = db.execute("SELECT ledger_id, IFNULL(on_hand_qty,0) q FROM STOCK_LEDGER"
                     " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                     (a, mid)).fetchone()
    dst = db.execute("SELECT ledger_id, IFNULL(on_hand_qty,0) q FROM STOCK_LEDGER"
                     " WHERE clinic_id=? AND material_id=? AND IFNULL(is_void,0)=0",
                     (b, mid)).fetchone()
    if not src:
        db.close()
        return h.redirect("/desk/stock/transfer?err=调出门店没有这种物料的账套")
    if src["q"] < qty:
        db.close()
        return h.redirect("/desk/stock/transfer?err=调出店只有 %s，不够调 %s"
                          % (BIZ.money(src["q"]), BIZ.money(qty)))
    no = _next_no(db, "TRANSFER", "DB", 70000)
    try:
        if not dst:
            db.execute("INSERT INTO STOCK_LEDGER(clinic_id, material_id, on_hand_qty)"
                       " VALUES(?,?,0)", (b, mid))
            dst = db.execute("SELECT ledger_id, IFNULL(on_hand_qty,0) q FROM STOCK_LEDGER"
                             " WHERE clinic_id=? AND material_id=? ORDER BY ledger_id DESC LIMIT 1",
                             (b, mid)).fetchone()
        # 条件更新：先查后改在并发下会双花（两个请求都读到 100、各调 60）。
        # 让 SQLite 的写锁来裁决，只有真正扣成功的那一次 rowcount 才是 1。
        cur = db.execute("UPDATE STOCK_LEDGER SET on_hand_qty = on_hand_qty - ?"
                         " WHERE ledger_id=? AND on_hand_qty >= ?",
                         (qty, src["ledger_id"], qty))
        if cur.rowcount != 1:
            db.rollback()
            db.close()
            return h.redirect("/desk/stock/transfer?err=调出店库存不足，可能刚被别人调走了")
        db.execute("UPDATE STOCK_LEDGER SET on_hand_qty = on_hand_qty + ? WHERE ledger_id=?",
                   (qty, dst["ledger_id"]))
        # 一条调拨在两边各写一条流水：调出记负数、调入记正数（同一单号）。
        for lid, direction, signed in ((src["ledger_id"], "出库", -qty),
                                       (dst["ledger_id"], "入库", qty)):
            db.execute("INSERT INTO STOCK_MOVEMENT(ledger_id, movement_type, direction,"
                       " quantity, source_type, source_no, moved_datetime)"
                       " VALUES(?,?,?,?,?,?,datetime('now','localtime'))",
                       (lid, "调拨", direction, signed, "调拨", no))
        db.commit()
    except Exception as e:
        db.rollback()
        db.close()
        return h.redirect("/desk/stock/transfer?err=调拨失败：%s" % BIZ.esc(str(e)[:60]))
    db.close()
    BIZ.audit(sess, "STOCK_LEDGER", src["ledger_id"], "on_hand_qty",
              src["q"], src["q"] - qty)
    return h.redirect("/desk/stock/transfer?ok=%s：%s %s 已从门店 %s 调到门店 %s"
                      % (no, BIZ.money(qty), "件", BIZ.esc(str(a)), BIZ.esc(str(b))))


def _next_no(db, name, prefix, start):
    """与 biz 里同名的发号器保持一致的做法：先占号再取回。"""
    db.execute("INSERT INTO SEQ(name, val) VALUES(?,?)"
               " ON CONFLICT(name) DO UPDATE SET val = val + 1", (name, start))
    return prefix + "%06d" % db.execute("SELECT val FROM SEQ WHERE name=?",
                                        (name,)).fetchone()[0]


def register(mod, biz_mod):
    global S, BIZ
    S, BIZ = mod, biz_mod
    S.CSS += """
.tw{overflow:auto;max-height:520px;border-radius:8px}
.kvr{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #f1f3f5;font-size:14px}
.kvr span{color:#6b7280}
.kvr b{font-weight:600}
.alert.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46;
  padding:10px 14px;border-radius:8px;margin:0 0 14px}
"""
    S.MENU.setdefault("hq", []).extend([
        ("/desk/po", "采购单", "doc"),
        ("/desk/statements", "供应商对账", "doc"),
        ("/desk/payables", "应付账款", "doc"),
        ("/desk/stock", "库存", "db"),
    ])
    S.MENU.setdefault("finance", []).extend([
        ("/desk/statements", "供应商对账", "doc"),
        ("/desk/payables", "应付账款", "doc"),
    ])
    S.MENU.setdefault("manager", []).extend([
        ("/desk/stock", "库存", "db"),
        ("/desk/po", "采购单", "doc"),
    ])

    def g(p, fn):
        S.ROUTES.append(("GET", __import__("re").compile("^" + p + "$"), fn))

    def po(p, fn):
        S.ROUTES.append(("POST", __import__("re").compile("^" + p + "$"), fn))

    g(r"/desk/po", lambda h, s: h.send(200, p_po(s)))
    g(r"/desk/po/new", lambda h, s: h.send(200, p_po_new(s, _q(s, "err"))))
    po(r"/desk/po/new", r_po_new)
    g(r"/desk/po/(\d+)", r_po_one)
    po(r"/desk/po/(\d+)/receive", r_po_receive)
    g(r"/desk/statements", lambda h, s: h.send(200, p_statements(s)))
    g(r"/desk/statements/new", lambda h, s: h.send(200, p_statement_new(s)))
    po(r"/desk/statements/new", r_statement_new)
    g(r"/desk/statements/(\d+)", r_statement_one)
    po(r"/desk/statements/(\d+)/payable", r_statement_payable)
    g(r"/desk/payables", lambda h, s: h.send(200, p_payables(s, _q(s, "ok"))))
    g(r"/desk/payables/(\d+)/pay", r_payable_pay_form)
    po(r"/desk/payables/(\d+)/pay", r_payable_pay)
    g(r"/desk/stock", lambda h, s: h.send(200, p_stock(s)))

    g(r"/desk/stock/batches", lambda h, s: h.send(200, p_batches(s, _q(s, "ok"))))
    g(r"/desk/stock/count", lambda h, s: h.send(200, p_count(s, _q(s, "err"), _q(s, "ok"))))
    po(r"/desk/stock/count", r_count)
    g(r"/desk/stock/transfer", lambda h, s: h.send(
        200, p_transfer(s, _q(s, "err"), _q(s, "ok"))))
    po(r"/desk/stock/transfer", r_transfer)
    po(r"/desk/po/(\d+)/void", r_po_void)
    po(r"/desk/payables/(\d+)/void", r_payable_void)
