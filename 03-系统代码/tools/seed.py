# -*- coding: utf-8 -*-
r"""灌演示数据：门店、人员、患者、排班、预约、就诊、结算、收款、账号。

跑法：python tools/seed.py          （库已存在则先清空再灌）
      python tools/seed.py --keep   （不清空，追加）
"""
import hashlib
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
DB = os.path.join(CODE, "data", "adc.db")
SCHEMA = os.path.join(CODE, "app", "schema.sql")

random.seed(20261111)

CN_SURNAME = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤")
CN_GIVEN = ["建华", "秀英", "志强", "丽娟", "海涛", "文静", "国庆", "晓梅", "永强", "玉兰",
            "宏伟", "丽华", "俊杰", "雪梅", "建国", "春燕", "志远", "梦琪", "家豪", "思雨"]

QUALIFICATIONS = [
    ("Q01", "口腔全科医师", "省级卫生健康委员会"),
    ("Q02", "正畸专科", "中华口腔医学会正畸专委会"),
    ("Q03", "种植专科", "中华口腔医学会种植专委会"),
    ("Q04", "儿童口腔专科", "中华口腔医学会儿童口腔专委会"),
    ("Q05", "牙周专科", "中华口腔医学会牙周病专委会"),
    ("Q06", "牙体牙髓专科", "中华口腔医学会牙体牙髓专委会"),
    ("Q07", "口腔修复专科", "中华口腔医学会修复专委会"),
]

CATALOG = [
    ("T01", "口腔检查与方案设计", "次", 60, 0),
    ("T02", "超声波洁治（洗牙）", "次", 180, 0),
    ("T03", "树脂充填（单面）", "牙", 280, 0),
    ("T04", "根管治疗（单根）", "牙", 900, 0),
    ("T05", "根管治疗（多根）", "牙", 1400, 0),
    ("T06", "普通拔牙", "牙", 150, 0),
    ("T07", "复杂拔牙（阻生齿）", "牙", 800, 0),
    ("T08", "全瓷冠修复", "牙", 2600, 0),
    ("T09", "种植体植入", "颗", 8800, 0),
    ("T10", "全口涂氟", "次", 200, 1),
    ("T11", "儿童窝沟封闭", "牙", 120, 0),
    ("T12", "牙周基础治疗", "象限", 600, 0),
]

CLINICS = [
    ("C01", "城西旗舰店", "杭州市西湖区文一西路 588 号", "浙江杭州", "王建国",
     "0571-88881001", 820.0, "浙卫医执字 2021-0101 号", "2026-12-31", "口腔全科、正畸、种植", "2016-03-18"),
    ("C02", "滨江中心店", "杭州市滨江区江南大道 1088 号", "浙江杭州", "李秀英",
     "0571-88881002", 640.0, "浙卫医执字 2021-0188 号", "2026-12-31", "口腔全科、正畸", "2018-09-06"),
    ("C03", "余杭未来科技城店", "杭州市余杭区文一西路 998 号", "浙江杭州", "张海涛",
     "0571-88881003", 510.0, "浙卫医执字 2022-0233 号", "2027-06-30", "口腔全科、儿童口腔", "2022-05-20"),
]


def h(pw):
    salt = "seed-salt-" + pw
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000)
    return dk.hex(), salt


def main():
    keep = "--keep" in sys.argv
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    if not os.path.exists(DB):
        con = sqlite3.connect(DB)
        con.executescript(open(SCHEMA, encoding="utf-8").read())
        con.commit()
        con.close()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    if not keep:
        # 清空时按外键依赖会冲突（DELETE 顺序无法满足所有引用），
        # 临时关掉外键检查，清完再打开——这里清的是自己的演示库，不会留下悬空引用。
        con.execute("PRAGMA foreign_keys = OFF")
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            if t.startswith("sqlite_"):
                continue
            con.execute("DELETE FROM %s" % t)
        con.commit()
        con.execute("PRAGMA foreign_keys = ON")

    now = datetime.now()
    today = now.date()

    # ---------------- 门店
    for c in CLINICS:
        con.execute(
            "INSERT INTO CLINIC (clinic_no, clinic_name, postal_address, region, manager_name,"
            " phone, office_area_sqm, license_no, license_valid_until, service_scope, opened_date)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", c)

    # ---------------- 营业日历（一周七天，周末也开）
    for cid in (1, 2, 3):
        for wd in range(1, 8):
            con.execute(
                "INSERT INTO CLINIC_CALENDAR (clinic_id, weekday, open_time, close_time,"
                " is_operating, chair_count) VALUES (?,?,?,?,?,?)",
                (cid, wd, "09:00" if wd <= 5 else "09:30", "18:00" if wd <= 5 else "17:00",
                 1, 4 if cid == 1 else 3))

    # ---------------- 资质
    for q in QUALIFICATIONS:
        con.execute("INSERT INTO QUALIFICATION (qualification_code, qualification_name,"
                    " issuing_body) VALUES (?,?,?)", q)

    # ---------------- 牙医
    dentists = []
    for i in range(10):
        nm = random.choice(CN_SURNAME) + random.choice(CN_GIVEN)
        con.execute("INSERT INTO DENTIST (employee_no, name, date_of_birth, phone, active)"
                    " VALUES (?,?,?,?,1)",
                    (1000 + i, nm,
                     "%d-%02d-%02d" % (random.randint(1975, 1995), random.randint(1, 12), random.randint(1, 28)),
                     "138%08d" % random.randint(0, 99999999)))
        did = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        dentists.append(did)
        # 每人 1-2 项资质
        for qid in random.sample(range(1, 8), random.randint(1, 2)):
            con.execute(
                "INSERT INTO DENTIST_QUALIFICATION (dentist_id, qualification_id, obtained_date,"
                " certificate_no, valid_until, cert_status) VALUES (?,?,?,?,?,?)",
                (did, qid, "%d-%02d-01" % (random.randint(2015, 2023), random.randint(1, 12)),
                 "ZS%06d" % random.randint(0, 999999), "2028-12-31", "有效"))

    # ---------------- 员工
    staff = []
    for i, (role, n) in enumerate([("诊所接待员", 1), ("牙医助手", 1), ("门店主管", 1)]):
        for k in range(n + (1 if role == "牙医助手" else 0)):
            nm = random.choice(CN_SURNAME) + random.choice(CN_GIVEN)
            cid = (k % 3) + 1
            con.execute("INSERT INTO STAFF (clinic_id, staff_no, name, role, phone) VALUES (?,?,?,?,?)",
                        (cid, 2000 + i * 10 + k, nm, role, "139%08d" % random.randint(0, 99999999)))
            staff.append((con.execute("SELECT last_insert_rowid()").fetchone()[0], cid, role))

    # ---------------- 治疗项目目录
    for it in CATALOG:
        con.execute("INSERT INTO TREATMENT_CATALOG (item_code, item_name, unit,"
                    " standard_unit_price, is_whole_mouth) VALUES (?,?,?,?,?)", it)

    # ---------------- 患者
    n_patient = 60
    for i in range(n_patient):
        nm = random.choice(CN_SURNAME) + random.choice(CN_GIVEN)
        con.execute(
            "INSERT INTO PATIENT (patient_no, name, date_of_birth, phone, email, id_card_no,"
            " insurance_card_no, occupation, source_channel, first_visit_date)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (10001 + i, nm,
             "%d-%02d-%02d" % (random.randint(1955, 2018), random.randint(1, 12), random.randint(1, 28)),
             "137%08d" % random.randint(0, 99999999),
             "p%d@example.com" % i,
             "3301%02d%04d%04d%02d%02d" % (random.randint(1, 12), random.randint(0, 9999),
                                          random.randint(0, 9999), random.randint(0, 12),
                                          random.randint(1, 28)),
             "YB%010d" % random.randint(0, 9999999999),
             random.choice(["职员", "教师", "工程师", "学生", "自由职业", "退休"]),
             random.choice(["小程序", "电话", "到店", "老患者推荐"]),
             (today - timedelta(days=random.randint(30, 900))).isoformat()))

    # ---------------- 排班：过去 30 天 + 未来 7 天
    roster_rows = []
    for delta in range(-30, 8):
        d = today + timedelta(days=delta)
        for cid in (1, 2, 3):
            for did in random.sample(dentists, 3):
                for slot, (s, e) in enumerate([("09:00", "12:00"), ("13:30", "18:00")]):
                    con.execute(
                        "INSERT INTO ROSTER (dentist_id, clinic_id, roster_date, slot_start,"
                        " slot_end, slot_capacity, roster_status, is_published)"
                        " VALUES (?,?,?,?,?,?,?,1)",
                        (did, cid, d.isoformat(), s, e, 6, "正常"))
                    roster_rows.append((con.execute("SELECT last_insert_rowid()").fetchone()[0],
                                        did, cid, d))

    # ---------------- 预约 + 就诊 + 结算 + 收款
    cat = con.execute("SELECT catalog_id, standard_unit_price, item_name, unit FROM TREATMENT_CATALOG").fetchall()
    n_appt = 0
    n_visit = 0
    n_inv = 0
    for rid, did, cid, d in roster_rows:
        taken = set()          # 同一个人不可能在同一个时段占两个号
        for k in range(random.randint(1, 5)):
            pid = random.randint(1, n_patient)
            if pid in taken:
                continue
            taken.add(pid)
            hh = random.randint(9, 17)
            mm = random.choice([0, 30])
            dt = "%s %02d:%02d:00" % (d.isoformat(), hh, mm)
            past = d < today
            status = "已到诊" if past and random.random() < 0.85 else ("已取消" if past else "已预约")
            con.execute(
                "INSERT INTO APPOINTMENT (appointment_no, patient_id, roster_id,"
                " appointment_datetime, status, cancellation_category, visit_reason)"
                " VALUES (?,?,?,?,?,?,?)",
                ("A%s%04d" % (d.strftime("%Y%m%d"), n_appt + 1),
                 pid, rid, dt, status,
                 random.choice(["患者原因", "门店原因"]) if status == "已取消" else None,
                 random.choice(["牙齿酸痛", "要求洗牙", "复查", "牙龈出血", "补牙", ""])),
            )
            aid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            n_appt += 1
            if status != "已到诊":
                continue
            con.execute(
                "INSERT INTO VISIT (visit_no, appointment_id, clinic_id, visit_datetime, treated,"
                " chief_complaint, diagnosis, treatment_note)"
                " VALUES (?,?,?,?,1,?,?,?)",
                (30000 + n_visit, aid, cid, dt,
                 random.choice(["牙齿酸痛三天", "要求洗牙", "右上后牙咬合痛", "牙龈出血", "复查"]),
                 random.choice(["慢性牙髓炎", "牙结石沉积", "深龋", "慢性牙周炎", "未见异常"]),
                 "已处置，嘱复诊"))
            vid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            n_visit += 1
            # 治疗行
            total = 0
            for ln in range(random.randint(1, 3)):
                c = random.choice(cat)
                units = random.randint(1, 2)
                price = c["standard_unit_price"]
                total += units * price
                con.execute(
                    "INSERT INTO TREATMENT_ITEM (visit_id, line_no, catalog_id, dentist_id,"
                    " tooth_fdi, standard_units, standard_unit_price, agreed_price, added_during_visit)"
                    " VALUES (?,?,?,?,?,?,?,?,1)",
                    (vid, ln + 1, c["catalog_id"], did,
                     random.choice([11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 25, 26, 31, 36, 41, 46]),
                     units, price, price))
            # 结算单
            inv_no = "INV%06d" % (40000 + n_inv)
            con.execute("INSERT INTO INVOICE (invoice_no, visit_id, invoice_date, status)"
                        " VALUES (?,?,?,?)", (inv_no, vid, d.isoformat(), "已收款"))
            iid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO INVOICE_LINE (invoice_id, line_no, item_name, units_used,"
                        " unit_price, line_subtotal) VALUES (?,?,?,?,?,?)",
                        (iid, 1, "诊疗费用合计", 1, total, total))
            n_inv += 1
            if random.random() < 0.9:
                con.execute("INSERT INTO PAYMENT (invoice_id, payment_no, amount, method,"
                            " paid_datetime) VALUES (?,?,?,?,?)",
                            (iid, "PAY%06d" % (50000 + n_inv), total,
                             random.choice(["微信", "支付宝", "银行卡", "现金"]),
                             dt))

    # ---------------- 账号
    def add_acc(login, pw, role, staff_id=None, dentist_id=None):
        ph, salt = h(pw)
        con.execute(
            "INSERT INTO USER_ACCOUNT (login_name, password_hash, password_salt, role,"
            " staff_id, dentist_id, account_status, registered_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (login, ph, salt, role, staff_id, dentist_id, "正常",
             now.strftime("%Y-%m-%d %H:%M:%S")))
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 患者账号：PATIENT.account_id 指向 USER_ACCOUNT（一个账号可带多个患者）
    p1 = con.execute("SELECT account_id FROM PATIENT WHERE patient_id=1").fetchone()
    acc1 = add_acc("zhangsan", "123456", "patient")
    con.execute("UPDATE PATIENT SET account_id=? WHERE patient_id=1", (acc1,))
    acc2 = add_acc("lisi", "123456", "patient")
    con.execute("UPDATE PATIENT SET account_id=? WHERE patient_id=2", (acc2,))
    # 再有几个患者挂到 zhangsan 名下（家长带孩子）
    for pid in (3, 4):
        con.execute("UPDATE PATIENT SET account_id=? WHERE patient_id=?", (acc1, pid))
    recept = [s for s in staff if s[2] == "诊所接待员"]
    mgr = [s for s in staff if s[2] == "门店主管"]
    asist = [s for s in staff if s[2] == "牙医助手"]
    add_acc("recept1", "123456", "receptionist", staff_id=(recept[0][0] if recept else None))
    add_acc("dentist1", "123456", "dentist", dentist_id=dentists[0])
    add_acc("dentist2", "123456", "dentist", dentist_id=dentists[1])
    add_acc("assist1", "123456", "assistant", staff_id=(asist[0][0] if asist else None))
    add_acc("manager1", "123456", "supervisor", staff_id=(mgr[0][0] if mgr else None))
    add_acc("ops1", "123456", "ops")
    add_acc("finance1", "123456", "finance")

    con.commit()
    print("门店 %d / 牙医 %d / 员工 %d / 患者 %d / 排班 %d / 预约 %d / 就诊 %d / 结算 %d"
          % (len(CLINICS), len(dentists), len(staff), n_patient, len(roster_rows), n_appt, n_visit, n_inv))
    print("账号：zhangsan lisi recept1 dentist1 dentist2 assist1 manager1 ops1 finance1（口令都是 123456）")
    con.close()


if __name__ == "__main__":
    main()
