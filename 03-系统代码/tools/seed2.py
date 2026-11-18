# -*- coding: utf-8 -*-
"""补齐 seed.py 没灌的表：耗材/采购/对账/质量/排班/患者扩展/核算/留痕。

seed.py 只灌了「门诊主链路」（门店、牙医、患者、排班、预约、就诊、结算、收款），
其余 37 张表是全空的——界面点进去只有表头。这里按业务关系把它们灌满。
"""
import datetime
import random
import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
random.seed(20261111)

DB = 'data/adc.db'
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row


def ins(table, **kw):
    cols = ', '.join(kw)
    q = ', '.join('?' * len(kw))
    cur = c.execute("INSERT INTO %s(%s) VALUES(%s)" % (table, cols, q), tuple(kw.values()))
    return cur.lastrowid


def exists(table):
    return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


TODAY = datetime.date(2026, 11, 11)
Q = '2026Q4'


def dt(d, h=9, m=0):
    return '%s %02d:%02d:00' % (d.isoformat(), h, m)


clinics = [r['clinic_id'] for r in c.execute("SELECT clinic_id FROM CLINIC ORDER BY clinic_id")]
dentists = [r['dentist_id'] for r in c.execute("SELECT dentist_id FROM DENTIST ORDER BY dentist_id")]
staffs = [r['staff_id'] for r in c.execute("SELECT staff_id FROM STAFF ORDER BY staff_id")]
pats = [r['patient_id'] for r in c.execute("SELECT patient_id FROM PATIENT ORDER BY patient_id")]
visits = [r['visit_id'] for r in c.execute("SELECT visit_id FROM VISIT ORDER BY visit_id")]
catalogs = [r for r in c.execute("SELECT catalog_id, item_name, standard_unit_price FROM TREATMENT_CATALOG")]
accounts = {r['login_name']: r['account_id'] for r in c.execute("SELECT account_id, login_name FROM USER_ACCOUNT")}

# ---------- 1. 供应商与结算条款 ----------
if not exists('SUPPLIER'):
    sup = [('S01', '浙江康泰医疗器械有限公司', '陈志明', '0571-86120001'),
           ('S02', '杭州齿科材料商行', '林晓琳', '0571-86120002'),
           ('S03', '上海瑞邦生物材料公司', '周文斌', '021-56220003'),
           ('S04', '宁波优齿耗材供应站', '郑海燕', '0574-87220004'),
           ('S05', '苏州精工牙科器械厂', '吴国强', '0512-68220005')]
    for code, name, contact, phone in sup:
        ins('SUPPLIER', supplier_code=code, supplier_name=name,
            contact_name=contact, phone=phone)
supplier_ids = [r['supplier_id'] for r in c.execute("SELECT supplier_id FROM SUPPLIER ORDER BY supplier_id")]

if not exists('SETTLEMENT_TERM'):
    terms = [('T30', 30, 0.02, '月结 30 天，逾期按 2% 计息'),
             ('T45', 45, 0.015, '月结 45 天'),
             ('T60', 60, 0.01, '月结 60 天，整单退换 1%'),
             ('TCASH', 0, 0.0, '货到付款')]
    for code, days, ratio, items in terms:
        ins('SETTLEMENT_TERM', term_code=code, payment_days=days,
            return_ratio=ratio, fee_items=items)
term_ids = [r['term_id'] for r in c.execute("SELECT term_id FROM SETTLEMENT_TERM ORDER BY term_id")]

# ---------- 2. 物料与批次 ----------
MATS = [
    ('M001', '光固化复合树脂 A2', '支', 0, 20),
    ('M002', '光固化复合树脂 A3', '支', 0, 20),
    ('M003', '进口麻药（阿替卡因）', '支', 1, 50),
    ('M004', '一次性检查手套', '盒', 0, 30),
    ('M005', '一次性口腔器械盘', '套', 0, 100),
    ('M006', '高速车针（金刚砂）', '支', 0, 40),
    ('M007', '低速球钻', '支', 0, 40),
    ('M008', '硅橡胶印模材', '盒', 0, 15),
    ('M009', '种植体（标准型）', '枚', 1, 5),
    ('M010', '正畸托槽套装', '套', 1, 8),
    ('M011', '根管锉（机用）', '盒', 0, 12),
    ('M012', '消毒灭菌指示卡', '盒', 0, 10),
]
if not exists('MATERIAL'):
    for code, name, unit, hv, rp in MATS:
        ins('MATERIAL', material_code=code, material_name=name, unit=unit,
            is_high_value=hv, reorder_point=rp)
mats = [(r['material_id'], r['is_high_value']) for r in
        c.execute("SELECT material_id, is_high_value FROM MATERIAL ORDER BY material_id")]

if not exists('MATERIAL_BATCH'):
    for mid, hv in mats:
        for k in range(2):
            exp = TODAY + datetime.timedelta(days=random.choice([180, 420, 730]))
            ins('MATERIAL_BATCH', material_id=mid,
                batch_serial_no='B%s-%02d' % (TODAY.strftime('%y%m'), k + 1),
                expiry_date=exp.isoformat(),
                purchase_unit_price=round(random.uniform(8, 900) * (6 if hv else 1), 2))
batches = [(r['batch_id'], r['material_id']) for r in
           c.execute("SELECT batch_id, material_id FROM MATERIAL_BATCH ORDER BY batch_id")]

# ---------- 3. 库存台账 + 流水 ----------
if not exists('STOCK_LEDGER'):
    for cid in clinics:
        for mid, hv in mats:
            qty = random.randint(2, 6) if hv else random.randint(60, 400)
            lid = ins('STOCK_LEDGER', clinic_id=cid, material_id=mid, on_hand_qty=qty,
                      is_void=0)
            ins('STOCK_MOVEMENT', ledger_id=lid, movement_type='入库', direction='增加',
                quantity=qty, source_type='入库单', source_no='GRN-%02d-%03d' % (cid, mid),
                moved_datetime=dt(TODAY - datetime.timedelta(days=random.randint(5, 60))))
            if not hv:
                out = random.randint(5, 20)
                ins('STOCK_MOVEMENT', ledger_id=lid, movement_type='领用', direction='减少',
                    quantity=out, source_type='领用单', source_no='MI-%02d-%03d' % (cid, mid),
                    moved_datetime=dt(TODAY - datetime.timedelta(days=random.randint(1, 20))))

# ---------- 4. 采购单 / 入库单 / 对账单 / 应付 ----------
if not exists('PURCHASE_ORDER'):
    for i in range(8):
        sid = supplier_ids[i % len(supplier_ids)]
        od = TODAY - datetime.timedelta(days=random.randint(20, 90))
        pid = ins('PURCHASE_ORDER', po_no='PO2026%04d' % (101 + i), supplier_id=sid,
                  term_id=term_ids[i % len(term_ids)], order_date=od.isoformat(),
                  expected_date=(od + datetime.timedelta(days=7)).isoformat(),
                  status=random.choice(['已入库', '已入库', '已下单']), is_void=0)
        for ln in range(1, random.randint(2, 4)):
            mid = mats[random.randrange(len(mats))][0]
            ins('PURCHASE_ORDER_LINE', po_id=pid, line_no=ln, material_id=mid,
                quantity=random.randint(5, 60),
                unit_price=round(random.uniform(8, 900), 2))

pos = [r['po_id'] for r in c.execute("SELECT po_id FROM PURCHASE_ORDER ORDER BY po_id")]
if not exists('RECEIPT_NOTE'):
    for i, pid in enumerate(pos[:6]):
        rid = ins('RECEIPT_NOTE', receipt_no='GRN2026%04d' % (201 + i), po_id=pid,
                  clinic_id=clinics[i % len(clinics)],
                  received_date=(TODAY - datetime.timedelta(days=random.randint(5, 50))).isoformat(),
                  status='已入库', is_void=0)
        ln = 1
        for bid, mid in batches[:random.randint(2, 4)]:
            ins('RECEIPT_LINE', receipt_id=rid, line_no=ln, material_id=mid,
                batch_id=bid, quantity=random.randint(5, 40))
            ln += 1

if not exists('STATEMENT'):
    for i, sid in enumerate(supplier_ids[:4]):
        st = TODAY.replace(day=1) - datetime.timedelta(days=30 * (i % 3 + 1))
        en = st.replace(day=28)
        stid = ins('STATEMENT', statement_no='ST2026%04d' % (301 + i), supplier_id=sid,
                   period_start=st.isoformat(), period_end=en.isoformat(),
                   status='已对账', is_void=0)
        for ln in range(1, 4):
            ins('STATEMENT_LINE', statement_id=stid, line_no=ln,
                source_type=random.choice(['采购单', '入库单']),
                source_no='PO2026%04d' % (101 + random.randint(0, 7)),
                amount=round(random.uniform(800, 12000), 2))

sts = [r['statement_id'] for r in c.execute("SELECT statement_id FROM STATEMENT ORDER BY statement_id")]
if not exists('ACCOUNT_PAYABLE'):
    for i, stid in enumerate(sts):
        sid = c.execute("SELECT supplier_id FROM STATEMENT WHERE statement_id=?", (stid,)).fetchone()[0]
        pid = ins('ACCOUNT_PAYABLE', supplier_id=sid, statement_id=stid,
                  payable_no='AP2026%04d' % (401 + i),
                  payable_amount=round(random.uniform(2000, 30000), 2),
                  status=random.choice(['未付', '部分付款', '已付清']), is_void=0)
        if c.execute("SELECT status FROM ACCOUNT_PAYABLE WHERE payable_id=?", (pid,)).fetchone()[0] != '未付':
            ins('PAYMENT_RECORD', payable_id=pid, supplier_id=sid,
                record_no='PR2026%04d' % (501 + i),
                amount=round(random.uniform(500, 15000), 2),
                method=random.choice(['银行转账', '承兑汇票', '支付宝']),
                paid_date=(TODAY - datetime.timedelta(days=random.randint(1, 30))).isoformat(),
                is_void=0)

# ---------- 5. 质量与院感 ----------
if not exists('QUALITY_INCIDENT'):
    kinds = [('器械消毒不合格', '灭菌指示卡变色不达标', '高'),
             ('材料过期', '库存盘点发现过期树脂 3 支', '中'),
             ('诊疗并发症', '根管治疗后疼痛加重', '中'),
             ('病历记录不全', '抽查发现 2 份病历缺知情同意', '低'),
             ('候诊超时', '高峰时段患者候诊超 60 分钟', '低'),
             ('设备故障', '椅位涡轮机异响停用', '中')]
    for i, (tp, desc, sev) in enumerate(kinds):
        ins('QUALITY_INCIDENT', visit_id=visits[i * 7 % len(visits)],
            clinic_id=clinics[i % len(clinics)], incident_type=tp,
            description=desc, occurred_date=(TODAY - datetime.timedelta(days=random.randint(3, 60))).isoformat(),
            severity=sev, status=random.choice(['已处理', '处理中', '待处理']), is_void=0)

if not exists('DISINFECTION_RECORD'):
    for cid in clinics:
        for k in range(6):
            d = TODAY - datetime.timedelta(days=k * 3)
            ins('DISINFECTION_RECORD', clinic_id=cid, record_date=d.isoformat(),
                operator_name='助手 %d' % ((cid + k) % 4 + 1),
                scope=random.choice(['高速手机', '治疗椅位', '器械盘', '诊室空气']),
                result=random.choice(['合格', '合格', '合格', '复检合格']), is_void=0)

# ---------- 6. 排班流转：请假 / 调班 / 征调 / 替班 ----------
if not exists('DENTIST_LEAVE'):
    reasons = ['年假', '病假（感冒）', '事假（家中有事）', '进修培训', '产检']
    for i in range(6):
        d = TODAY + datetime.timedelta(days=random.randint(-20, 15))
        ins('DENTIST_LEAVE', dentist_id=dentists[i % len(dentists)],
            clinic_id=clinics[i % len(clinics)],
            leave_start=dt(d, 9), leave_end=dt(d, 18),
            leave_type=random.choice(['事假', '病假', '年假']),
            leave_reason=reasons[i % len(reasons)],
            approval_status=random.choice(['已批准', '已批准', '待审批', '已驳回']),
            approver_staff_id=staffs[i % len(staffs)],
            approved_date=(d - datetime.timedelta(days=2)).isoformat(),
            is_void=0)

if not exists('SHIFT_REQUEST'):
    reasons = ['本店患者激增', '邻店牙医临时请假', '种植手术排不下', '正畸复诊集中']
    for i in range(5):
        d = TODAY + datetime.timedelta(days=random.randint(-10, 10))
        ins('SHIFT_REQUEST', clinic_id=clinics[i % len(clinics)],
            requester_staff_id=staffs[i % len(staffs)],
            dentist_id=dentists[i % len(dentists)],
            request_date=d.isoformat(), slot_start='09:00', slot_end='12:00',
            direction=random.choice(['调入', '调出']),
            reason=reasons[i % len(reasons)],
            request_status=random.choice(['已批准', '待审批', '待审批', '已驳回']),
            approver_staff_id=staffs[(i + 1) % len(staffs)],
            approved_date=(d - datetime.timedelta(days=1)).isoformat(), is_void=0)

if not exists('SHIFT_REQUISITION'):
    reasons = ['城西旗舰店种植手术排满，需从滨江调 1 名种植牙医',
               '余杭店周末正畸复诊集中，需从城西调 1 名正畸牙医',
               '城西店牙医集体培训，需从余杭调 2 名全科牙医']
    for i in range(3):
        d = TODAY + datetime.timedelta(days=random.randint(-5, 12))
        ins('SHIFT_REQUISITION', from_clinic_id=clinics[(i + 1) % len(clinics)],
            to_clinic_id=clinics[i % len(clinics)],
            dentist_id=dentists[(i * 3) % len(dentists)],
            requisition_date=d.isoformat(), start_time='09:00', end_time='18:00',
            requisition_reason=reasons[i],
            requisition_status=random.choice(['已批准', '待审批', '已驳回']),
            requester_account_id=accounts.get('ops1'),
            approver_account_id=accounts.get('manager1') if i != 1 else None,
            submitted_at=dt(d - datetime.timedelta(days=1), 10),
            approved_at=dt(d, 9) if i != 1 else None)

if not exists('SHIFT_SUBSTITUTION'):
    for i in range(4):
        d = TODAY + datetime.timedelta(days=random.randint(-8, 8))
        ins('SHIFT_SUBSTITUTION', roster_id=None,
            absent_dentist_id=dentists[i % len(dentists)],
            substitute_dentist_id=dentists[(i + 3) % len(dentists)],
            source_clinic_id=clinics[(i + 1) % len(clinics)],
            effective_from=d.isoformat(),
            effective_to=(d + datetime.timedelta(days=2)).isoformat(),
            reason_type=random.choice(['请假替班', '跨店征调', '临时补位']))

# ---------- 7. 患者扩展：过敏 / 病史 / 会员 / 治疗计划 / 召回 / 影像 / 保单 ----------
if not exists('ALLERGY'):
    items = [('青霉素', '药物', '严重', '过敏性休克史'), ('磺胺类', '药物', '中度', '皮疹'),
             ('利多卡因', '药物', '严重', '心悸、晕厥'), ('橡胶', '材料', '中度', '接触性皮炎'),
             ('海鲜', '食物', '轻度', '荨麻疹'), ('花粉', '环境', '轻度', '打喷嚏、流泪')]
    for i, p in enumerate(pats[:24]):
        name, tp, sev, rx = items[i % len(items)]
        ins('ALLERGY', patient_id=p, allergy_name=name, allergen_type=tp,
            severity=sev, reaction=rx,
            discovered_date=(TODAY - datetime.timedelta(days=random.randint(30, 2000))).isoformat(),
            is_confirmed=random.choice([0, 1]),
            confirming_dentist_id=dentists[i % len(dentists)] if i % 2 else None)

if not exists('MEDICAL_HISTORY'):
    conds = ['高血压（服药控制）', '2 型糖尿病', '冠心病支架术后', '甲状腺功能减退',
             '妊娠 20 周', '乙肝携带者', '哮喘', '长期服用抗凝药']
    for i, p in enumerate(pats[:30]):
        ins('MEDICAL_HISTORY', patient_id=p,
            record_date=(TODAY - datetime.timedelta(days=random.randint(10, 1200))).isoformat(),
            condition_description=conds[i % len(conds)],
            status=random.choice(['稳定', '随访中', '已治愈']))

if not exists('MEMBER'):
    for i, p in enumerate(pats[:18]):
        ins('MEMBER', patient_id=p, member_no='MB2026%04d' % (1001 + i),
            member_level=random.choice(['普通', '银卡', '金卡', '钻石']),
            joined_date=(TODAY - datetime.timedelta(days=random.randint(60, 1500))).isoformat())

if not exists('TREATMENT_PLAN'):
    for i, v in enumerate(visits[:40]):
        ins('TREATMENT_PLAN', visit_id=v, plan_no='TP2026%04d' % (2001 + i),
            created_date=(TODAY - datetime.timedelta(days=random.randint(1, 120))).isoformat(),
            plan_description=random.choice([
                '分三次完成：①洁治 + 抛光 ②树脂充填 2 颗 ③复查',
                '正畸方案：拔除 4 颗前磨牙，24 个月固定矫治，每月复诊',
                '种植方案：左下第一磨牙拔除后 3 个月植入，6 个月后冠修复',
                '根管治疗：分两次完成，术后 1 周复查，建议冠修复']))

if not exists('FOLLOWUP_RECALL'):
    for i, v in enumerate(visits[:40]):
        d = TODAY + datetime.timedelta(days=random.randint(-30, 120))
        done = d < TODAY
        ins('FOLLOWUP_RECALL', patient_id=pats[i % len(pats)], visit_id=v,
            due_date=d.isoformat(), channel=random.choice(['短信', '微信', '电话']),
            status='已完成' if done else random.choice(['待召回', '待召回', '已联系']),
            completed_date=d.isoformat() if done else None, is_void=0)

if not exists('IMAGE_RECORD'):
    for i, v in enumerate(visits[:50]):
        ins('IMAGE_RECORD', patient_id=pats[i % len(pats)], visit_id=v,
            tooth_fdi=str(random.choice([11, 16, 24, 36, 46])),
            image_type=random.choice(['根尖片', '全景片', 'CBCT', '口内照']),
            image_url='/media/xray/%d_%d.jpg' % (v, i),
            taken_datetime=dt(TODAY - datetime.timedelta(days=random.randint(1, 90)), 10))

if not exists('INSURANCE_POLICY'):
    for i, p in enumerate(pats[:20]):
        ins('INSURANCE_POLICY', patient_id=p,
            insurer_name=random.choice(['中国人保健康', '平安健康', '泰康在线', '太平洋保险']),
            policy_no='PL2026%06d' % (300001 + i),
            coverage_scope=random.choice(['门诊 70%　住院 90%', '门诊 60%　不限住院',
                                          '仅住院 80%', '门诊 50%　上限 5000 元']),
            valid_until=(TODAY + datetime.timedelta(days=random.randint(60, 700))).isoformat())

# ---------- 8. 保险理赔 / 分期 ----------
invs = [r['invoice_id'] for r in c.execute("SELECT invoice_id FROM INVOICE ORDER BY invoice_id LIMIT 60")]
pols = [r['policy_id'] for r in c.execute("SELECT policy_id FROM INSURANCE_POLICY ORDER BY policy_id")]
if not exists('INSURANCE_CLAIM') and pols:
    for i in range(12):
        claimed = round(random.uniform(300, 6000), 2)
        ins('INSURANCE_CLAIM', invoice_id=invs[i * 3 % len(invs)],
            policy_id=pols[i % len(pols)],
            submitted_date=(TODAY - datetime.timedelta(days=random.randint(5, 90))).isoformat(),
            claimed_amount=claimed,
            approved_amount=round(claimed * random.choice([0.0, 0.6, 0.7, 0.8, 0.9]), 2),
            status=random.choice(['已理赔', '已理赔', '审核中', '已驳回', '待提交']))

if not exists('INSTALLMENT_PLAN'):
    for i in range(10):
        ins('INSTALLMENT_PLAN', invoice_id=invs[i * 5 % len(invs)],
            installment_count=random.choice([3, 6, 12]),
            first_due_date=(TODAY + datetime.timedelta(days=15)).isoformat(),
            status=random.choice(['履约中', '已结清', '已逾期']))

# ---------- 9. 核算：成本版本 / 标准成本 / 运营费用 / 分摊 / 业绩 / 激励 ----------
if not exists('COST_VERSION'):
    for i, (no, d) in enumerate([('V2025', '2025-01-01'), ('V2026', '2026-01-01'),
                                 ('V2026H2', '2026-07-01')]):
        ins('COST_VERSION', version_no=no, effective_date=d,
            description='按%s采购价与人力成本口径' % d[:4])
vers = [r['version_id'] for r in c.execute("SELECT version_id FROM COST_VERSION ORDER BY version_id")]

if not exists('STANDARD_COST'):
    for cat in catalogs:
        for vid in vers:
            base = float(cat['standard_unit_price'] or 100)
            ins('STANDARD_COST', catalog_id=cat['catalog_id'], version_id=vid,
                standard_cost=round(base * random.uniform(0.45, 0.7), 2),
                effective_date=('2025-01-01' if vid == 1 else
                                '2026-01-01' if vid == 2 else '2026-07-01'))

if not exists('OPERATING_EXPENSE'):
    cats = [('房租', 38000), ('人力', 96000), ('水电', 6200), ('耗材摊销', 18000),
            ('设备折旧', 9500), ('市场推广', 7800)]
    for cid in clinics:
        for cat, base in cats:
            ins('OPERATING_EXPENSE', clinic_id=cid, quarter=Q, expense_category=cat,
                amount=round(base * random.uniform(0.85, 1.2), 2),
                description='%s %s' % (Q, cat), is_void=0)

if not exists('EXPENSE_ALLOCATION'):
    exps = [r['expense_id'] for r in c.execute("SELECT expense_id FROM OPERATING_EXPENSE")]
    for i, e in enumerate(exps[:18]):
        ins('EXPENSE_ALLOCATION', expense_id=e, clinic_id=clinics[i % len(clinics)],
            quarter=Q, allocated_amount=round(random.uniform(1000, 9000), 2),
            basis=random.choice(['按就诊人次', '按收入占比', '按椅位数', '按牙医人数']),
            is_void=0)

if not exists('DENTIST_QUARTER_PERFORMANCE'):
    for d in dentists:
        rev = round(random.uniform(80000, 260000), 2)
        ins('DENTIST_QUARTER_PERFORMANCE', dentist_id=d, quarter=Q,
            revenue_amount=rev, cost_amount=round(rev * random.uniform(0.3, 0.45), 2),
            operating_expense_amount=round(rev * random.uniform(0.15, 0.25), 2),
            visit_count=random.randint(80, 320),
            patient_count=random.randint(50, 200),
            recall_rate=round(random.uniform(0.55, 0.92), 3),
            complaint_count=random.randint(0, 3),
            quality_incident_count=random.randint(0, 2),
            chair_utilization=round(random.uniform(0.6, 0.95), 3),
            work_days=random.randint(55, 66))

if not exists('INCENTIVE_FUND'):
    perfs = [r for r in c.execute(
        "SELECT perf_id, revenue_amount, cost_amount, operating_expense_amount"
        " FROM DENTIST_QUARTER_PERFORMANCE")]
    for p in perfs:
        net = float(p['revenue_amount']) - float(p['cost_amount']) - float(p['operating_expense_amount'])
        rate = 0.12
        ins('INCENTIVE_FUND', perf_id=p['perf_id'], quarter=Q,
            net_profit=round(net, 2), fund_rate=rate,
            fund_amount=round(max(net, 0) * rate, 2), is_void=0)

# ---------- 10. 留痕 ----------
if not exists('AUDIT_LOG'):
    fields = ['diagnosis', 'treatment_note', 'agreed_price', 'status']
    for i in range(30):
        v = visits[i * 5 % len(visits)]
        f = fields[i % len(fields)]
        ins('AUDIT_LOG', patient_id=pats[i % len(pats)], record_table='VISIT',
            record_id_ref=str(v), changed_field=f,
            old_value='原值 %d' % i, new_value='新值 %d' % (i + 1),
            operator_name=random.choice(['dentist1', 'dentist2', 'recept1']),
            changed_datetime=dt(TODAY - datetime.timedelta(days=random.randint(1, 40)),
                                random.randint(9, 17), random.choice([0, 15, 30, 45])))

if not exists('RECORD_ACCESS_LOG'):
    for i in range(25):
        ins('RECORD_ACCESS_LOG', patient_id=pats[i % len(pats)],
            clinic_id=clinics[i % len(clinics)],
            operator_name=random.choice(['dentist1', 'dentist2', 'assist1', 'recept1']),
            access_datetime=dt(TODAY - datetime.timedelta(days=random.randint(0, 30)),
                               random.randint(8, 18)),
            purpose=random.choice(['诊疗调阅', '复诊准备', '质量抽查', '患者本人申请']),
            authorization_ref=random.choice(['本人授权', '诊疗需要', '质量委员会']))

c.commit()

print('补齐完成，各表行数：')
names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
zero = 0
for t in names:
    n = c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    if n == 0:
        zero += 1
        print('  仍为空:', t)
tot = sum(c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0] for t in names)
print('表 %d 张，总行数 %d，仍为空的表 %d 张' % (len(names), tot, zero))
c.close()
