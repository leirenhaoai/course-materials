# -*- coding: utf-8 -*-
"""端到端：把一条真实业务链从预约走到收款，每一步都查库确认。

只测「页面能打开」是不够的——POST 落不落库、状态对不对，必须查表。
"""
import datetime
from datetime import date, timedelta
import http.cookiejar
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = 'http://127.0.0.1:8000'
DB = 'data/adc.db'
ok = []


def check(name, cond, extra=""):
    ok.append((name, bool(cond), extra))
    print("%s %-34s %s" % ("PASS" if cond else "FAIL", name, extra))


def login(name):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(BASE + '/login',
            urllib.parse.urlencode({'login_name': name, 'password': '123456'}).encode()).read()
    return op


def q(sql, args=()):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    r = c.execute(sql, args).fetchall()
    c.close()
    return r


def ex(sql, args=()):
    c = sqlite3.connect(DB)
    c.execute(sql, args)
    c.commit()
    c.close()


# 干净起点：把上一轮造的数据清掉，避免重复跑冲突
ex("DELETE FROM PAYMENT WHERE invoice_id IN"
   " (SELECT invoice_id FROM INVOICE WHERE visit_id IN"
   "   (SELECT visit_id FROM VISIT WHERE visit_no > 90000))")
ex("DELETE FROM INVOICE_LINE WHERE invoice_id IN"
   " (SELECT invoice_id FROM INVOICE WHERE visit_id IN"
   "   (SELECT visit_id FROM VISIT WHERE visit_no > 90000))")
ex("DELETE FROM INVOICE WHERE visit_id IN (SELECT visit_id FROM VISIT WHERE visit_no > 90000)")
ex("DELETE FROM TREATMENT_ITEM WHERE visit_id IN"
   " (SELECT visit_id FROM VISIT WHERE visit_no > 90000)")
ex("DELETE FROM MATERIAL_ISSUE WHERE visit_id IN"
   " (SELECT visit_id FROM VISIT WHERE visit_no > 90000)")
ex("DELETE FROM VISIT WHERE visit_no > 90000")
ex("DELETE FROM DENTIST_LEAVE WHERE leave_reason LIKE 'E2E%'")
ex("DELETE FROM COMPLAINT WHERE content LIKE 'E2E%'")

today = datetime.date.today().isoformat()
day2 = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
pat = login('zhangsan')
recept = login('recept1')
dent = login('dentist1')
assist = login('assist1')
mgr = login('manager1')

# 1. 患者预约（现在要点进确认页提交，列表里的按钮只是链接）
did1 = q("SELECT dentist_id d FROM USER_ACCOUNT WHERE login_name='dentist1'")[0]['d']
# 挑一个「有空位、且这位患者还没约」的排班：页面上列出的第一条不一定是。
# 只用来决定去哪一天，真正下单仍走真实接口。
pid_for_pick = q("SELECT patient_id p FROM PATIENT WHERE account_id="
                 " (SELECT account_id FROM USER_ACCOUNT WHERE login_name='zhangsan')"
                 " ORDER BY patient_id LIMIT 1")[0]["p"]
_pick = q(
    "SELECT r.roster_date d, r.roster_id rid FROM ROSTER r"
    " WHERE r.clinic_id = 1"          # 页面 /me/book/1/<day> 只列城西店
    "   AND r.roster_date >= date('now','+1 day')"
    "   AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
    "   AND (SELECT COUNT(*) FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
    "        AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊'))"
    "       < r.slot_capacity"
    "   AND NOT EXISTS (SELECT 1 FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
    "        AND a.patient_id=%d AND IFNULL(a.is_void,0)=0"
    "        AND a.status IN ('已预约','已到诊'))"
    " ORDER BY r.roster_date, r.slot_start LIMIT 1" % int(pid_for_pick))
if not _pick:
    print("库里没有「有空位且这位患者未约」的排班，测试无法继续")
    sys.exit(1)
day2 = _pick[0]["d"]
said = _pick[0]["rid"]
h = pat.open(BASE + '/me/book/1/' + day2).read().decode('utf-8')
m = re.search(r'/me/book/confirm/(\d+)\?d=', h)
check('预约页出时段', m is not None)
pid_me = q("SELECT patient_id p FROM PATIENT WHERE account_id="
         " (SELECT account_id FROM USER_ACCOUNT WHERE login_name='zhangsan')"
         " ORDER BY patient_id LIMIT 1")[0]["p"]
cands = re.findall(r"/me/book/confirm/(\d+)\?d=", h)
if str(said) in cands:                     # 库里挑中的那条优先
    cands.remove(str(said))
    cands.insert(0, str(said))
if not cands:
    print("列表页没有可约时段，测试无法继续")
    sys.exit(1)
# 同一个号可能早就被 zhangsan 占了（查重会拦住），逐个候选试到成功为止
n0 = q("SELECT COUNT(*) c FROM APPOINTMENT")[0]['c']
n1 = n0
rid = cands[0]
for cand in cands:
    pat.open(BASE + '/me/book/do', urllib.parse.urlencode({
        'roster_id': cand, 'date': day2, 'patient_id': pid_me,
        'phone': '13900002222', 'visit_reason': 'e2e 测试预约'}).encode()).read()
    n1 = q("SELECT COUNT(*) c FROM APPOINTMENT")[0]['c']
    if n1 == n0 + 1:
        rid = cand
        break
check('预约写入库', n1 == n0 + 1, '%d -> %d（试了 %d 个候选）'
      % (n0, n1, len(cands)))
aid = q("SELECT appointment_id a FROM APPOINTMENT ORDER BY appointment_id DESC LIMIT 1")[0]["a"]
row = q("SELECT appointment_no, visit_reason FROM APPOINTMENT WHERE appointment_id=%d" % aid)[0]
check('预约编号已生成', bool(row['appointment_no']), row['appointment_no'])
check('就诊原因已落库', row['visit_reason'] == 'e2e 测试预约', row['visit_reason'])

# 2. 接待员登记到诊
# 清掉上几轮 e2e 留下的「今天到诊」测试预约，否则今天号满、下一轮就没班可测。
x0 = sqlite3.connect(DB)
# visit_id 没有 AUTOINCREMENT，删掉最大那条后再插入会复用同一个 id；
# 所以必须把旧就诊名下的单据、明细、收款一起清掉，否则新就诊会继承「已收款」状态。
x0.execute("DELETE FROM PAYMENT WHERE invoice_id IN (SELECT invoice_id FROM INVOICE"
           "  WHERE visit_id IN (SELECT visit_id FROM VISIT WHERE appointment_id IN"
           "   (SELECT appointment_id FROM APPOINTMENT WHERE appointment_no LIKE 'AE2E%')))")
x0.execute("DELETE FROM INVOICE_LINE WHERE invoice_id IN (SELECT invoice_id FROM INVOICE"
           "  WHERE visit_id IN (SELECT visit_id FROM VISIT WHERE appointment_id IN"
           "   (SELECT appointment_id FROM APPOINTMENT WHERE appointment_no LIKE 'AE2E%')))")
x0.execute("DELETE FROM INVOICE WHERE visit_id IN (SELECT visit_id FROM VISIT"
           "  WHERE appointment_id IN (SELECT appointment_id FROM APPOINTMENT"
           "   WHERE appointment_no LIKE 'AE2E%'))")
x0.execute("DELETE FROM TREATMENT_ITEM WHERE visit_id IN (SELECT visit_id FROM VISIT"
           "  WHERE appointment_id IN (SELECT appointment_id FROM APPOINTMENT"
           "   WHERE appointment_no LIKE 'AE2E%'))")
x0.execute("DELETE FROM VISIT WHERE appointment_id IN"
           " (SELECT appointment_id FROM APPOINTMENT"
           "   WHERE appointment_no LIKE 'AE2E%')")
x0.execute("DELETE FROM APPOINTMENT WHERE appointment_no LIKE 'AE2E%'")
x0.commit()
x0.close()
n0 = q("SELECT COUNT(*) c FROM VISIT")[0]['c']
# 造一条今天的预约（不挪共享排班），模拟患者当天到店
did1 = q("SELECT dentist_id d FROM DENTIST WHERE employee_no="
          " (SELECT staff_no FROM STAFF WHERE staff_id=1)")[0]["d"] \
    if q("SELECT COUNT(*) c FROM DENTIST WHERE employee_no="
         " (SELECT staff_no FROM STAFF WHERE staff_id=1)")[0]["c"] else None
if not did1:
    did1 = q("SELECT dentist_id d FROM DENTIST ORDER BY dentist_id LIMIT 1")[0]["d"]
# 到诊只能由本店前台做（same_clinic），所以这条预约必须挂在门店 1 今天的班上；
# 而病历只有主治牙医能写（own_visit），所以登录的牙医会话要跟着这条班的医生走。
# 优先挑「这位牙医有可用账号」的班：演示数据里只有 dentist1/dentist2 有账号，
# 随便挑一位没账号的医生，会话换不过去，写病历会被 own_visit 正确拒绝。
r_today = q("SELECT r.roster_id i, r.dentist_id d FROM ROSTER r"
            " WHERE r.clinic_id=1 AND r.roster_date=?"
            "  AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
            "  AND EXISTS (SELECT 1 FROM USER_ACCOUNT ua WHERE ua.dentist_id=r.dentist_id"
            "              AND ua.account_status<>'停用')"
            " ORDER BY r.slot_start LIMIT 1", (today,))
if not r_today:
    r_today = q("SELECT r.roster_id i, r.dentist_id d FROM ROSTER r"
                " WHERE r.clinic_id=1 AND r.roster_date=?"
                "  AND IFNULL(r.is_void,0)=0 AND IFNULL(r.is_published,1)=1"
                " ORDER BY r.slot_start LIMIT 1", (today,))
if r_today:
    did1 = r_today[0]["d"]
    # 把 dent 会话换成这位医生的账号，否则写病历会被 own_visit 正确拒绝
    # （USER_ACCOUNT 直接带 dentist_id，不必绕 STAFF 的 staff_no）
    _row = q("SELECT login_name n FROM USER_ACCOUNT"
             " WHERE dentist_id=? AND account_status<>'停用' LIMIT 1", (did1,))
    if _row:
        dent = login(_row[0]["n"])
if not r_today:
    # 该医生当天可能在别的门店/别的时段已有班，直接插 09:00-12:00 会与它重叠。
    # 先试自己补空档；补不出就换一个「今天在门店 1 有空档」的医生。
    x = sqlite3.connect(DB)
    busy = [r[0] for r in x.execute(
        "SELECT slot_start || '-' || slot_end FROM ROSTER"
        " WHERE dentist_id=? AND roster_date=? AND IFNULL(is_void,0)=0",
        (did1, today)).fetchall()]
    slot = None
    for s0, s1 in (("09:00", "12:00"), ("13:30", "18:00")):
        if not any(b.split("-")[0] < s1 and b.split("-")[1] > s0 for b in busy):
            slot = (s0, s1)
            break
    if slot is None:
        # 换医生：找一个今天在两个时段都不忙的
        cands = [r[0] for r in x.execute(
            "SELECT DISTINCT dentist_id FROM DENTIST ORDER BY dentist_id").fetchall()]
        for d in cands:
            bz = [r[0] for r in x.execute(
                "SELECT slot_start || '-' || slot_end FROM ROSTER"
                " WHERE dentist_id=? AND roster_date=? AND IFNULL(is_void,0)=0",
                (d, today)).fetchall()]
            for s0, s1 in (("09:00", "12:00"), ("13:30", "18:00")):
                if not any(z.split("-")[0] < s1 and z.split("-")[1] > s0 for z in bz):
                    did1, slot = d, (s0, s1)
                    break
            if slot:
                break
    if slot is None:
        x.close()
        raise SystemExit("今天找不到任何医生空档，先跑 tools/_fix_overlap3.py")
    s0, s1 = slot
    x.execute("INSERT INTO ROSTER(clinic_id, dentist_id, roster_date, slot_start,"
              " slot_end, slot_capacity, roster_status, is_published)"
              " VALUES(1,?,?,?,?,6,'正常',1)", (did1, today, s0, s1))
    x.commit()
    rid_new = x.execute("SELECT last_insert_rowid()").fetchone()[0]
    x.close()
    r_today = [{"i": rid_new}]
    print("  (今天没有可用排班，已为医生 %s 补一条 %s %s-%s)"
          % (did1, today, s0, s1))
x = sqlite3.connect(DB)
x.execute("INSERT INTO APPOINTMENT(appointment_no, patient_id, roster_id,"
          " appointment_datetime, status, visit_reason) VALUES(?,?,?,?,?,?)",
          ("AE2E%s%03d" % (today.replace("-", ""), aid % 1000),
           pid_me, r_today[0]["i"], today + " 09:00:00", "已预约", "e2e 到诊"))
x.commit()
aid = x.execute("SELECT last_insert_rowid()").fetchone()[0]
x.close()
recept.open(BASE + '/desk/checkin/%d' % aid, b'').read()
n1 = q("SELECT COUNT(*) c FROM VISIT")[0]['c']
st = q("SELECT status s FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]['s']
check('到诊建就诊记录', n1 == n0 + 1, '%d -> %d' % (n0, n1))
check('预约状态转已到诊', st == '已到诊', st)
vid = q("SELECT visit_id v FROM VISIT WHERE appointment_id=?", (aid,))[0]['v']

# 3. 牙医写病历
dent.open(BASE + '/desk/visit/%d' % vid,
          urllib.parse.urlencode({'chief_complaint': 'E2E 牙痛',
                                  'present_history': 'E2E 三天',
                                  'examination': 'E2E 见龋洞',
                                  'diagnosis': 'E2E 深龋',
                                  'treatment_note': 'E2E 已充填'}).encode()).read()
dx = q("SELECT diagnosis d, treated t FROM VISIT WHERE visit_id=?", (vid,))[0]
check('病历落库', dx['d'] == 'E2E 深龋', dx['d'])
check('就诊标记已完成', dx['t'] == 1, str(dx['t']))

# 4. 牙医加治疗项目
cid = q("SELECT catalog_id c FROM TREATMENT_CATALOG ORDER BY catalog_id LIMIT 1")[0]['c']
price = q("SELECT standard_unit_price p FROM TREATMENT_CATALOG WHERE catalog_id=?", (cid,))[0]['p']
n0 = q("SELECT COUNT(*) c FROM TREATMENT_ITEM WHERE visit_id=?", (vid,))[0]['c']
dent.open(BASE + '/desk/visit/%d/item' % vid,
          urllib.parse.urlencode({'catalog_id': cid, 'tooth_fdi': '16',
                                  'units': '2', 'price': ''}).encode()).read()
n1 = q("SELECT COUNT(*) c FROM TREATMENT_ITEM WHERE visit_id=?", (vid,))[0]['c']
check('治疗项目落库', n1 == n0 + 1, '%d -> %d' % (n0, n1))

# 5. 接待员开结算单
recept.open(BASE + '/desk/invoice/%d/create' % vid, b'').read()
inv = q("SELECT i.*, (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l"
        " WHERE l.invoice_id=i.invoice_id) due FROM INVOICE i WHERE i.visit_id=?", (vid,))
check('结算单已生成', len(inv) == 1 and inv[0]['due'] > 0,
      '%s 应收 %s' % (inv[0]['invoice_no'], inv[0]['due']) if inv else '无')

# 6. 收款
due = inv[0]['due']
recept.open(BASE + '/desk/invoice/%d/pay' % vid,
            urllib.parse.urlencode({'amount': '%.2f' % due, 'method': '微信'}).encode()).read()
pay = q("SELECT IFNULL(SUM(amount),0) s FROM PAYMENT WHERE invoice_id=?", (inv[0]['invoice_id'],))[0]['s']
st = q("SELECT status s FROM INVOICE WHERE invoice_id=?", (inv[0]['invoice_id'],))[0]['s']
check('收款落库', abs(pay - due) < 0.01, '%s / %s' % (pay, due))
check('结算单转已收款', st == '已收款', st)

# 7. 患者看就诊详情
h = pat.open(BASE + '/me/visit/%d' % vid).read().decode('utf-8')
check('患者可看自己病历', 'E2E 深龋' in h and 'E2E 已充填' in h)

# 8. 助手领用耗材
# 必须挑一个「该门店账套里还有货」的批次：前几轮测试可能已经领空了某些物料。
# 两个条件都要满足：批次本身有余量（否则批次校验拦），账套里也有货（否则库存校验拦）。
b = q("SELECT b.batch_id id, b.material_id m FROM MATERIAL_BATCH b"
      " JOIN STOCK_LEDGER s ON s.material_id=b.material_id"
      " WHERE s.clinic_id=1 AND IFNULL(s.on_hand_qty,0)>=10"
      "   AND IFNULL(b.received_qty,0)-IFNULL(b.issued_qty,0)>=10"
      "   AND (b.expiry_date IS NULL OR b.expiry_date >= date('now'))"
      " LIMIT 1")
if not b:
    # 现造一条批次（入库 50），同时把账套补到 50，否则领用会被库存校验拦住
    q("INSERT INTO MATERIAL_BATCH(material_id, batch_serial_no, expiry_date,"
      " purchase_unit_price, received_qty, issued_qty)"
      " SELECT material_id, 'E2E-BATCH-' || DATE('now'), DATE('now','+2 year'),"
      "        10.0, 50, 0 FROM MATERIAL LIMIT 1")
    b = q("SELECT batch_id id, material_id m FROM MATERIAL_BATCH"
          " ORDER BY batch_id DESC LIMIT 1")
    if b:
        _mid = b[0]['m']
        _cur = q("SELECT IFNULL(on_hand_qty,0) q, ledger_id lid FROM STOCK_LEDGER"
                 " WHERE clinic_id=1 AND material_id=?", (_mid,))
        if not _cur:
            q("INSERT INTO STOCK_LEDGER(clinic_id, material_id, on_hand_qty)"
              " VALUES(1,?,50)", (_mid,))
        elif _cur[0]['q'] < 50:
            q("UPDATE STOCK_LEDGER SET on_hand_qty=50 WHERE ledger_id=?", (_cur[0]['lid'],))
        q("INSERT INTO STOCK_MOVEMENT(ledger_id, movement_type, direction, quantity,"
          " source_type, source_no, moved_datetime)"
          " SELECT ledger_id,'入库','入库',50,'测试','E2E-TOPUP',datetime('now')"
          " FROM STOCK_LEDGER WHERE clinic_id=1 AND material_id=?", (_mid,))
if b:
    bid, mid = b[0]['id'], b[0]['m']
    before = q("SELECT IFNULL(SUM(on_hand_qty),0) q FROM STOCK_LEDGER WHERE material_id=?",
               (mid,))[0]['q']
    n0 = q("SELECT COUNT(*) c FROM MATERIAL_ISSUE")[0]['c']
    assist.open(BASE + '/desk/materials',
                urllib.parse.urlencode({'batch_id': bid, 'quantity': '5'}).encode()).read()
    n1 = q("SELECT COUNT(*) c FROM MATERIAL_ISSUE")[0]['c']
    after = q("SELECT IFNULL(SUM(on_hand_qty),0) q FROM STOCK_LEDGER WHERE material_id=?",
              (mid,))[0]['q']
    check('领用落库', n1 == n0 + 1, '%d -> %d' % (n0, n1))
    check('库存扣减', abs(after - (before - 5)) < 0.01, '%s -> %s' % (before, after))
else:
    check('领用落库', False, '无库存记录')

# 9. 店长请假审批
did = q("SELECT dentist_id d FROM DENTIST LIMIT 1")[0]['d']
mgr.open(BASE + '/desk/leaves/new',
         urllib.parse.urlencode({'dentist_id': did, 'leave_type': '事假',
                                 'leave_start': tomorrow, 'leave_end': tomorrow,
                                 'leave_reason': 'E2E 测试请假'}).encode()).read()
lv = q("SELECT leave_id i, approval_status s FROM DENTIST_LEAVE WHERE leave_reason='E2E 测试请假'")
check('请假单落库', len(lv) == 1 and lv[0]['s'] == '待审批', lv[0]['s'] if lv else '无')
if lv:
    mgr.open(BASE + '/desk/leaves/%d/ok' % lv[0]['i'], b'').read()
    s = q("SELECT approval_status s FROM DENTIST_LEAVE WHERE leave_id=?", (lv[0]['i'],))[0]['s']
    check('请假批准生效', s == '已批准', s)

# 10. 店长登记投诉并闭环
mgr.open(BASE + '/desk/complaints/new',
         urllib.parse.urlencode({'patient_id': 1, 'channel': '电话',
                                 'content': 'E2E 投诉内容'}).encode()).read()
cp = q("SELECT complaint_id i, status s FROM COMPLAINT WHERE content='E2E 投诉内容'")
check('投诉落库', len(cp) == 1 and cp[0]['s'] == '待处理', cp[0]['s'] if cp else '无')
if cp:
    # 处理结论现在必填，空提交会被正确拒绝
    r0 = mgr.open(BASE + '/desk/complaints/%d/done' % cp[0]['i'], b'').read()
    s0 = q("SELECT status s FROM COMPLAINT WHERE complaint_id=?", (cp[0]['i'],))[0]['s']
    check('投诉空结论被拒', s0 == '待处理', s0)
    mgr.open(BASE + '/desk/complaints/%d/done' % cp[0]['i'],
             urllib.parse.urlencode({'resolution': 'E2E 已回访致歉并补偿一次洁牙'}).encode()).read()
    s = q("SELECT status s FROM COMPLAINT WHERE complaint_id=?", (cp[0]['i'],))[0]['s']
    check('投诉闭环', s == '已处理', s)

# 11. 患者改约：用一条新的、还没到诊的预约（已到诊的不能改约，这是对的）
h_list2 = pat.open(BASE + '/me/book/1/%s' % day2).read().decode('utf-8')
m3 = re.findall(r'/me/book/confirm/(\d+)\?d=([0-9-]+)', h_list2)
for _rid, _d in m3:
    pat.open(BASE + '/me/book/do',
             urllib.parse.urlencode({'roster_id': _rid, 'date': _d,
                                     'patient_id': pid_me,
                                     'phone': '13700000000',
                                     'visit_reason': 'e2e 改约用'}).encode()).read()
    break
c_r = sqlite3.connect(DB)
aid = c_r.execute("SELECT appointment_id FROM APPOINTMENT WHERE patient_id=?"
                  " AND status='已预约' AND IFNULL(is_void,0)=0"
                  " ORDER BY appointment_id DESC LIMIT 1", (pid_me,)).fetchone()[0]
rid = c_r.execute("SELECT roster_id FROM APPOINTMENT WHERE appointment_id=?",
                  (aid,)).fetchone()[0]
c_r.close()
# 改约页默认停在原门店原日期，那天可能已经约满（是正常情况，不是 bug）。
# 往后找第一个真有可改时段的日期，再改过去。
new_rid = None
pick_day = None
for _k in range(10):
    _d = (date.today() + timedelta(days=1 + _k)).isoformat()
    h = pat.open(BASE + '/me/reschedule/%d?d=%s' % (aid, _d)).read().decode('utf-8')
    m = re.search(r'name="roster_id" value="(\d+)"', h)
    if m:
        new_rid = int(m.group(1))
        pick_day = _d
        break
if new_rid:
    pat.open(BASE + '/me/reschedule/%d' % aid,
             urllib.parse.urlencode({'roster_id': new_rid, 'date': pick_day}).encode()).read()
    got = q("SELECT roster_id r FROM APPOINTMENT WHERE appointment_id=?", (aid,))[0]['r']
    check('改约生效', got == new_rid, 'roster %d -> %d' % (int(rid), got))
else:
    check('改约生效', False, '改约页无可选时段')

print()
bad = [x for x in ok if not x[1]]
print('检查 %d 项，失败 %d 项' % (len(ok), len(bad)))
if bad:
    for n, _, e in bad:
        print('  FAIL', n, e)
    sys.exit(1)