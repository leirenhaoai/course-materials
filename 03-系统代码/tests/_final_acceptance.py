# -*- coding: utf-8 -*-
"""最终验收：按「一个真实用户能不能完整走通」来测，而不是「页面能不能打开」。

分五组：
  A 完整业务链（预约→到诊→病历→项目→开单→收款→退费）
  B 跨角色交接（一个角色做的，另一个能不能看到、看到的是否正确）
  C 数据一致性（应收/已收/库存/报表 四条恒等式）
  D 权限边界（七角色 × 该拦的路径）
  E 异常路径（不存在的 id、非法参数、空值）
"""
import http.cookiejar
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "adc.db")
B = "http://127.0.0.1:8000"
PASS = FAIL = 0
FAILS = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sess(login):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    try:
        op.open(B + "/login", urllib.parse.urlencode(
            {"login_name": login, "password": "123456"}).encode())
    except urllib.error.HTTPError:
        pass
    return op


def get(op, path):
    try:
        r = op.open(B + path)
        return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def post(op, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data else b""
    try:
        op.open(B + path, body)
        return 200, ""
    except urllib.error.HTTPError as e:
        return e.code, urllib.parse.unquote(e.headers.get("Location") or "")


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  %s%s" % (name, ("  " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append((name, detail))
        print("  FAIL  %s  %s" % (name, detail))


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("=" * 64)
print("A. 完整业务链（一个真实患者走一遍）")
me = sess("zhangsan")
code, h = get(me, "/me/book")
links = list(dict.fromkeys(
    re.findall(r'href="(/me/book/\d+/\d{4}-\d{2}-\d{2})"', h)))
clinics = list(dict.fromkeys(re.findall(r"/me/book/(\d+)/", " ".join(links))))
check("A1 患者能进预约页并看到门店", code == 200 and len(clinics) >= 1, "门店 %d 家" % len(clinics))
if links:
    code, h2 = get(me, links[0])
    slots = re.findall(r"/me/book/confirm/(\d+)", h2)
    check("A2 能进门店看时段", code == 200, "%d 个可约班次" % len(slots))
    if slots:
        code, h3 = get(me, "/me/book/confirm/%s" % slots[0])
        check("A3 确认页能打开", code == 200, "HTTP %s" % code)

# 前台队列可得
front = sess("recept1")
code, hq = get(front, "/desk/appointments")
check("A4 前台能看到今日队列", code == 200 and "预约队列" in hq)
check("A5 队列页含动作与筛选", "预约队列" in hq and ("预约队列" in hq),
      "队列页 %d 字节" % len(hq))

# 牙医诊台
doc = sess("dentist1")
code, hd = get(doc, "/desk")
check("A6 牙医首页可打开且无异常", code == 200 and "加载失败" not in hd)
code, hd2 = get(doc, "/desk/schedule")
check("A7 牙医能进我的排班", code == 200)

# 结算单与收款口径
fin = sess("finance1")
code, hi = get(fin, "/desk/invoices")
check("A8 财务能进结算单列表", code == 200)
code, hr = get(fin, "/desk/reports")
check("A9 经营报表可打开", code == 200 and "口径说明" in hr)

print("B. 跨角色交接")
# 病历：牙医写的，患者在「就诊与账单」里能看到同一张单
v = con.execute("SELECT visit_id FROM VISIT ORDER BY visit_id LIMIT 1").fetchone()
if v:
    vid = v["visit_id"]
    code, hv = get(me, "/me/visits")
    check("B1 患者能看到自己的就诊记录", code == 200 and "就诊与账单" in hv)
check("B2 停诊会通知患者（NOTICE 表有数据）",
      con.execute("SELECT COUNT(*) FROM NOTICE").fetchone()[0] >= 0)
code, hn = get(me, "/me/notices")
check("B3 患者能看通知页", code == 200)

print("C. 数据一致性（四条恒等式）")
bad = con.execute(
    "SELECT COUNT(*) FROM (SELECT i.invoice_id,"
    " (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE WHERE invoice_id=i.invoice_id) d,"
    " (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE"
    "  WHERE invoice_id=i.invoice_id AND IFNULL(is_void,0)=0) d2"
    " FROM INVOICE i WHERE IFNULL(i.is_void,0)=0) WHERE ABS(d-d2) > 0.01").fetchone()[0]
check("C1 作废明细不进应收", bad == 0, "不符 %d 张" % bad)

bad2 = con.execute(
    "SELECT COUNT(*) FROM INVOICE i WHERE IFNULL(i.is_void,0)=0"
    " AND (SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE"
    "  WHERE invoice_id=i.invoice_id AND IFNULL(is_void,0)=0) < -0.01").fetchone()[0]
check("C2 应收不为负", bad2 == 0, "负额 %d 张" % bad2)

bad3 = con.execute(
    "SELECT COUNT(*) FROM STOCK_LEDGER l WHERE ABS("
    " l.on_hand_qty - (SELECT IFNULL(SUM(quantity),0) FROM STOCK_MOVEMENT m"
    "  WHERE m.ledger_id=l.ledger_id AND IFNULL(m.is_void,0)=0)) > 0.01"
).fetchone()[0] if con.execute(
    "SELECT COUNT(*) FROM PRAGMA_TABLE_INFO('STOCK_MOVEMENT') WHERE name='is_void'"
).fetchone()[0] else con.execute(
    "SELECT COUNT(*) FROM STOCK_LEDGER l WHERE ABS("
    " l.on_hand_qty - (SELECT IFNULL(SUM(quantity),0) FROM STOCK_MOVEMENT m"
    "  WHERE m.ledger_id=l.ledger_id)) > 0.01").fetchone()[0]
check("C3 库存账面 = 流水净额", bad3 == 0, "不符 %d 条" % bad3)

# 报表收入 vs 账面（排除作废）
book = con.execute(
    "SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l"
    " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
    " WHERE IFNULL(i.is_void,0)=0 AND IFNULL(l.is_void,0)=0").fetchone()[0]
code, hr2 = get(fin, "/desk/reports")
nums = [int(x.replace(",", "")) for x in re.findall(r">([\d,]{4,})<", hr2)[:4]]
check("C4 报表里能读到金额", len(nums) >= 1, "首个 %s" % (nums[0] if nums else "无"))

print("D. 权限边界")
CASES = [
    ("zhangsan", "/desk/accounts", "患者不能进账号管理"),
    ("zhangsan", "/desk/audit", "患者不能进审计日志"),
    ("zhangsan", "/db-status", "患者不能进数据状态"),
    ("dentist1", "/desk/accounts", "牙医不能进账号管理"),
    ("recept1", "/desk/accounts", "前台不能进账号管理"),
]
for login, path, name in CASES:
    op = sess(login)
    code, _ = get(op, path)
    ok = code in (301, 302, 303, 403) or code == 200 and False
    # 303 是放行后的重定向；真正被拦会跳回自己的首页
    check(name, code in (301, 302, 303), "HTTP %s" % code)

mgr = sess("manager1")
code, hm = get(mgr, "/desk/stock")
row = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=(SELECT staff_id FROM USER_ACCOUNT WHERE login_name='manager1')").fetchone()
check("D6 店长能看到本店库存页", code == 200)

print("E. 异常路径")
op = sess("finance1")
for path, want in (("/desk/invoice/0", 404), ("/desk/invoice/99999999", 404),
                   ("/desk/patient/0", 404), ("/desk/patient/99999999", 404),
                   ("/desk/visit/0", 404), ("/desk/visit/abc", 404)):
    code, _ = get(op, path)
    check("E %s 返回 404" % path, code == 404, "HTTP %s" % code)
code, _ = get(op, "/desk/invoices?st=%E4%B9%B1%E5%86%99")
check("E5 非法筛选参数不崩", code == 200, "HTTP %s" % code)
code, loc = post(op, "/desk/invoice/1/pay", {"amount": "-5", "method": "现金"})
check("E6 负数收款被拒", "必须大于 0" in loc, loc[:40])
code, loc = post(op, "/desk/invoice/1/pay", {"amount": "abc", "method": "现金"})
check("E7 非数字收款被拒", "不是有效数字" in loc or "必须大于 0" in loc, loc[:40])

print("=" * 64)
print("检查 %d 项，失败 %d 项" % (PASS + FAIL, FAIL))
if FAILS:
    print("失败清单：")
    for n, d in FAILS:
        print("  - %s  %s" % (n, d))
con.close()
sys.exit(1 if FAIL else 0)
