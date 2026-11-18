# -*- coding: utf-8 -*-
"""补数据：seed2 用 `if not exists(表)` 做保护，如果这张表已经被其它脚本
（比如 _e2e.py 造的测试数据）占了 1 行，整批种子就会被跳过。这里按
「行数不足期望值」来补，不覆盖已有数据。
"""
import datetime
import random
import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
random.seed(7788)
DB = 'data/adc.db'
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
TODAY = datetime.date(2026, 11, 11)


def ins(table, **kw):
    cur = c.execute("INSERT INTO %s(%s) VALUES(%s)"
                    % (table, ', '.join(kw), ', '.join('?' * len(kw))), tuple(kw.values()))
    return cur.lastrowid


def n(table):
    return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def dt(d, h=9, m=0):
    return '%s %02d:%02d:00' % (d.isoformat(), h, m)


clinics = [r['clinic_id'] for r in c.execute("SELECT clinic_id FROM CLINIC ORDER BY clinic_id")]
dentists = [r['dentist_id'] for r in c.execute("SELECT dentist_id FROM DENTIST ORDER BY dentist_id")]
staffs = [r['staff_id'] for r in c.execute("SELECT staff_id FROM STAFF ORDER BY staff_id")]
pats = [r['patient_id'] for r in c.execute("SELECT patient_id FROM PATIENT ORDER BY patient_id")]
visits = [r['visit_id'] for r in c.execute("SELECT visit_id FROM VISIT ORDER BY visit_id")]

# ---------- 请假：补到 8 条，其中 3 条待审批 ----------
want = 8
if n('DENTIST_LEAVE') < want:
    plans = [('dentist', 0, '年假', '年假', '已批准'),
             ('dentist', 1, '病假', '病假（感冒发热）', '待审批'),
             ('dentist', 2, '事假', '事假（家中有事）', '已批准'),
             ('dentist', 3, '进修', '进修培训（种植进阶班）', '待审批'),
             ('dentist', 4, '事假', '产检陪同', '已批准'),
             ('dentist', 5, '病假', '病假（腰椎复发）', '待审批'),
             ('dentist', 6, '年假', '年假（调休）', '已批准'),
             ('dentist', 7, '事假', '事假（子女入学）', '已驳回')]
    have = n('DENTIST_LEAVE')
    for i in range(have, want):
        _, di, tp, reason, st = plans[i]
        if c.execute("SELECT 1 FROM DENTIST_LEAVE WHERE leave_reason=?", (reason,)).fetchone():
            continue
        d = TODAY + datetime.timedelta(days=random.randint(-15, 18))
        ins('DENTIST_LEAVE', dentist_id=dentists[di % len(dentists)],
            clinic_id=clinics[di % len(clinics)],
            leave_start=dt(d, 9), leave_end=dt(d, 18),
            leave_type=tp, leave_reason=reason, approval_status=st,
            approver_staff_id=staffs[di % len(staffs)],
            approved_date=(d - datetime.timedelta(days=2)).isoformat(), is_void=0)
    print('DENTIST_LEAVE 补到', n('DENTIST_LEAVE'))

# ---------- 投诉：补到 10 条，其中 4 条待处理 ----------
want = 10
if n('COMPLAINT') < want:
    items = [('电话', '候诊超过 40 分钟，无人告知进度', '待处理'),
             ('微信', '前台承诺的免费复查到店后被告知要收费', '待处理'),
             ('现场', '治疗椅位有异味，卫生状况令人担心', '待处理'),
             ('电话', '改约三次都没约上，要求退费', '待处理'),
             ('微信', '结算单金额与报价不一致', '已处理'),
             ('现场', '牙医操作时未提前告知会疼痛', '已处理'),
             ('电话', '发票开具拖延两周', '已处理'),
             ('微信', '儿童诊室玩具破损有安全隐患', '已处理'),
             ('现场', '停车位不足且无人引导', '已处理'),
             ('电话', '缴费后未收到电子票据', '已处理')]
    have = n('COMPLAINT')
    for i in range(have, want):
        ch, content, st = items[i]
        if c.execute("SELECT 1 FROM COMPLAINT WHERE content=?", (content,)).fetchone():
            continue
        d = TODAY - datetime.timedelta(days=random.randint(1, 45))
        cid = ins('COMPLAINT', patient_id=pats[i % len(pats)],
                  visit_id=visits[i % len(visits)] if i % 2 else None,
                  clinic_id=clinics[i % len(clinics)], channel=ch,
                  content=content, filed_date=dt(d, 10, 30),
                  status=st,
                  resolution='已电话回访并补偿一次洁牙' if st == '已处理' else None)
    print('COMPLAINT 补到', n('COMPLAINT'))

# ---------- 替班：seed2 里把 roster_id 置空了，这里挂上真实排班 ----------
if n('SHIFT_SUBSTITUTION') < 6:
    roster = c.execute(
        "SELECT roster_id, dentist_id, clinic_id, dentist_id FROM ROSTER"
        " WHERE roster_date>=? ORDER BY roster_date LIMIT 12", (TODAY.isoformat(),)).fetchall()
    have = n('SHIFT_SUBSTITUTION')
    for i in range(have, 6):
        r = roster[i % len(roster)] if roster else None
        ins('SHIFT_SUBSTITUTION', roster_id=r['roster_id'] if r else None,
            absent_dentist_id=r['dentist_id'] if r else dentists[i % len(dentists)],
            substitute_dentist_id=dentists[(i + 3) % len(dentists)],
            source_clinic_id=clinics[(i + 1) % len(clinics)],
            effective_from=(TODAY + datetime.timedelta(days=i - 2)).isoformat(),
            effective_to=(TODAY + datetime.timedelta(days=i)).isoformat(),
            reason_type=['请假替班', '跨店征调', '临时补位'][i % 3])
    print('SHIFT_SUBSTITUTION 补到', n('SHIFT_SUBSTITUTION'))

# ---------- 征调：确保有 2 条待审批，供总部工作台演示 ----------
if c.execute("SELECT COUNT(*) FROM SHIFT_REQUISITION WHERE requisition_status='待审批'"
             ).fetchone()[0] == 0:
    for i in range(2):
        d = TODAY + datetime.timedelta(days=2 + i)
        ins('SHIFT_REQUISITION', from_clinic_id=clinics[(i + 1) % len(clinics)],
            to_clinic_id=clinics[i % len(clinics)],
            dentist_id=dentists[(i * 4) % len(dentists)],
            requisition_date=d.isoformat(), start_time='09:00', end_time='18:00',
            requisition_reason='周末正畸复诊集中，需临时增补牙医' if i == 0
            else '种植手术排满，需从邻店征调',
            requisition_status='待审批', submitted_at=dt(TODAY - datetime.timedelta(days=1), 15))
    print('SHIFT_REQUISITION 补了待审批记录')

c.commit()
print()
names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
zero = [t for t in names if c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0] == 0]
tot = sum(c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0] for t in names)
print('表 %d 张，总行数 %d，仍为空 %d 张: %s' % (len(names), tot, len(zero), zero or '无'))
c.close()
