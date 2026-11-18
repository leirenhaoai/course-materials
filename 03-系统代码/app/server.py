# -*- coding: utf-8 -*-
r"""牙科连锁诊疗管理系统 —— 标准库实现，零第三方依赖。

启动：双击 run.bat，或 python app/server.py
默认 http://127.0.0.1:8000
"""
import hashlib
import hmac
import html
import json
import io
import os
import re
import secrets
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta

# 同一个「现在」：今天已结束的时段不再出现在列表里，
# 否则会出现「列表显示剩 N 位、点进去说已经过去了」。
_T = datetime.now().date().isoformat()
_HM = datetime.now().strftime("%H:%M")
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, quote

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
# 环境变量优先：ADC_DB 指定库文件、ADC_PORT 指定端口，命令行 --port 覆盖环境变量。
DB_PATH = os.environ.get("ADC_DB") or os.path.join(CODE, "data", "adc.db")
SCHEMA = os.path.join(HERE, "schema.sql")
def _argv_port(default):
    """命令行 --port NNNN 优先于 ADC_PORT。"""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            return int(argv[i + 1])
        if a.startswith("--port="):
            return int(a.split("=", 1)[1])
    return default


PORT = _argv_port(int(os.environ.get("ADC_PORT", "8000")))

ROLE_CN = {
    "patient": "患者", "receptionist": "诊所接待员", "dentist": "接诊牙医",
    "assistant": "牙医助手", "supervisor": "门店主管", "ops": "总部运营人员",
    "finance": "总部财务人员", "admin": "系统管理员",
}
DESK = {
    "patient": "patient", "receptionist": "frontdesk", "assistant": "assistant",
    "dentist": "doctor", "supervisor": "manager", "ops": "hq",
    "finance": "finance", "admin": "hq",
}
DESK_CN = {"patient": "患者", "frontdesk": "前台", "doctor": "医生",
           "assistant": "助手", "manager": "店长", "hq": "总部", "finance": "财务"}

MENU = {
    "patient": [
        ("/me", "我的首页", "home"),
        ("/me/book", "去预约", "plus"),
        ("/me/appointments", "我的预约", "cal"),
        ("/me/visits", "就诊与账单", "doc"),
    ],
    "frontdesk": [
        ("/desk", "前台账", "home"),
        ("/desk/appointments", "预约排队", "cal"),
        ("/desk/patients", "患者检索", "doc"),
    ],
    "doctor": [
        ("/desk", "我的诊台", "home"),
        ("/desk/schedule", "我的排班", "cal"),
    ],
    "manager": [
        ("/desk", "店长看板", "home"),
        ("/desk/schedule", "门店排班", "cal"),
        ("/db-status", "数据状态", "db"),
    ],
    "hq": [
        ("/desk", "总部看板", "home"),
        ("/db-status", "数据状态", "db"),
    ],
}
ICON = {
    "home": '<path d="M4 11.5 12 4l8 7.5"/><path d="M6.5 10.5V20h11v-9.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "cal": '<rect x="4" y="5.5" width="16" height="15" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
    "doc": '<path d="M7 3.5h7l4 4V20.5H7z"/><path d="M14 3.5v4h4M9.5 12h5M9.5 15.5h5"/>',
    "db": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6"/><path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3"/>',
}


# ----------------------------------------------------------------- 数据库
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():

    # data/ 目录可能还不存在（第一次运行、或者把 code 目录拷给别人），
    # 先建出来，否则 sqlite3.connect 会抛 "unable to open database file"
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    # 运行期表：站内通知。schema.sql 里也有一份，这里兜底。
    con = sqlite3.connect(DB_PATH)
    con.executescript("""CREATE TABLE IF NOT EXISTS NOTICE (
  notice_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  INTEGER,
  patient_id  INTEGER,
  kind        TEXT,
  title       TEXT,
  body        TEXT,
  ref_table   TEXT,
  ref_id      INTEGER,
  created_at  TEXT,
  read_at     TEXT,
  is_void     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS IX_NOTICE_ACCT ON NOTICE(account_id, read_at);""")
    con.commit()
    con.close()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(io.open(SCHEMA, encoding="utf-8").read())
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    con.close()
    return n


# ----------------------------------------------------------------- 口令与会话
def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 120000)
    return dk.hex(), salt


def verify_pw(pw, stored, salt):
    if not stored or not salt:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 120000)
    return hmac.compare_digest(dk.hex(), stored)


def new_session(account_id, role, guest=False):
    sid = secrets.token_urlsafe(24)
    now = datetime.now()
    con = db()
    con.execute(
        "INSERT INTO SESSION (session_id, account_id, role, is_guest, csrf_token, issued_at, expires_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (sid, account_id, role, 1 if guest else 0, secrets.token_hex(16),
         now.strftime("%Y-%m-%d %H:%M:%S"),
         (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    return sid


def load_session(sid):
    if not sid:
        return None
    con = db()
    row = con.execute("SELECT * FROM SESSION WHERE session_id = ?", (sid,)).fetchone()
    con.close()
    if not row:
        return None
    if row["expires_at"] and row["expires_at"] < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        return None
    d = dict(row)
    d["role_cn"] = ROLE_CN.get(d["role"], d["role"])
    d["desk"] = DESK.get(d["role"], "patient")
    d["desk_cn"] = DESK_CN[d["desk"]]
    d["display"] = "游客"
    d["patient_ids"] = []
    if d["account_id"]:
        con = db()
        a = con.execute("SELECT * FROM USER_ACCOUNT WHERE account_id = ?",
                        (d["account_id"],)).fetchone()
        if a:
            d["login_name"] = a["login_name"]
            d["display"] = a["login_name"]
            d["staff_id"] = a["staff_id"]
            d["dentist_id"] = a["dentist_id"]
            if d["desk"] == "patient":
                d["patient_ids"] = [r[0] for r in con.execute(
                    "SELECT patient_id FROM PATIENT WHERE account_id=?", (a["account_id"],)).fetchall()]
        con.close()
    return d


# ----------------------------------------------------------------- 样式
CSS = """

*{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
.app{max-width:100%;overflow-x:hidden}
body{margin:0;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
     background:#f4f6f8;color:#1f2937}
a{color:#1d6fd8;text-decoration:none} a:hover{text-decoration:underline}
.app{display:flex;min-height:100vh}
.side{width:212px;flex:0 0 212px;background:#14263f;color:#c8d4e4;
      display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.side .brand{padding:20px 20px 16px;color:#fff;font-weight:600;font-size:15px;
             letter-spacing:.3px;line-height:1.35}
.side .brand small{display:block;font-weight:400;font-size:11.5px;opacity:.6;
                   margin-top:3px;letter-spacing:0}
.side .who{padding:0 20px 16px;font-size:12px;color:#8fa6c4;border-bottom:1px solid #1e3554}
.side .who b{display:block;color:#fff;font-size:13.5px;font-weight:500;margin-bottom:2px}
.side nav{flex:1;padding:10px 0;overflow:auto}
.side nav a{display:flex;align-items:center;gap:10px;padding:9px 20px;font-size:13.5px;
            color:#c8d4e4;border-left:3px solid transparent}
.side nav a:hover{background:#1a3150;color:#fff;text-decoration:none}
.side nav a.on{background:#1e3554;color:#fff;border-left-color:#4f9bf0;font-weight:500}
.side nav a svg{width:17px;height:17px;flex:0 0 17px;stroke:currentColor;fill:none;
                stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;opacity:.85}
.side .foot{padding:14px 20px;border-top:1px solid #1e3554;font-size:12.5px}
.side .foot a{color:#8fa6c4}
.main{flex:1;min-width:0;padding:28px 32px 40px}
.wrap{max-width:1240px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#6b7280;font-size:13px;margin-bottom:22px}
.grid{display:grid;gap:14px}
.g3{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:18px}
.card h3{margin:0 0 6px;font-size:15px}
.card p{margin:0;color:#6b7280;font-size:13px}
.card .num{font-size:26px;font-weight:600;color:#14263f;line-height:1.2}
.card .lbl{color:#6b7280;font-size:12px;margin-bottom:8px}
.btn{display:inline-block;background:#1d6fd8;color:#fff;border:0;border-radius:7px;
      padding:9px 18px;font-size:14px;cursor:pointer;font-family:inherit}
.btn:hover{background:#1a63c2;text-decoration:none;color:#fff}
.btn.ghost{background:#fff;color:#1d6fd8;border:1px solid #c7d7ea}
.btn.ghost:hover{background:#f0f6ff;color:#1d6fd8}
.btn.sm{padding:5px 12px;font-size:13px}
.btn.danger{background:#fff;color:#b42318;border:1px solid #f0c2bd}
.btn.danger:hover{background:#fdf3f2;color:#b42318}
.login{max-width:390px;margin:9vh auto;background:#fff;border:1px solid #e5e7eb;
        border-radius:12px;padding:32px}
.login h1{font-size:19px;text-align:center;margin-bottom:2px}
.login .sub{text-align:center;margin-bottom:24px}
label{display:block;font-size:13px;color:#374151;margin:12px 0 5px}
input,select,textarea{width:100%;padding:9px 11px;border:1px solid #d1d5db;border-radius:7px;
                      font:inherit;background:#fff;font-family:inherit}
input:focus,select:focus,textarea:focus{outline:0;border-color:#1d6fd8;
                                        box-shadow:0 0 0 3px #dbe9fb}
.msg{padding:9px 12px;border-radius:7px;font-size:13px;margin-bottom:14px}
.err{background:#fdecec;color:#b42318;border:1px solid #f6c9c5}
.ok{background:#eaf7ef;color:#12683a;border:1px solid #bfe5cd}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;
       border-radius:10px;overflow:hidden}
th{background:#f9fafb;text-align:left;font-size:12px;color:#6b7280;font-weight:600;
   padding:10px 14px;border-bottom:1px solid #e5e7eb;white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid #f1f3f5;font-size:13px}
tr:last-child td{border-bottom:0}
.muted{color:#9ca3af}
.badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:9px;
       background:#eef2f7;color:#4b5563}
.badge.g{background:#eaf7ef;color:#12683a}
.badge.r{background:#fdecec;color:#b42318}
.badge.b{background:#e8f2fe;color:#1d6fd8}
.badge.y{background:#fef6e7;color:#a16207}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;
     margin-bottom:12px}
.slot{display:inline-block;border:1px solid #d1d5db;border-radius:7px;padding:7px 12px;
      margin:0 6px 6px 0;font-size:13px;background:#fff;cursor:pointer}
.slot:hover{border-color:#1d6fd8;background:#f5faff}
.slot.on{background:#1d6fd8;border-color:#1d6fd8;color:#fff}
.slot.off{opacity:.4;cursor:not-allowed;text-decoration:line-through}
.foot{text-align:center;color:#9ca3af;font-size:12px;margin:44px 0 18px}

/* 预约确认 / 取消确认 / 成功页 */
.panel{background:#fff;border:1px solid #e8eaee;border-radius:12px;
       overflow:hidden;margin-bottom:16px}
.panel .h{padding:13px 18px;font-size:14.5px;font-weight:600;
          border-bottom:1px solid #f1f2f5;background:#fbfcfd}
.panel .bd{padding:16px 18px}
.kv2{width:100%;border-collapse:collapse;font-size:14px;padding:0 18px}
.kv2 tr{border-bottom:1px solid #f4f5f7}
.kv2 tr:last-child{border-bottom:0}
.kv2 th{text-align:left;color:#6b7280;font-weight:400;width:110px;
        padding:9px 12px;vertical-align:top}
.kv2 td{padding:9px 12px}
.picks{display:grid;gap:7px;padding:4px 0}
.pick{display:flex;align-items:center;gap:10px;border:1px solid #e1e5eb;
      border-radius:9px;padding:8px 13px;cursor:pointer;background:#fff}
.pick:hover{border-color:#9db8e8;background:#f7fbff}
.pick input{margin:0;accent-color:#1d6fd8;width:16px;height:16px}
.pick span{font-size:14px;font-weight:500}
.pick em{margin-left:auto;font-style:normal;color:#9ca3af;font-size:12.5px}
.pick:has(input:checked){border-color:#1d6fd8;background:#f2f8ff;
      box-shadow:0 0 0 3px rgba(29,111,216,.08)}
label.f{display:block;margin-bottom:14px;font-size:13px;color:#4b5563}
label.f input,label.f textarea{display:block;width:100%;margin-top:6px;
      border:1px solid #d7dbe2;border-radius:8px;padding:10px 12px;
      font-size:14px;font-family:inherit;background:#fff}
label.f textarea{resize:vertical}
.btn.big{padding:11px 26px;font-size:15px;border-radius:9px}
.btn.danger-solid{background:#d64545;color:#fff;border:1px solid #d64545}
.btn.danger-solid:hover{background:#bf3b3b}
.done{max-width:560px;margin:8px auto 0;text-align:center}
.done .tick{width:56px;height:56px;line-height:54px;border-radius:50%;
      background:#eaf7ef;color:#12683a;font-size:30px;font-weight:600;
      margin:0 auto 14px}
.done h1{font-size:23px;margin-bottom:4px}
.done .no{display:inline-block;margin-top:16px;padding:11px 26px;
      background:#f2f8ff;border:1px dashed #9db8e8;border-radius:10px;
      font:600 21px/1 "Consolas","Menlo",monospace;letter-spacing:1.5px;color:#1a4d8f}
.done .tips{text-align:left;background:#fff;border:1px solid #e8eaee;
      border-radius:12px;padding:16px 20px;margin-top:22px;font-size:13.5px;color:#4b5563}
.done .tips p{margin:0 0 8px} .done .tips p:last-child{margin:0}
.done .tips b{color:#1f2937}

/* ============ 设计令牌：颜色/间距/字号只有这几种，别再随手写 ============ */
:root{
  --ink:#111827; --ink2:#4b5563; --ink3:#9ca3af;
  --line:#e5e7eb; --line2:#f1f3f6; --bg:#f5f6f8; --card:#fff;
  --brand:#1d6fd8; --brand-soft:#f2f8ff; --brand-line:#cfe0f8;
  --ok:#12683a; --ok-soft:#eaf7ef;
  --warn:#8a5a00; --warn-soft:#fff6e5; --warn-line:#f3d9a4;
  --bad:#b42318; --bad-soft:#fdf3f2; --bad-line:#f0c2bd;
  --r1:8px; --r2:12px; --r3:16px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
}
body{font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.num,.kpi b,.meter em{font-variant-numeric:tabular-nums}

/* ============ 顶栏 ============ */
.top{display:flex;align-items:center;gap:var(--s3);padding:0 0 var(--s3);
     border-bottom:1px solid var(--line);margin-bottom:var(--s4)}
.crumb{font-size:13px;color:var(--ink3)}
.crumb b{color:var(--ink2);font-weight:500}
.top .sp{flex:1}
.bell{position:relative;display:inline-flex;align-items:center;gap:6px;
      font-size:13px;color:var(--ink2);text-decoration:none;
      border:1px solid var(--line);border-radius:999px;padding:6px 12px;background:#fff}
.bell:hover{border-color:var(--brand-line);color:var(--brand)}
.bell i{font-style:normal;background:var(--bad);color:#fff;border-radius:999px;
        min-width:18px;height:18px;line-height:18px;text-align:center;font-size:11px;padding:0 5px}
.me{display:flex;align-items:center;gap:var(--s2);font-size:13px;color:var(--ink2)}
.me b{color:var(--ink);font-weight:600}
.me span{background:var(--brand-soft);color:var(--brand);border-radius:999px;padding:2px 8px;font-size:12px}

/* ============ 角色焦点条：一屏内最先看到的那几个数 ============ */
.focus{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--s3);margin-bottom:var(--s4)}
.focus .f{background:var(--card);border:1px solid var(--line);border-radius:var(--r2);
          padding:var(--s3) var(--s4)}
.focus .f .k{font-size:12.5px;color:var(--ink3);margin-bottom:6px}
.focus .f .v{font-size:26px;font-weight:600;line-height:1.1;font-variant-numeric:tabular-nums}
.focus .f .n{font-size:12px;color:var(--ink3);margin-top:6px}
.focus .f.hot{border-color:var(--bad-line);background:var(--bad-soft)}
.focus .f.hot .v{color:var(--bad)}
.focus .f.warm{border-color:var(--warn-line);background:var(--warn-soft)}
.focus .f.warm .v{color:var(--warn)}

/* ============ 待办队列：一行一件事 + 一个按钮 ============ */
.todo{background:var(--card);border:1px solid var(--line);border-radius:var(--r2);
      margin-bottom:var(--s4);overflow:hidden}
.todo .hd{display:flex;align-items:center;gap:var(--s2);padding:var(--s3) var(--s4);
          border-bottom:1px solid var(--line2);font-size:14px;font-weight:600}
.todo .hd .n{background:var(--bad);color:#fff;border-radius:999px;font-size:12px;
             min-width:20px;height:20px;line-height:20px;text-align:center;padding:0 6px}
.todo .hd .sp{flex:1}
.todo .it{display:flex;align-items:center;gap:var(--s3);padding:11px var(--s4);
          border-bottom:1px solid var(--line2);font-size:13.5px}
.todo .it:last-child{border-bottom:0}
.todo .it .t{flex:1;min-width:0}
.todo .it .t b{display:block;font-weight:500;color:var(--ink);
               overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.todo .it .t span{color:var(--ink3);font-size:12.5px}
.todo .it.hot{box-shadow:inset 3px 0 0 var(--bad)}
.todo .it.warm{box-shadow:inset 3px 0 0 var(--warn-line)}

/* ============ 进度条 / 双段条 / 条形图 ============ */
.meter{height:8px;border-radius:999px;background:var(--line2);overflow:hidden;display:flex}
.meter i{display:block;height:100%;background:var(--brand)}
.meter i.ok{background:#2f9e5f}
.meter i.warn{background:#e0a53c}
.meter i.bad{background:#d64545}
.meterrow{display:flex;align-items:center;gap:var(--s3);font-size:13px;padding:7px 0}
.meterrow .nm{width:120px;color:var(--ink2);flex:none;overflow:hidden;
              text-overflow:ellipsis;white-space:nowrap}
.meterrow .meter{flex:1}
.meterrow .vl{width:96px;text-align:right;color:var(--ink3);flex:none;
              font-variant-numeric:tabular-nums}
.bars{display:flex;flex-direction:column;gap:var(--s2)}
.bars .r{display:flex;align-items:center;gap:var(--s3);font-size:13px}
.bars .r .nm{width:96px;color:var(--ink2);flex:none;overflow:hidden;
             text-overflow:ellipsis;white-space:nowrap}
.bars .r .tr{flex:1;height:20px;background:var(--line2);border-radius:4px;position:relative}
.bars .r .tr i{position:absolute;left:0;top:0;bottom:0;background:var(--brand);
               border-radius:4px;min-width:2px}
.bars .r .vl{width:88px;text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2);flex:none}
.stack{display:flex;height:14px;border-radius:999px;overflow:hidden;background:var(--line2)}
.stack i{display:block;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:var(--s3);margin-top:var(--s2);font-size:12.5px;color:var(--ink2)}
.legend em{font-style:normal;display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px}

/* ============ 空状态：三套写法不许混用 ============ */
.empty{padding:var(--s5);text-align:center;color:var(--ink3);font-size:13.5px}
.empty .big{font-size:15px;color:var(--ink2);margin-bottom:6px}
.empty .btn{margin-top:var(--s3)}
.empty.none{background:var(--ok-soft);color:var(--ok);border-radius:var(--r2);
            padding:var(--s4);font-size:13.5px}
.empty.deny{background:#fff;border:1px dashed var(--line)}

/* ============ 导航分组 ============ */
.side nav .sec{font-size:11px;letter-spacing:.08em;color:#7c8798;
               padding:14px 12px 6px;text-transform:uppercase}
.side nav .sec:first-child{padding-top:4px}
.side nav .cnt{margin-left:auto;background:#d64545;color:#fff;border-radius:999px;
               min-width:18px;height:18px;line-height:18px;text-align:center;
               font-size:11px;padding:0 5px}

/* ============ 表格：首页密、业务中、财务细 ============ */
.tbl.dense td{padding:8px 10px}
.tbl th{font-variant-numeric:tabular-nums}
.card.pad{padding:var(--s4)}
.two{display:grid;grid-template-columns:minmax(0,1fr) 318px;gap:var(--s4);align-items:start}
@media (max-width:1100px){.two{grid-template-columns:minmax(0,1fr)}}
.focus{grid-template-columns:repeat(4,minmax(0,1fr))}
@media (max-width:900px){.focus{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:760px){
  .app{flex-direction:column}
  .side{width:auto;flex:0 0 auto;height:auto;position:static;
        flex-direction:row;align-items:stretch;padding:0}
  .side .brand{display:none}
  .side .who{padding:10px 12px;border:0;border-right:1px solid #1e3554;
             white-space:nowrap;flex:0 0 auto;font-size:11.5px}
  .side .who b{display:block;font-size:12.5px;margin:0}
  .side nav{flex:1 1 auto;display:flex;flex-direction:row;align-items:center;
            padding:6px 8px;overflow-x:auto;gap:4px}
  .side nav .sec{display:none}
  .side nav > div{display:flex;flex-direction:row;gap:4px;flex:0 0 auto}
  .side nav a{padding:7px 11px;white-space:nowrap;border-left:0;border-radius:8px;
              font-size:12.5px;gap:6px}
  .side nav a.on{border-left:0}
  .side nav a svg{width:15px;height:15px;flex:0 0 15px}
  .side .foot{border:0;padding:8px 10px;flex:0 0 auto;font-size:12px}
  .main{padding:14px 14px 40px}
  .wrap{max-width:100%}
  .top{padding:10px 14px;flex-wrap:wrap;gap:6px;position:static}
  .top .crumb{font-size:11.5px}
  .grid,.two,.g3{grid-template-columns:minmax(0,1fr)}
  .stats,.focus{grid-template-columns:repeat(2,minmax(0,1fr))}
  .card{padding:14px;border-radius:12px}
  .card .num{font-size:22px}
  h1{font-size:20px}
  .tbl{display:block;overflow-x:auto;white-space:nowrap}
  .card{overflow-x:auto}
  .stats,.focus,.grid,.two,.g3{min-width:0}
  .card{min-width:0}
  form .row,form .f{flex-direction:column;align-items:stretch}
  .footer{position:static;padding:10px 14px}
  .btn-row{flex-wrap:wrap}
}

"""


# 导航只做「视觉分组」，不动 MENU 结构：按路径查组名，查不到的落到最后一组。
# 这样 biz2/biz4 往 MENU 里 append 的一行都不用改，缺项时自动退化成扁平列表。
NAV_GROUPS = {
    "patient": [("我的", ("/me",)),
                ("预约", ("/me/book", "/me/appointments")),
                ("记录", ("/me/visits", "/me/notices"))],
    "frontdesk": [("今天", ("/desk", "/desk/appointments")),
                  ("登记", ("/desk/book", "/desk/walkin", "/desk/patients")),
                  ("回访", ("/desk/recalls",))],
    "doctor": [("诊台", ("/desk", "/desk/performance")),
               ("排班", ("/desk/schedule",)),
               ("治疗", ("/desk/plans", "/desk/materials"))],
    "assistant": [("助手台", ("/desk",)),
                  ("耗材", ("/desk/materials",)),
                  ("患者", ("/desk/patients",))],
    "manager": [("看板", ("/desk",)),
                ("排班", ("/desk/schedule",)),
                ("审批", ("/desk/leaves", "/desk/shifts", "/desk/complaints")),
                ("经营", ("/desk/performance", "/desk/license"))],
    "hq": [("看板", ("/desk",)),
           ("门店", ("/desk/clinics", "/desk/requisitions", "/desk/quality")),
           ("财务", ("/desk/invoices", "/desk/reports", "/desk/payables", "/desk/daily")),
           ("系统", ("/desk/accounts", "/desk/audit", "/db-status"))],
    "finance": [("看板", ("/desk",)),
                ("收付", ("/desk/invoices", "/desk/payables", "/desk/daily")),
                ("报表", ("/desk/reports", "/db-status"))],
}


def nav_section(desk, path):
    for name, paths in NAV_GROUPS.get(desk, []):
        if path in paths:
            return name
    return ""


def pending_count(con, sess):
    """导航铃上的待办数。只算「等我动作」的，不算「已处理」。"""
    if not sess:
        return 0
    desk = sess.get("desk")
    n = 0
    try:
        if desk == "patient":
            n = con.execute("SELECT COUNT(*) FROM NOTICE WHERE patient_id IN"
                            " (SELECT patient_id FROM PATIENT WHERE account_id=?)"
                            " AND read_at IS NULL", (sess.get("account_id"),)).fetchone()[0]
        elif desk == "manager":
            # 店长只看本店：他的审批权本来就被 same_clinic 收到本店了。
            cid = None
            if sess.get("staff_id"):
                r = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?",
                                (sess["staff_id"],)).fetchone()
                cid = r["clinic_id"] if r else None
            if cid:
                n = con.execute("SELECT COUNT(*) FROM DENTIST_LEAVE"
                                " WHERE approval_status='待审批' AND clinic_id=?"
                                " AND IFNULL(is_void,0)=0", (cid,)).fetchone()[0]
                n += con.execute("SELECT COUNT(*) FROM SHIFT_REQUEST"
                                 " WHERE request_status='待审批' AND clinic_id=?"
                                 " AND IFNULL(is_void,0)=0", (cid,)).fetchone()[0]
                n += con.execute("SELECT COUNT(*) FROM COMPLAINT"
                                 " WHERE status IN ('待处理','处理中') AND clinic_id=?"
                                 " AND IFNULL(is_void,0)=0", (cid,)).fetchone()[0]
                n += con.execute("SELECT COUNT(*) FROM QUALITY_INCIDENT"
                                 " WHERE status IN ('待处理','处理中') AND clinic_id=?"
                                 " AND IFNULL(is_void,0)=0", (cid,)).fetchone()[0]
        elif desk in ("hq", "ops", "admin"):
            n = con.execute("SELECT COUNT(*) FROM DENTIST_LEAVE WHERE approval_status='待审批'").fetchone()[0]
            n += con.execute("SELECT COUNT(*) FROM SHIFT_REQUEST WHERE request_status='待审批'").fetchone()[0]
            n += con.execute("SELECT COUNT(*) FROM COMPLAINT"
                             " WHERE status IN ('待处理','处理中')").fetchone()[0]
            n += con.execute("SELECT COUNT(*) FROM SHIFT_REQUISITION"
                             " WHERE requisition_status='待审批'").fetchone()[0]
            n += con.execute("SELECT COUNT(*) FROM QUALITY_INCIDENT"
                             " WHERE status IN ('待处理','处理中')").fetchone()[0]
        elif desk == "frontdesk":
            n = con.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE status='已到诊'"
                            " AND date(appointment_datetime)=date('now','localtime')").fetchone()[0]
        elif desk == "finance":
            # ACCOUNT_PAYABLE 没有 paid_amount 列，只有 status（未付款/部分付款/已付清）。
            n = con.execute("SELECT COUNT(*) FROM ACCOUNT_PAYABLE"
                            " WHERE IFNULL(is_void,0)=0"
                            " AND status IN ('未付款','部分付款')").fetchone()[0]
    except Exception:
        n = 0
    return n or 0


def page(title, body, sess=None, active="", flash=""):
    side, top = "", ""
    if sess:
        items = MENU.get(sess["desk"], [])
        # 按 NAV_GROUPS 分节；同节连续若干项归到一个小标题下，未匹配的落「其他」。
        groups = NAV_GROUPS.get(sess["desk"], [])
        order = []
        for name, paths in groups:
            for p in paths:
                if p not in order:
                    order.append(p)
        # 先分桶、再按固定顺序输出：未匹配的项全部归到同一个「其他」，
        # 否则 biz2/biz4 append 的条目会把分组切得七零八落。
        buckets, sec_order = {}, [n for n, _ in groups]
        for h, t, ic in items:
            sec = nav_section(sess["desk"], h) or "其他"
            buckets.setdefault(sec, []).append((h, t, ic))
        if "其他" in buckets:
            sec_order.append("其他")
        pieces = []
        for sec in sec_order:
            rows = buckets.get(sec)
            if not rows:
                continue
            pieces.append('<div class="sec">%s</div><div>' % html.escape(sec))
            for h, t, ic in rows:
                pieces.append(
                    '<a href="%s"%s><svg viewBox="0 0 24 24">%s</svg>%s</a>'
                    % (h, ' class="on"' if h == active else "", ICON.get(ic, ""), html.escape(t)))
            pieces.append("</div>")
        nav = "".join(pieces)
        # 顶栏：面包屑 + 通知铃（待办数）+ 身份
        n = 0
        try:
            _c = db()
            n = pending_count(_c, sess)
            _c.close()
        except Exception:
            n = 0
        bell_url = "/me/notices" if sess["desk"] == "patient" else "/desk"
        bell_txt = "通知" if sess["desk"] == "patient" else "待办"
        bell = ('<a class="bell" href="%s">%s%s</a>'
                % (bell_url, bell_txt, ('<i>%d</i>' % n) if n else ""))
        top = ('<div class="top"><div class="crumb">ADC 诊疗管理系统<b> / %s</b></div>'
               '<div class="sp"></div>%s<div class="me"><b>%s</b><span>%s</span></div></div>'
               ) % (html.escape(title), bell, html.escape(sess["display"]), sess["role_cn"])
        side = ('<aside class="side"><div class="brand">ADC 诊疗管理系统'
                '<small>安德鲁牙科连锁店</small></div>'
                '<div class="who"><b>%s</b>%s</div><nav>%s</nav>'
                '<div class="foot"><a href="/logout">退出登录</a></div></aside>'
                ) % (html.escape(sess["display"]), sess["role_cn"], nav)
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · ADC 诊疗管理系统</title><style>%s</style></head><body>
<div class="app">%s<div class="main"><div class="wrap">%s%s%s</div>
<div class="foot">系统分析与设计 · 安德鲁牙科连锁店诊疗管理系统</div>
</div></div></body></html>""" % (html.escape(title), CSS, side, top, flash, body)


def flash_ok(m):
    return '<div class="msg ok">%s</div>' % html.escape(m) if m else ""


def flash_err(m):
    return '<div class="msg err">%s</div>' % html.escape(m) if m else ""


# ----------------------------------------------------------------- 小组件
def stat(num, label, sub=""):
    return ('<div class="card"><div class="lbl">%s</div><div class="num">%s</div>'
            '<p style="margin-top:8px">%s</p></div>') % (
        html.escape(label), num, html.escape(sub))


# 状态色只有三种语义：红=今天不处理会出事，黄=在等某个动作，灰=不用管。
# 蓝留给「可以点」，不用来表示状态，否则患者会以为 badge 是按钮。
STATE = {
    # 绿：已完成、正常
    "已到诊": "g", "已收款": "g", "正常": "g", "已批准": "g", "已入库": "g",
    "已完成": "g", "已付清": "g", "已联系": "g", "已闭环": "g", "已处理": "g",
    # 红：需要立刻处理
    "爽约": "r", "已取消": "r", "已驳回": "r", "已作废": "r", "逾期": "r",
    "缺货": "r", "已过期": "r", "高": "r", "停诊": "r", "异常": "r",
    # 黄：在等别人
    "已预约": "y", "待就诊": "y", "待审批": "y", "待处理": "y", "处理中": "y",
    "待收款": "y", "部分收款": "y", "部分付款": "y", "待召回": "y", "未付款": "y",
    "待入库": "y", "已下单": "y", "中": "y", "90 天内": "y", "低库存": "y",
    # 灰：不用管
    "已请假": "", "已停诊": "", "未发布": "", "低": "", "已关闭": "",
}


def yuan(x):
    """千分位金额。biz.py 里也有同名逻辑，但 server 不能顶层 import biz
    （biz 顶层 `S = None`，要等 server 加载完再注入），所以这里自带一个。"""
    try:
        return "{:,.0f}".format(float(x or 0))
    except (TypeError, ValueError):
        return "0"


def badge(status):
    s = "" if status is None else str(status)
    return '<span class="badge %s">%s</span>' % (STATE.get(s, ""), html.escape(s))


def count(con, table, where="", args=()):
    sql = "SELECT COUNT(*) FROM %s" % table
    if where:
        sql += " WHERE " + where
    try:
        return con.execute(sql, args).fetchone()[0]
    except sqlite3.Error:
        return 0


def fmt_dt(s):
    return (s or "")[:16]


# ----------------------------------------------------------------- 登录 / 注册
def p_login(err="", ok=""):
    body = """<div class="login"><h1>ADC 诊疗管理系统</h1>
<p class="sub">登录后按身份进入对应工作台</p>%s%s
<form method="post" action="/login">
  <label>登录名</label><input name="login_name" autofocus required>
  <label>口令</label><input name="password" type="password" required>
  <div style="margin-top:20px"><button class="btn" style="width:100%%">登录</button></div>
</form>
<div style="text-align:center;margin-top:18px;font-size:13px;color:#6b7280">
没有账号？<a href="/register">注册</a> · <a href="/guest">以游客身份浏览</a></div>
<div style="margin-top:22px;padding-top:16px;border-top:1px solid #eef1f4;
     font-size:12px;color:#9ca3af;line-height:1.9">
演示账号（口令都是 <b>123456</b>）：<br>
<b>zhangsan</b> 患者 · <b>recept1</b> 接待员 · <b>dentist1</b> 牙医<br>
<b>manager1</b> 店长 · <b>ops1</b> 总部运营 · <b>finance1</b> 总部财务
</div></div>""" % (flash_err(err), flash_ok(ok))
    return page("登录", body)


def p_register(err=""):
    body = """<div class="login"><h1>注册</h1>
<p class="sub">患者在预约前自助注册</p>%s
<form method="post" action="/register">
  <label>登录名</label><input name="login_name" required minlength="3" maxlength="20">
  <label>口令</label><input name="password" type="password" required minlength="6">
  <label>患者姓名</label><input name="patient_name" required>
  <label>手机号</label><input name="phone" required>
  <div style="margin-top:20px"><button class="btn" style="width:100%%">注册并登录</button></div>
</form>
<div style="text-align:center;margin-top:16px;font-size:13px;color:#6b7280">
已有账号？<a href="/login">登录</a></div></div>""" % flash_err(err)
    return page("注册", body)


# ----------------------------------------------------------------- 患者端
def p_me(sess, flash=""):
    con = db()
    pids = sess["patient_ids"]
    today = datetime.now().strftime("%Y-%m-%d")
    up, visited, paid = 0, 0, 0
    rows, past = [], []
    if pids:
        q = "(" + ",".join("?" * len(pids)) + ")"
        up = con.execute("SELECT COUNT(*) FROM APPOINTMENT WHERE patient_id IN " + q +
                         " AND status='已预约' AND appointment_datetime>=?", tuple(pids) + (today,)).fetchone()[0]
        visited = con.execute("SELECT COUNT(*) FROM VISIT v JOIN APPOINTMENT a"
                              " ON v.appointment_id=a.appointment_id"
                              " WHERE a.patient_id IN " + q, pids).fetchone()[0]
        paid = con.execute("SELECT COALESCE(SUM(p.amount),0) FROM PAYMENT p"
                           " JOIN INVOICE i ON p.invoice_id=i.invoice_id"
                           " JOIN VISIT v ON i.visit_id=v.visit_id"
                           " JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
                           " WHERE a.patient_id IN " + q, pids).fetchone()[0]
        rows = con.execute(
            "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name AS pname,"
            " d.name AS dname, c.clinic_name, c.postal_address, r.slot_start, r.slot_end"
            " FROM APPOINTMENT a JOIN PATIENT p ON a.patient_id=p.patient_id"
            " JOIN ROSTER r ON a.roster_id=r.roster_id"
            " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
            " JOIN CLINIC c ON r.clinic_id=c.clinic_id"
            " WHERE a.patient_id IN " + q +
            " AND a.status='已预约' AND a.appointment_datetime>=?"
            " ORDER BY a.appointment_datetime LIMIT 5", tuple(pids) + (today,)).fetchall()
        past = con.execute(
            "SELECT a.appointment_datetime, a.status, d.name AS dname, c.clinic_name,"
            " i.invoice_no, i.status AS istatus,"
            " (SELECT COALESCE(SUM(amount),0) FROM PAYMENT WHERE invoice_id=i.invoice_id) AS paid"
            " FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id"
            " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
            " JOIN CLINIC c ON r.clinic_id=c.clinic_id"
            " LEFT JOIN VISIT v ON v.appointment_id=a.appointment_id"
            " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id"
            " WHERE a.patient_id IN " + q +
            " AND a.appointment_datetime<? ORDER BY a.appointment_datetime DESC LIMIT 6",
            tuple(pids) + (today,)).fetchall()
    con.close()

    # 下一诊的醒目提示
    nxt = ""
    if rows:
        r = rows[0]
        nxt = ('<div class="card" style="background:#f2f8ff;border-color:#cfe2fb">'
               '<div class="lbl" style="color:#1d6fd8">下一次就诊</div>'
               '<div style="font-size:19px;font-weight:600;margin:2px 0 6px">%s</div>'
               '<div style="color:#4b5563;font-size:13px">%s · %s · %s 至 %s</div></div>'
               ) % (fmt_dt(r["appointment_datetime"]), html.escape(r["clinic_name"]),
                    html.escape(r["dname"]), r["slot_start"], r["slot_end"])

    upcoming = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
        '<td>%s</td></tr>' % (
            fmt_dt(r["appointment_datetime"]), html.escape(r["clinic_name"]),
            html.escape(r["dname"]), badge(r["status"]),
            '<a class="btn sm ghost" href="/me/reschedule/%d">改约</a> '
            '<a class="btn sm danger" href="/me/cancel/%d">取消</a>'
            % (r["appointment_id"], r["appointment_id"]))
        for r in rows) or '<tr><td colspan="5" class="muted">还没有待就诊的预约</td></tr>'

    hist = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            fmt_dt(r["appointment_datetime"]), html.escape(r["clinic_name"]),
            html.escape(r["dname"]), badge(r["status"]),
            ("%s / %s 元" % (r["invoice_no"], ("%.0f" % r["paid"]))) if r["invoice_no"] else "—")
        for r in past) or '<tr><td colspan="5" class="muted">还没有就诊记录</td></tr>'

    body = """<div class="row"><h1>我的</h1>
<a class="btn" href="/me/book">＋ 去预约</a></div>
<p class="sub">预约、查档案、看账单</p>%s
<div class="grid g3" style="margin-top:14px">
  %s %s %s
</div>
%s
<h2 style="font-size:16px;margin:26px 0 10px">待就诊的预约</h2>
<table><thead><tr><th>时间</th><th>门店</th><th>牙医</th><th>状态</th><th></th></tr></thead>
<tbody>%s</tbody></table>
<h2 style="font-size:16px;margin:26px 0 10px">历史就诊</h2>
<table><thead><tr><th>时间</th><th>门店</th><th>牙医</th><th>状态</th><th>结算</th></tr></thead>
<tbody>%s</tbody></table>""" % (
        flash_ok(flash), nxt or "",
        stat(up, "待就诊", "已预约、未到诊"),
        stat(visited, "历史就诊", "累计次数"),
        stat("{:,.0f}".format(paid), "累计支付（元）", ""),
        upcoming, hist)
    return page("我的", body, sess, "/me")


def p_book(sess, cid=None, flash="", err=""):
    con = db()
    clinics = con.execute("SELECT clinic_id, clinic_name, postal_address FROM CLINIC"
                          " ORDER BY clinic_id").fetchall()
    if not clinics:
        con.close()
        return page("预约挂号", flash_err("连锁还没有门店，无法预约"), sess, "/me/book")
    if cid is None:
        cid = clinics[0]["clinic_id"]
    today = datetime.now().date()
    days = []
    for i in range(14):
        d = today + timedelta(days=i)
        n = con.execute(
            "SELECT COUNT(*) FROM ROSTER r WHERE r.clinic_id=? AND r.roster_date=?"
            " AND r.is_published=1 AND (r.is_void IS NULL OR r.is_void=0)"
            " AND r.slot_capacity > (SELECT COUNT(*) FROM APPOINTMENT a"
            "   WHERE a.roster_id=r.roster_id AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊'))"
            " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))",
            (cid, d.isoformat(), _T, _T, _HM)).fetchone()[0]
        days.append((d, n))
    con.close()

    day_btns = "".join(
        '<a class="slot%s" href="/me/book/%d/%s">%s %s<span class="muted"> %d</span></a>' % (
            " on" if d == today else "", cid, d.isoformat(),
            "%d月%d日" % (d.month, d.day), "日一二三四五六"[d.weekday()], n)
        for d, n in days)
    cl_btns = "".join(
        '<a class="slot%s" href="/me/book/%d/%s">%s</a>' % (
            " on" if c["clinic_id"] == cid else "", c["clinic_id"],
            (datetime.now().date() + timedelta(days=1)).isoformat(),
            html.escape(c["clinic_name"])) for c in clinics)

    body = """<h1>预约挂号</h1>
<p class="sub">选门店 → 选日期 → 点进日期挑时段</p>%s%s
<div class="card">
  <div class="lbl" style="margin-bottom:8px">① 门店</div>%s
  <div class="lbl" style="margin:18px 0 8px">② 日期（括号里是当天剩余可约位数）</div>%s
</div>
<div class="card" style="margin-top:16px">
  <h3>怎么约</h3>
  <p>上面选好门店，再点一个日期，会列出当天每位牙医的时段和余位，点「约这个」就成了。</p>
</div>""" % (flash_ok(flash), flash_err(err), cl_btns, day_btns)
    return page("预约挂号", body, sess, "/me/book")


def p_book_slots(sess, clinic_id, day, flash="", err=""):
    con = db()
    c = con.execute("SELECT * FROM CLINIC WHERE clinic_id=?", (clinic_id,)).fetchone()
    if not c:
        con.close()
        return page("预约挂号", flash_err("门店不存在"), sess, "/me/book")
    rows = con.execute(
        "SELECT r.roster_id, r.slot_start, r.slot_end, r.slot_capacity, d.name AS dname,"
        " (SELECT COUNT(*) FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
        "   AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')) AS used"
        " FROM ROSTER r JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE r.clinic_id=? AND r.roster_date=? AND r.is_published=1"
        " AND (r.is_void IS NULL OR r.is_void=0)"
        " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))"
        " ORDER BY r.slot_start, d.name",
        (clinic_id, day, _T, _T, _HM)).fetchall()
    con.close()
    if not rows:
        inner = '<tr><td colspan="3" class="muted">这天这家店没有排班，换一天或换一家</td></tr>'
    else:
        trs = []
        for r in rows:
            left = (r["slot_capacity"] or 0) - r["used"]
            if left <= 0:
                act = '<span class="badge r">已约满</span>'
            else:
                # 先跳到确认页，别在列表里直接下单——患者要选给谁看病、留电话、说清来意
                act = ('<a class="btn sm" href="/me/book/confirm/%d?d=%s">约这个</a>'
                       % (r["roster_id"], day))
            trs.append('<tr><td>%s — %s</td><td>%s</td><td>剩 %d 位 %s</td></tr>'
                       % (r["slot_start"], r["slot_end"], html.escape(r["dname"]), left, act))
        inner = "".join(trs)
    body = """<div class="row"><h1>%s</h1>
<a class="btn ghost" href="/me/book">换门店或日期</a></div>
<p class="sub">%s · %s</p>%s%s
<table><thead><tr><th>时段</th><th>牙医</th><th>余位</th></tr></thead>
<tbody>%s</tbody></table>""" % (
        html.escape(c["clinic_name"]), html.escape(c["postal_address"]), day,
        flash_ok(flash), flash_err(err), inner)
    return page("选时段", body, sess, "/me/book")


def _slot_info(con, rid):
    """取一个排班槽的完整信息，确认页和成功页都要用。"""
    return con.execute(
        "SELECT r.roster_id, r.roster_date, r.slot_start, r.slot_end, r.slot_capacity,"
        " r.clinic_id, c.clinic_name, c.postal_address, c.phone AS cphone,"
        " d.name AS dname, d.employee_no,"
        " (SELECT COUNT(*) FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
        "   AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')) AS used"
        " FROM ROSTER r"
        " JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " WHERE r.roster_id=?"
        " AND (r.roster_date > ? OR (r.roster_date = ? AND r.slot_end > ?))",
        (rid, _T, _T, _HM)).fetchone()


def p_book_confirm(sess, rid, err=""):
    """预约确认页：选就诊人、填联系电话、说清就诊原因，再提交。"""
    con = db()
    s = _slot_info(con, rid)
    if not s:
        con.close()
        return page("预约确认", flash_err("排班已不存在，请重选"), sess, "/me/book")
    left = (s["slot_capacity"] or 0) - s["used"]
    if left <= 0:
        con.close()
        return page("预约确认", flash_err("这个时段已约满，请换一个"), sess, "/me/book")

    mine = con.execute(
        "SELECT patient_id, patient_no, name, phone FROM PATIENT WHERE account_id=?"
        " ORDER BY patient_id", (sess["account_id"],)).fetchall()
    if not mine:
        mine = con.execute(
            "SELECT patient_id, patient_no, name, phone FROM PATIENT WHERE patient_id=?",
            (sess["patient_ids"][0],)).fetchall() if sess.get("patient_ids") else []
    con.close()

    if len(mine) == 1:
        who = ('<input type="hidden" name="patient_id" value="%d">'
               '<p class="kv">就诊人：<b>%s</b>（%s）</p>'
               % (mine[0]["patient_id"], html.escape(mine[0]["name"]),
                  html.escape(str(mine[0]["patient_no"] or ""))))
        dflt_phone = mine[0]["phone"] or ""
    elif len(mine) > 1:
        radios = []
        for i, p in enumerate(mine):
            radios.append(
                '<label class="pick"><input type="radio" name="patient_id" value="%d"%s>'
                '<span>%s</span><em>%s</em></label>'
                % (p["patient_id"], " checked" if i == 0 else "",
                   html.escape(p["name"]), html.escape(str(p["patient_no"] or ""))))
        who = ('<p style="margin:0 0 10px;color:#6b7280;font-size:13px">'
               '这个账号下有 %d 位就诊人，这次是给谁看？</p>'
               '<div class="picks">%s</div>' % (len(mine), "".join(radios)))
        dflt_phone = mine[0]["phone"] or ""
    else:
        # 账号还没挂就诊人档案（比如员工账号误入患者流程）：给个去处，不要 500
        return ('<div class="done"><div class="tick" style="background:#fff4e8;'
                'color:#b45309">!</div><h1>这个账号还没有就诊人档案</h1>'
                '<p class="sub">就诊人档案由前台建档后挂到账号下。可以先把电话留给前台，'
                '或者让前台用「散客挂号」当场建档。</p>'
                '<p style="margin-top:22px"><a class="btn" href="/me">回我的首页</a></p></div>')

    body = flash_err(err) + """
<div class="row"><h1>确认预约</h1>
<a class="btn ghost" href="/me/book/%d/%s">换个时段</a></div>
<p class="sub">核对一下，没问题再提交；提交后才会占住这个号。</p>

<div class="panel"><div class="h">这次预约</div>
<table class="kv2">
<tr><th>门店</th><td>%s</td></tr>
<tr><th>地址</th><td>%s</td></tr>
<tr><th>时间</th><td><b>%s %s — %s</b></td></tr>
<tr><th>接诊牙医</th><td>%s</td></tr>
<tr><th>余位</th><td>剩 %d 位（提交前仍可能被别人约走）</td></tr>
</table></div>

<form method="post" action="/me/book/do">
<input type="hidden" name="roster_id" value="%d">
<input type="hidden" name="date" value="%s">
<div class="panel"><div class="h">就诊人</div>%s</div>
<div class="panel"><div class="h">联系方式与来意</div>
<label class="f">联系电话
  <input name="phone" value="%s" placeholder="方便门店临时联系你，比如改约或迟到">
</label>
<label class="f">就诊原因（选填）
  <textarea name="visit_reason" rows="3" placeholder="比如：右上后牙咬合痛三天 / 要求洗牙 / 复查"></textarea>
</label>
<p class="muted" style="margin:10px 0 0">留了电话和来意，前台能提前备好东西、医生也能提前看一眼。</p>
</div>
<button class="btn big">确认预约</button>
<a class="btn ghost big" href="/me/book/%d/%s">取消，回去重选</a>
</form>""" % (
        s["clinic_id"], s["roster_date"],
        html.escape(s["clinic_name"]), html.escape(s["postal_address"] or ""),
        s["roster_date"], s["slot_start"], s["slot_end"],
        html.escape(s["dname"] or ""), left,
        rid, s["roster_date"], who,
        html.escape(dflt_phone),
        s["clinic_id"], s["roster_date"])
    return page("确认预约", body, sess, "/me/book")


def p_book_done(sess, aid):
    """预约成功页：把编号、时间、地址、要带什么一次说清。"""
    con = db()
    a = con.execute(
        "SELECT a.*, r.slot_start, r.slot_end, r.roster_date, c.clinic_name,"
        " c.postal_address, c.phone AS cphone, d.name AS dname, p.name AS pname"
        " FROM APPOINTMENT a"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " WHERE a.appointment_id=?", (aid,)).fetchone()
    con.close()
    if not a:
        return page("预约成功", flash_err("找不到这条预约"), sess, "/me/appointments")
    # 成功页里有患者姓名、门店地址、牙医，不能凭 appointment_id 就让谁都能看
    mine = set(str(x) for x in (sess or {}).get("patient_ids") or [])
    if mine and str(a["patient_id"]) not in mine and (sess or {}).get("desk") not in (
            "frontdesk", "manager", "hq", "ops", "finance", "admin"):
        return page("预约成功", flash_err("这不是您的预约"), sess, "/me")
    body = """
<div class="done">
  <div class="tick">✓</div>
  <h1>预约成功</h1>
  <p class="sub">到店报预约编号或姓名都可以</p>
  <div class="no">%s</div>
  <table class="kv2" style="margin:22px auto 0;text-align:left">
  <tr><th>就诊人</th><td>%s</td></tr>
  <tr><th>时间</th><td><b>%s %s — %s</b></td></tr>
  <tr><th>门店</th><td>%s</td></tr>
  <tr><th>地址</th><td>%s</td></tr>
  <tr><th>接诊牙医</th><td>%s</td></tr>
  <tr><th>门店电话</th><td>%s</td></tr>
  <tr><th>就诊原因</th><td>%s</td></tr>
  </table>
  <div class="tips">
    <p><b>到店前</b>　带身份证或医保卡；有既往片子、用药清单一并带来。</p>
    <p><b>临时有事</b>　提前在「我的预约」里改约或取消，别让这个号空着。</p>
    <p><b>迟到</b>　超过 15 分钟可能顺延，先打门店电话说一声。</p>
  </div>
  <div style="margin-top:22px">
    <a class="btn" href="/me/appointments">看我的预约</a>
    <a class="btn ghost" href="/me/book">再约一个</a>
  </div>
</div>""" % (
        html.escape(a["appointment_no"] or ""), html.escape(a["pname"] or ""),
        a["roster_date"], a["slot_start"], a["slot_end"],
        html.escape(a["clinic_name"] or ""), html.escape(a["postal_address"] or ""),
        html.escape(a["dname"] or ""), html.escape(a["cphone"] or ""),
        html.escape(a["visit_reason"] or "—"))
    return page("预约成功", body, sess, "/me/appointments")


CAN_CATS = ["临时有事", "身体不适", "已在别处就诊", "约错时间或门店", "其他"]


def p_cancel(sess, aid, err=""):
    """取消确认页：让患者说清为什么取消，理由要进库。"""
    con = db()
    a = con.execute(
        "SELECT a.*, r.slot_start, r.slot_end, r.roster_date, c.clinic_name,"
        " d.name AS dname, p.name AS pname FROM APPOINTMENT a"
        " LEFT JOIN ROSTER r ON a.roster_id=r.roster_id"
        " LEFT JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " LEFT JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " LEFT JOIN PATIENT p ON a.patient_id=p.patient_id"
        " WHERE a.appointment_id=?", (aid,)).fetchone()
    con.close()
    if not a or a["patient_id"] not in (sess.get("patient_ids") or []):
        return page("取消预约", flash_err("找不到这条预约"), sess, "/me/appointments")
    if (a["status"] or "") != "已预约":
        return page("取消预约", flash_err("这条预约当前状态是「%s」，不用取消" % (a["status"] or "")),
                    sess, "/me/appointments")
    opts = "".join(
        '<label class="pick"><input type="radio" name="reason" value="%s"%s><span>%s</span></label>'
        % (c, " checked" if i == 0 else "", c) for i, c in enumerate(CAN_CATS))
    body = flash_err(err) + """
<div class="row"><h1>取消预约</h1>
<a class="btn ghost" href="/me/appointments">不取消了</a></div>
<p class="sub">取消后这个号会放回去给别人，所以请说一句原因。</p>

<div class="panel"><div class="h">要取消的预约</div>
<table class="kv2">
<tr><th>预约编号</th><td>%s</td></tr>
<tr><th>就诊人</th><td>%s</td></tr>
<tr><th>时间</th><td><b>%s %s — %s</b></td></tr>
<tr><th>门店</th><td>%s</td></tr>
<tr><th>牙医</th><td>%s</td></tr>
</table></div>

<form method="post" action="/me/cancel/%d">
<div class="panel"><div class="h">取消原因</div><div class="picks">%s</div>
<label class="f" style="margin-top:14px">补充说明（选填）
  <input name="note" placeholder="比如：孩子临时发烧">
</label></div>
<button class="btn danger-solid big">确认取消</button>
<a class="btn ghost big" href="/me/reschedule/%d">改成别的时间</a>
</form>""" % (
        html.escape(a["appointment_no"] or ""), html.escape(a["pname"] or ""),
        a["roster_date"], a["slot_start"], a["slot_end"],
        html.escape(a["clinic_name"] or ""), html.escape(a["dname"] or ""),
        aid, opts, aid)
    return page("取消预约", body, sess, "/me/appointments")


def p_visits(sess):
    con = db()
    pids = sess["patient_ids"]
    q = "(" + ",".join("?" * len(pids)) + ")" if pids else "(NULL)"
    rows = con.execute(
        "SELECT v.visit_datetime, v.diagnosis, v.chief_complaint, c.clinic_name, d.name AS dname,"
        " i.invoice_no, i.status AS istatus,"
        " (SELECT COALESCE(SUM(amount),0) FROM PAYMENT WHERE invoice_id=i.invoice_id) AS paid"
        " FROM VISIT v JOIN APPOINTMENT a ON v.appointment_id=a.appointment_id"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " JOIN CLINIC c ON v.clinic_id=c.clinic_id"
        " LEFT JOIN INVOICE i ON i.visit_id=v.visit_id"
        " WHERE a.patient_id IN " + q + " ORDER BY v.visit_datetime DESC LIMIT 40",
        pids).fetchall()
    con.close()
    tr = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        fmt_dt(r["visit_datetime"]), html.escape(r["clinic_name"]),
        html.escape(r["chief_complaint"] or "—"), html.escape(r["diagnosis"] or "—"),
        ("%s / %.0f 元" % (r["invoice_no"], r["paid"])) if r["invoice_no"] else "—")
        for r in rows) or '<tr><td colspan="5" class="muted">还没有就诊记录</td></tr>'
    body = """<h1>就诊与账单</h1><p class="sub">按时间倒序，最多 40 条</p>
<table><thead><tr><th>就诊时间</th><th>门店</th><th>主诉</th><th>诊断</th><th>账单</th></tr></thead>
<tbody>%s</tbody></table>""" % tr
    return page("就诊与账单", body, sess, "/me/visits")


# ----------------------------------------------------------------- 各角色看板
def _count_c(con, table, sess, where="1=1", args=()):
    """按当前账号所属门店计数。

    APPOINTMENT / VISIT 都没有 clinic_id 列：预约挂排班、就诊挂排班或自己带 clinic_id，
    所以各表要走不同的连接。店长/前台只能看到自己店的数据，总部与财务看全连锁。
    """
    import biz as _bz
    cid = _bz.staff_clinic(sess)
    if table == "APPOINTMENT":
        sql = ("SELECT COUNT(*) FROM APPOINTMENT a JOIN ROSTER r ON a.roster_id=r.roster_id")
        w = where
        if cid is not None:
            w = "r.clinic_id=? AND " + where
            args = (cid,) + tuple(args)
    elif table == "VISIT":
        sql = "SELECT COUNT(*) FROM VISIT v"
        w = where
        if cid is not None:
            w = "v.clinic_id=? AND " + where
            args = (cid,) + tuple(args)
    else:
        sql = "SELECT COUNT(*) FROM %s" % table
        w = where
    return con.execute(sql + " WHERE " + w, tuple(args)).fetchone()[0]


def p_desk(sess):
    con = db()
    desk = sess["desk"]
    today = datetime.now().strftime("%Y-%m-%d")
    if desk == "frontdesk":
        cards = [
            stat(_count_c(con, "APPOINTMENT", sess, "date(a.appointment_datetime)=?", (today,)),
                 "本店今日预约", "含已到诊与待就诊"),
            stat(_count_c(con, "APPOINTMENT", sess, "a.status='已预约'"), "本店待就诊", ""),
            stat(_count_c(con, "VISIT", sess, "date(v.visit_datetime)=?", (today,)),
                 "本店今日就诊", "已开诊"),
            stat(count(con, "PATIENT"), "在册患者", "全连锁共享档案"),
        ]
        title, sub = "前台工作台", "接待、挂号、收款、对账"
    elif desk == "doctor":
        did = sess.get("dentist_id")
        if did:
            cards = [
                stat(count(con, "ROSTER", "dentist_id=? AND roster_date=?", (did, today)),
                     "我今日排班", "含上午与下午"),
                stat(con.execute("SELECT COUNT(*) FROM TREATMENT_ITEM i JOIN VISIT v"
                                 " ON i.visit_id=v.visit_id WHERE i.dentist_id=?"
                                 " AND date(v.visit_datetime)=?", (did, today)).fetchone()[0],
                     "我今日诊疗行", ""),
                stat(count(con, "TREATMENT_PLAN"), "在管治疗计划", "全连锁"),
            ]
        else:
            cards = [stat("—", "未关联牙医档案", "这个账号还没绑定牙医")]
        title, sub = "医生工作台", "接诊、记录治疗、开治疗计划"
    elif desk == "manager":
        cid = None
        if sess.get("staff_id"):
            s = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?",
                            (sess["staff_id"],)).fetchone()
            cid = s["clinic_id"] if s else None
        if cid:
            cards = [
                stat(count(con, "ROSTER", "clinic_id=? AND roster_date=?", (cid, today)),
                     "本店今日出诊", "牙医排班人次"),
                stat(count(con, "SHIFT_REQUEST", "clinic_id=?", (cid,)),
                     "本店调班申请", ""),
                stat(count(con, "DENTIST_LEAVE", "clinic_id=?", (cid,)),
                     "本店请假记录", ""),
                stat(count(con, "PATIENT"), "在册患者", "全连锁共享档案"),
            ]
        else:
            cards = [stat("—", "未关联门店", "这个账号还没绑定门店")]
        title, sub = "店长工作台", "排班、调班审批、门店质量"
    elif desk == "assistant":
        # 助手原来掉进 else 分支，顶着「总部工作台」的标题看门店数和结算单（验收 D2）
        cid = None
        if sess.get("staff_id"):
            s = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?",
                            (sess["staff_id"],)).fetchone()
            cid = s["clinic_id"] if s else None
        my = "clinic_id=?" if cid else "1=1"
        args = (cid,) if cid else ()
        cards = [
            stat(count(con, "APPOINTMENT", "date(appointment_datetime)=? AND " + my,
                       (today,) + args),
                 "本店今日诊次", "含待就诊与已到诊"),
            stat(count(con, "VISIT",
                       "date(visit_datetime)=? AND clinic_id=?", (today, cid)) if cid
                 else "—",
                 "本店今日就诊", "已开诊"),
            stat(con.execute(
                "SELECT COUNT(*) FROM STOCK_LEDGER l JOIN MATERIAL m ON l.material_id=m.material_id"
                " WHERE IFNULL(l.is_void,0)=0 AND l.on_hand_qty<=IFNULL(m.reorder_point,0)"
                + (" AND l.clinic_id=?" if cid else ""), args).fetchone()[0],
                 "低于补货点", "该报补了"),
            stat(count(con, "DISINFECTION_RECORD", "date(record_date)=?", (today,)),
                 "今日消毒记录", "器械与诊位"),
        ]
        title, sub = "助手工作台", "配合诊疗、领用耗材、消毒登记"
    elif desk in ("finance",):
        cards = [
            stat(yuan(con.execute(
                "SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
                " WHERE date(paid_datetime)=? AND amount>0", (today,)).fetchone()[0]),
                 "今日收款", "不含退费"),
            stat(yuan(con.execute(
                "SELECT IFNULL(SUM(amount),0) FROM PAYMENT"
                " WHERE date(paid_datetime)=? AND amount<0", (today,)).fetchone()[0]),
                 "今日退费", "负向记录"),
            stat(yuan(con.execute(
                "SELECT IFNULL(SUM(line_subtotal),0) FROM INVOICE_LINE l"
                " JOIN INVOICE i ON l.invoice_id=i.invoice_id"
                " WHERE IFNULL(i.is_void,0)=0").fetchone()[0]),
                 "累计应收", "毛收入"),
            stat(count(con, "INVOICE", "IFNULL(is_void,0)=0"), "结算单", "未作废"),
            stat(count(con, "ACCOUNT_PAYABLE", "IFNULL(is_void,0)=0"), "应付账款", "供应商"),
        ]
        cards = cards[:4]
        title, sub = "财务工作台", "收款、对账、应付、报表"
    else:
        cards = [
            stat(count(con, "CLINIC"), "门店数", "连锁在营"),
            stat(count(con, "DENTIST"), "牙医数", "在册"),
            stat(count(con, "DENTIST_QUARTER_PERFORMANCE"), "业绩记录", "按季度"),
            stat(count(con, "INVOICE"), "结算单", ""),
        ]
        title, sub = "总部工作台", "连锁经营、报表、核算"
    con.close()
    body = '<h1>%s</h1><p class="sub">%s · 当前身份：%s</p><div class="grid g3">%s</div>' % (
        title, sub, sess["role_cn"], "".join(cards))
    # 各角色真正要看的清单（本店今日预约、待审批、未结清结算单……）由 biz 提供，
    # 这里延迟 import：biz 顶层有 S = None，运行时 server 已完全加载。
    try:
        import biz
        body += biz.desk_extra(sess)
    except Exception as e:
        body += '<div class="msg err">看板清单加载失败：%s</div>' % html.escape(repr(e))
    return page(title, body, sess, "/desk")


def p_queue(sess):
    con = db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = con.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, p.name AS pname,"
        " p.phone, d.name AS dname, c.clinic_name"
        " FROM APPOINTMENT a JOIN PATIENT p ON a.patient_id=p.patient_id"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " WHERE date(a.appointment_datetime)=? ORDER BY a.appointment_datetime", (today,)).fetchall()
    con.close()
    tr = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        fmt_dt(r["appointment_datetime"]), html.escape(r["pname"]),
        html.escape(r["phone"] or "—"), html.escape(r["clinic_name"]),
        html.escape(r["dname"]), badge(r["status"])) for r in rows)
    body = ('<h1>今日预约排队</h1><p class="sub">%s · 共 %d 条</p>'
            '<table><thead><tr><th>时间</th><th>患者</th><th>手机</th>'
            '<th>门店</th><th>牙医</th><th>状态</th></tr></thead><tbody>%s</tbody></table>'
            ) % (today, len(rows), tr or '<tr><td colspan="6" class="muted">今天没有预约</td></tr>')
    return page("预约排队", body, sess, "/desk/appointments")




def p_schedule(sess):
    con = db()
    t0 = datetime.now().strftime("%Y-%m-%d")
    t1 = (datetime.now().date() + timedelta(days=7)).isoformat()
    did = sess.get("dentist_id")
    cond, args = "(r.roster_date>=? AND r.roster_date<=?)", (t0, t1)
    my_cid = None
    if did:
        cond += " AND r.dentist_id=?"
        args = args + (did,)
    elif sess["desk"] == "manager" and sess.get("staff_id"):
        s2 = con.execute("SELECT clinic_id FROM STAFF WHERE staff_id=?",
                         (sess["staff_id"],)).fetchone()
        if s2:
            my_cid = s2["clinic_id"]
            cond += " AND r.clinic_id=?"
            args = args + (my_cid,)
    rows = con.execute(
        "SELECT r.roster_id, r.roster_date, r.slot_start, r.slot_end, r.slot_capacity,"
        " r.is_void, r.void_reason, r.is_published,"
        " d.name AS dname, c.clinic_name,"
        " (SELECT COUNT(*) FROM APPOINTMENT a WHERE a.roster_id=r.roster_id"
        "   AND IFNULL(a.is_void,0)=0 AND a.status IN ('已预约','已到诊')) AS used FROM ROSTER r"
        " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " JOIN CLINIC c ON r.clinic_id=c.clinic_id WHERE " + cond +
        " ORDER BY r.roster_date, r.slot_start, d.name LIMIT 200", args).fetchall()
    can_edit = sess["desk"] in ("manager", "hq", "ops", "admin")
    tr = []
    for r in rows:
        void = bool(r["is_void"])
        pub = "" if r["is_published"] else ' <span class="badge">未发布</span>'
        if void:
            state = '<span class="badge" title="%s">已停诊</span>' % html.escape(r["void_reason"] or "")
            act = ""
            if can_edit:
                act = ('<form method="post" action="/desk/schedule/%d/resume" style="margin:0">'
                       '<button class="btn ghost sm">恢复出诊</button></form>' % r["roster_id"])
        else:
            state = "正常" + pub
            act = ""
            if can_edit:
                act = ('<form method="post" action="/desk/schedule/%d/stop" style="margin:0">'
                       '<button class="btn ghost sm">停诊</button></form>' % r["roster_id"])
        cap = "%d/%d" % (r["used"], r["slot_capacity"])
        if can_edit and not void:
            cap = ('%d/%d <form method="post" action="/desk/schedule/%d/cap"'
                   ' style="display:inline;margin-left:6px">'
                   '<input name="cap" type="number" value="%d" min="1" max="40"'
                   ' style="width:56px;padding:2px 4px">'
                   '<button class="btn ghost sm">改</button></form>'
                   % (r["used"], r["slot_capacity"], r["roster_id"], r["slot_capacity"]))
        tr.append("<tr><td>%s</td><td>%s—%s</td><td>%s</td><td>%s</td>"
                  "<td>%s</td><td>%s</td><td>%s</td></tr>" % (
                      r["roster_date"], r["slot_start"], r["slot_end"],
                      html.escape(r["clinic_name"]), html.escape(r["dname"]),
                      cap, state, act))
    tr = "".join(tr)
    newform = ""
    if can_edit:
        docs = con.execute(
            "SELECT dentist_id, name FROM DENTIST WHERE IFNULL(active,1)=1 ORDER BY name"
        ).fetchall()
        clis = con.execute("SELECT clinic_id, clinic_name FROM CLINIC").fetchall()
        newform = (
            '<div class="panel"><div class="h">新建排班</div><div class="bd">'
            '<form method="post" action="/desk/schedule/new" class="f2">'
            '<label class="f">门店<select name="clinic_id">%s</select></label>'
            '<label class="f">牙医<select name="dentist_id">%s</select></label>'
            '<label class="f">日期<input type="date" name="roster_date" min="%s" required></label>'
            '<label class="f">开始<input type="time" name="slot_start" value="09:00" required></label>'
            '<label class="f">结束<input type="time" name="slot_end" value="12:00" required></label>'
            '<label class="f">容量<input type="number" name="slot_capacity" value="6" min="1" max="40"></label>'
            '<button class="btn">建这个班</button></form></div></div>'
            % (t0, "".join('<option value="%d">%s</option>' % (c["clinic_id"], html.escape(c["clinic_name"]))
                       for c in clis),
               "".join('<option value="%d">%s</option>' % (d["dentist_id"], html.escape(d["name"]))
                       for d in docs)))
    con.close()
    body = ("<h1>排班</h1><p class=\"sub\">%s 起 7 天。满了可以加容量，临时停诊点「停诊」，"
            "停掉后这个时段患者看不到、也约不上。</p>"
            "<table class=\"tbl\"><thead><tr><th>日期</th><th>时段</th><th>门店</th>"
            "<th>牙医</th><th>已约 / 容量</th><th>状态</th><th></th></tr></thead><tbody>%s</tbody></table>%s"
            ) % (t0, tr or "<tr><td colspan=7 class=muted>这 7 天没有排班</td></tr>", newform)
    return page("排班", body, sess, "/desk/schedule")


def p_db_status(sess):
    con = db()
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    data, total = [], 0
    for r in rows:
        t = r["name"]
        if t.startswith("sqlite_"):
            continue
        n = count(con, t)
        total += n
        data.append((t, n))
    con.close()
    tr = "".join('<tr><td>%s</td><td style="text-align:right">%d</td></tr>' % (html.escape(t), n)
                 for t, n in data)
    body = ('<h1>数据状态</h1><p class="sub">共 %d 张表、%d 行数据</p>'
            '<table><thead><tr><th>表名</th><th style="text-align:right">行数</th></tr></thead>'
            '<tbody>%s</tbody></table>') % (len(data), total, tr)
    return page("数据状态", body, sess, "/db-status")


def p_guest(sess):
    con = db()
    body = """<h1>游客浏览</h1>
<p class="sub">你没有登录，只能看公开信息。要预约请先注册或登录。</p>
<div class="grid g3">%s%s
<div class="card"><div class="lbl">下一步</div>
<p style="margin-bottom:12px">登录后才能预约、看就诊记录和账单。</p>
<a class="btn" href="/login">去登录</a>
<a class="btn ghost" href="/register" style="margin-left:8px">注册</a></div></div>""" % (
        stat(count(con, "CLINIC"), "连锁门店", "覆盖城市的门店数"),
        stat(count(con, "DENTIST"), "在册牙医", "含全职与兼职"))
    con.close()
    return page("游客浏览", body, sess)


# ----------------------------------------------------------------- 路由
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


# 后台路径的角色白名单。键是路径前缀（最长匹配优先），值是允许进入的角色。
# 不在表里的 /desk/* 页面，除患者外都可进；患者一律被挡——之前只判「登录了没有」，
# 结果患者登录后能打开账单、账号、审计、61 位患者手机号和别人的病历（验收报告 A7）。
ROLE_PAGES = [
    ("/desk/accounts", ("ops", "admin")),
    ("/desk/audit", ("ops", "admin")),
    ("/desk/clinics", ("ops", "admin", "supervisor")),
    ("/desk/requisitions", ("ops", "admin")),
    ("/desk/quality", ("ops", "admin", "supervisor")),
    ("/desk/leaves", ("supervisor", "ops", "admin")),
    ("/desk/shifts", ("supervisor", "ops", "admin")),
    ("/desk/complaints", ("supervisor", "ops", "admin")),
    ("/desk/materials", ("assistant", "dentist", "supervisor", "ops", "admin")),
    ("/desk/reports", ("ops", "admin", "finance", "supervisor")),
    ("/db-status", ("ops", "admin", "finance")),
]


def path_allowed(path, sess):
    """返回 (是否放行, 被挡时应跳去的位置)。"""
    role = (sess or {}).get("role") or ""
    if path.startswith("/desk") or path.startswith("/db-status"):
        if not sess:
            return False, "/login"
        if role == "patient":
            return False, "/me"
        best, allow = None, None
        for pre, roles in ROLE_PAGES:
            if path.startswith(pre) and (best is None or len(pre) > len(best)):
                best, allow = pre, roles
        if allow is not None and role not in allow:
            return False, "/desk"
        return True, ""
    return True, ""


def qs(sess):
    """从 sess["_path"] 里解 GET 的 query。

    dispatch 在调用处理函数前会把原始 URL 塞进 sess["_path"]，
    页面/接口函数拿不到 handler，只能这么拿。
    """
    raw = (sess or {}).get("_path") or ""
    return {k: v[0] for k, v in parse_qs(urlparse(raw).query).items()}


class Handler(BaseHTTPRequestHandler):
    server_version = "ADC/0.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        line = "%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args)
        sys.stderr.write(line)
        # 同时落一份到文件：后台运行时 stderr 是管道，管道写满会阻塞，
        # 排查期间文件日志比 stderr 可靠。
        try:
            with open(os.path.join(HERE, "server.log"), "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        except Exception:
            pass

    def cookie_sid(self):
        raw = self.headers.get("Cookie", "")
        if not raw:
            return None
        c = SimpleCookie()
        try:
            c.load(raw)
        except Exception:
            return None
        return c["sid"].value if "sid" in c else None

    def token_sid(self):
        """小程序没有 Cookie，用 Authorization: Bearer <sid> 携带会话。"""
        raw = self.headers.get("Authorization") or ""
        if raw.lower().startswith("bearer "):
            return raw[7:].strip() or None
        return None

    def json(self, data, code=200):
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def send(self, code, body, cookie=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def form(self):
        """同时接受表单与 JSON。

        网页端发的是 application/x-www-form-urlencoded；小程序的 wx.request
        默认 application/json，早先只走 parse_qs 时小程序所有 POST 都拿到空 dict。
        """
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else ""
        if not raw:
            return {}
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype or raw.lstrip()[:1] in "{[":
            try:
                d = json.loads(raw)
            except ValueError:
                return {}
            if isinstance(d, dict):
                return {k: ("" if v is None else v) for k, v in d.items()}
            return {}
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def redirect(self, loc, cookie=None):
        # HTTP 头只能 latin-1，带中文的 query（?ok=预约成功）必须先百分号编码，
        # 否则 send_header 直接抛 UnicodeEncodeError，浏览器看到 500。
        try:
            loc.encode("latin-1")
        except UnicodeEncodeError:
            loc = quote(loc, safe="/?=&%#:,;!~*'()+\\$@")
        self.send_response(303)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def do_GET(self):
        try:
            self.dispatch("GET")
        except BaseException:
            self._boom()

    def do_POST(self):
        try:
            self.dispatch("POST")
        except BaseException:
            self._boom()

    def _boom(self):
        tb = traceback.format_exc()
        try:
            with open(os.path.join(HERE, "server.log"), "a", encoding="utf-8") as f:
                f.write("\n===== 未捕获异常 %s %s =====\n%s\n"
                        % (getattr(self, "command", "?"), getattr(self, "path", "?"), tb))
        except Exception:
            pass
        sys.stderr.write(tb)

    def dispatch(self, method):
        try:
            u = urlparse(self.path)
            path = u.path
            sess = load_session(self.cookie_sid() or self.token_sid())
            if path.startswith("/api/"):
                # 接口自己判权限；未登录统一回 401 JSON，别跳 HTML 登录页（小程序解析不了）。
                for m, rx, fn in ROUTES:
                    if m != method:
                        continue
                    mo = rx.match(path)
                    if mo:
                        if sess is not None:
                            sess["_path"] = self.path
                        return fn(self, sess, *mo.groups())
                return self.json({"ok": False, "err": "接口不存在"}, 404)
            ok, back = path_allowed(path, sess)
            if not ok:
                return self.redirect(back + ("?err=这个页面需要更高的权限" if back.startswith("/desk") else ""))
            for m, rx, fn in ROUTES:
                if m != method:
                    continue
                mo = rx.match(path)
                if mo:
                    if sess is not None:
                        sess["_path"] = self.path
                    return fn(self, sess, *mo.groups())
            self.send(404, page("页面不存在",
                                '<h1>404</h1><p class="sub">没有这个页面：%s</p>'
                                '<a class="btn" href="/">回首页</a>' % html.escape(path), sess))
        except Exception:
            tb = traceback.format_exc()
            sys.stderr.write(tb)
            self.send(500, page("服务器错误",
                                '<h1>500</h1><pre style="font-size:12px;white-space:pre-wrap">%s</pre>'
                                % html.escape(tb[-2000:])))


SID = "sid=%s; Path=/; HttpOnly; SameSite=Lax"


# ----------------------------------------------------------------- 路由实现
@route("GET", "/")
def r_index(h, sess):
    return h.redirect("/desk" if sess and sess["desk"] != "patient" else
                      ("/me" if sess else "/login"))


@route("GET", "/login")
def r_login_form(h, sess):
    if sess:
        return h.redirect("/desk")
    q = parse_qs(urlparse(h.path).query)
    return h.send(200, p_login(ok=(q.get("ok") or [""])[0]))


@route("POST", "/login")
def r_login(h, sess):
    f = h.form()
    name = (f.get("login_name") or "").strip()
    pw = f.get("password") or ""
    con = db()
    a = con.execute("SELECT * FROM USER_ACCOUNT WHERE login_name = ?", (name,)).fetchone()
    if not a:
        con.close()
        return h.send(200, p_login("登录名或口令不对"))
    if a["account_status"] not in (None, "", "正常", "在职"):
        con.close()
        return h.send(200, p_login("这个账号已停用"))
    if not verify_pw(pw, a["password_hash"], a["password_salt"]):
        con.close()
        return h.send(200, p_login("登录名或口令不对"))
    con.execute("UPDATE USER_ACCOUNT SET last_login_at=? WHERE account_id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), a["account_id"]))
    con.commit()
    con.close()
    sid = new_session(a["account_id"], a["role"] or "patient")
    desk = DESK.get(a["role"] or "patient", "patient")
    dest = "/me" if desk == "patient" else "/desk"
    return h.redirect(dest, cookie=SID % sid)


@route("GET", "/register")
def r_reg_form(h, sess):
    return h.send(200, p_register())


@route("POST", "/register")
def r_register(h, sess):
    f = h.form()
    name = (f.get("login_name") or "").strip()
    pw = f.get("password") or ""
    pname = (f.get("patient_name") or "").strip()
    phone = (f.get("phone") or "").strip()
    if len(name) < 3 or len(pw) < 6:
        return h.send(200, p_register("登录名至少 3 位、口令至少 6 位"))
    con = db()
    if con.execute("SELECT 1 FROM USER_ACCOUNT WHERE login_name = ?", (name,)).fetchone():
        con.close()
        return h.send(200, p_register("这个登录名已被占用"))
    ph, salt = hash_pw(pw)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = con.execute(
        "INSERT INTO USER_ACCOUNT (login_name, password_hash, password_salt, role,"
        " account_status, registered_at) VALUES (?,?,?,?,?,?)",
        (name, ph, salt, "patient", "正常", now))
    aid = cur.lastrowid
    pcur = con.execute(
        "INSERT INTO PATIENT (patient_no, name, phone, source_channel, first_visit_date,"
        " account_id) VALUES (?,?,?,?,?,?)",
        (int(time.time()) % 1000000, pname, phone, "小程序", now[:10], aid))
    con.commit()
    con.close()
    # 自助注册直接改 PATIENT 档案，必须留痕（谁、什么时候、从哪个渠道建的）
    import biz as _bz
    _bz.audit(sess, "PATIENT", pcur.lastrowid, "insert", None,
              "%s/%s/小程序" % (pname, phone))
    return h.redirect("/me", cookie=SID % new_session(aid, "patient"))


@route("GET", "/guest")
def r_guest(h, sess):
    # 已登录的人点「以游客身份浏览」不该被顶成游客：员工一点就掉线。
    if sess:
        return h.redirect("/guest/home")
    return h.redirect("/guest/home", cookie=SID % new_session(None, "patient", guest=True))


@route("GET", "/guest/home")
def r_guest_home(h, sess):
    return h.send(200, p_guest(sess))


@route("GET", "/logout")
def r_logout(h, sess):
    if sess:
        con = db()
        con.execute("DELETE FROM SESSION WHERE session_id = ?", (sess["session_id"],))
        con.commit()
        con.close()
    return h.redirect("/login", cookie="sid=; Path=/; Max-Age=0")


@route("GET", "/me")
def r_me(h, sess):
    if not sess:
        return h.redirect("/login")
    q = parse_qs(urlparse(h.path).query)
    return h.send(200, p_me(sess, (q.get("ok") or [""])[0]))


@route("GET", "/me/book")
def r_book(h, sess):
    if not sess:
        return h.redirect("/login")
    q = parse_qs(urlparse(h.path).query)
    c = (q.get("c") or [None])[0]
    return h.send(200, p_book(sess, int(c) if c and c.isdigit() else None))


@route("GET", "/me/book/(\\d+)/(\\d{4}-\\d{2}-\\d{2})")
def r_book_slots(h, sess, cid, day):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_book_slots(sess, int(cid), day))


@route("GET", "/me/book/confirm/(\\d+)")
def r_book_confirm(h, sess, rid):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_book_confirm(sess, int(rid)))


@route("GET", "/me/book/done/(\\d+)")
def r_book_done(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_book_done(sess, int(aid)))


@route("POST", "/me/book/do")
def r_book_do(h, sess):
    if not sess:
        return h.redirect("/login")
    f = h.form()
    rid = f.get("roster_id") or ""
    day = f.get("date") or ""
    phone = (f.get("phone") or "").strip()[:20]
    reason = (f.get("visit_reason") or "").strip()[:200]
    pid_raw = (f.get("patient_id") or "").strip()
    if not pid_raw.isdigit():
        pid_raw = str(sess["patient_ids"][0]) if sess.get("patient_ids") else ""
    if not rid.isdigit() or not pid_raw.isdigit():
        return h.redirect("/me/book")
    pid = int(pid_raw)
    if pid not in (sess.get("patient_ids") or []):
        return h.send(200, p_book_confirm(sess, int(rid), err="就诊人不是你的档案"))
    con = db()
    r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (int(rid),)).fetchone()
    if not r:
        con.close()
        return h.send(200, p_book_confirm(sess, int(rid), err="排班不存在"))
    used = con.execute(
        "SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=?"
        " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')", (int(rid),)).fetchone()[0]
    if used >= (r["slot_capacity"] or 0):
        con.close()
        return h.send(200, p_book_confirm(sess, int(rid), err="这个时段刚被约满，换一个"))
    # 排班必须「没停诊、已发布」，否则患者能约到一个根本不会出诊的号
    if (r["is_void"] or 0) == 1:
        con.close()
        return h.send(200, p_book_confirm(sess, int(rid),
                                          err="这个时段已经停诊，换一个"))
    if (r["is_published"] or 0) == 0:
        con.close()
        return h.send(200, p_book_confirm(sess, int(rid),
                                          err="这个时段还没开放，换一个"))
    dt = "%s %s:00" % (r["roster_date"], r["slot_start"])
    # 过去的时段不能约
    if dt < datetime.now().strftime("%Y-%m-%d %H:%M:%S"):
        con.close()
        return h.send(200, p_book_confirm(sess, int(rid),
                                          err="这个时段已经过去了，换一个"))
    # 同一个人在同一位医生这个时段只能占一个号。
    # 唯一索引 UX_APPT_ACTIVE 是最后一道兜底，这里先查一遍好给准话。
    dup = con.execute(
        "SELECT COUNT(*) FROM APPOINTMENT WHERE patient_id=? AND roster_id=?"
        " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')",
        (pid, int(rid))).fetchone()[0]
    if dup:
        con.close()
        return h.send(200, p_book_confirm(
            sess, int(rid), err="这位就诊人已经约了这个时段了，不用重复约"))
    # 预约编号用「A + 日期 + 当日序号」：患者打电话改约时报这串就够，前台不用翻表。
    # 序号取 MAX+1 并循环避让，不能用 COUNT+1——删过数据就会撞号。
    today8 = (r["roster_date"] or "").replace("-", "")
    mx = con.execute("SELECT IFNULL(MAX(CAST(SUBSTR(appointment_no, 10) AS INTEGER)), 0)"
                     " FROM APPOINTMENT WHERE appointment_no LIKE ?",
                     ("A" + today8 + "%",)).fetchone()[0]
    seq = int(mx)
    while True:
        seq += 1
        no = "A%s%04d" % (today8, seq)
        if not con.execute("SELECT 1 FROM APPOINTMENT WHERE appointment_no=?",
                           (no,)).fetchone():
            break
    con.execute(
        "INSERT INTO APPOINTMENT (appointment_no, patient_id, roster_id,"
        " appointment_datetime, status, visit_reason) VALUES (?,?,?,?,?,?)",
        (no, pid, int(rid), dt, "已预约", reason or None))
    aid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    import biz as _bz
    _bz.audit(sess, "APPOINTMENT", aid, "status", "", "已预约",
              patient_id=pid, con=con)
    if phone:
        con.execute("UPDATE PATIENT SET phone=? WHERE patient_id=? AND"
                    " (phone IS NULL OR phone='')", (phone, pid))
    con.commit()
    con.close()
    return h.redirect("/me/book/done/%d" % aid)


@route("GET", "/me/cancel/(\\d+)")
def r_cancel_form(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_cancel(sess, int(aid)))


@route("POST", "/me/cancel/(\\d+)")
def r_cancel(h, sess, aid):
    if not sess:
        return h.redirect("/login")
    f = h.form()
    reason = (f.get("reason") or "患者原因").strip()[:20]
    note = (f.get("note") or "").strip()[:100]
    aid = int(aid)
    con = db()
    a = con.execute("SELECT * FROM APPOINTMENT WHERE appointment_id=?", (aid,)).fetchone()
    if not a or a["patient_id"] not in (sess.get("patient_ids") or []):
        con.close()
        return h.redirect("/me/appointments?err=这条预约不在你的名下")
    # 只有「已预约」能取消：已到诊的要退号得走前台退费，不能自己把就诊记录取消掉
    if (a["status"] or "已预约") != "已预约" or (a["is_void"] or 0) == 1:
        con.close()
        return h.redirect("/me/appointments?err=" + quote(
            "这条预约已经是「%s」，不能再取消" % (a["status"] or "已作废")))
    full = reason if not note else "%s：%s" % (reason, note)
    cur = con.execute(
        # 取消只是状态流转，不是作废：is_void 留给「撤销 / 重复数据清理」。
        # 前台取消（r_desk_cancel）不置 is_void，两边口径要一致。
        "UPDATE APPOINTMENT SET status='已取消', cancellation_category=?,"
        " void_reason=?, void_at=?, void_account_id=?"
        " WHERE appointment_id=? AND status='已预约' AND IFNULL(is_void,0)=0",
        (reason, full, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         sess.get("account_id"), aid))
    ok = cur.rowcount == 1
    if ok:
        import biz as _bz
        _bz.audit(sess, "APPOINTMENT", aid, "status", "已预约", "已取消",
                  con=con)
    con.commit()
    con.close()
    if not ok:
        return h.redirect("/me/appointments?err=这条预约刚被改过，刷新再看")
    return h.redirect("/me/appointments?ok=已取消")


@route("GET", "/me/appointments")
def r_my_appt(h, sess):
    if not sess:
        return h.redirect("/login")
    con = db()
    pids = sess["patient_ids"]
    q = "(" + ",".join("?" * len(pids)) + ")" if pids else "(NULL)"
    rows = con.execute(
        "SELECT a.appointment_id, a.appointment_datetime, a.status, d.name AS dname,"
        " a.cancellation_category, a.void_reason,"
        " c.clinic_name, r.slot_start, r.slot_end FROM APPOINTMENT a"
        " JOIN ROSTER r ON a.roster_id=r.roster_id"
        " JOIN DENTIST d ON r.dentist_id=d.dentist_id"
        " JOIN CLINIC c ON r.clinic_id=c.clinic_id"
        " WHERE a.patient_id IN " + q + " ORDER BY a.appointment_datetime DESC LIMIT 60",
        pids).fetchall()
    con.close()
    def why(r):
        """把库里的取消原因翻成人话——患者不该只看到「已取消」两个字。"""
        cat = (r["cancellation_category"] or "").strip()
        note = (r["void_reason"] or "").strip()
        if not cat and not note:
            return ""
        if cat == "医生停诊":
            return "牙医临时停诊，门店会电话联系改约"
        if cat == "门店原因":
            return "门店原因取消" + ("（%s）" % note if note and note != cat else "")
        if cat == "患者未到":
            return "未按时到店"
        if cat.startswith("时间冲突"):
            return "时间冲突，"
        if note.startswith(cat + "："):
            return note.split("：", 1)[1]
        return note or cat

    def ops(r):
        st = r["status"]
        aid = r["appointment_id"]
        if st == "已预约":
            return ('<a class="btn sm ghost" href="/me/reschedule/%d">改约</a> '
                    '<a class="btn sm danger" href="/me/cancel/%d">取消</a>' % (aid, aid))
        if st == "已取消":
            # 取消后还能不能重约，取决于这个日期有没有过去
            return '<a class="btn sm" href="/me/book">重新预约</a>'
        if st == "爽约":
            return ('<span class="muted" style="margin-right:8px">没等到您</span>'
                    '<a class="btn sm" href="/me/book">重新预约</a>')
        return ""

    tr = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        fmt_dt(r["appointment_datetime"]), html.escape(r["clinic_name"]),
        html.escape(r["dname"]), badge(r["status"]),
        '<span class="muted">%s</span>' % html.escape(why(r)) if why(r) else "—",
        ops(r))
        for r in rows) or '<tr><td colspan="6" class="muted">还没有预约</td></tr>'
    body = ('<div class="row"><h1>我的预约</h1><a class="btn" href="/me/book">＋ 去预约</a></div>'
            '<p class="sub">全部预约记录。被取消的会写明原因，可以直接重新预约。</p>'
            '<table><thead><tr><th>时间</th><th>门店</th><th>牙医</th><th>状态</th>'
            '<th>说明</th><th></th></tr></thead><tbody>%s</tbody></table>') % tr
    return h.send(200, page("我的预约", body, sess, "/me/appointments"))


@route("GET", "/me/visits")
def r_my_visits(h, sess):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_visits(sess))


@route("GET", "/desk")
def r_desk(h, sess):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_desk(sess))


# /desk/appointments 由 biz.py 的 r_queue2 接管（带「登记到诊」操作列）；
# 这里不再注册，否则会与 biz 的同名路由打架、把操作列覆盖掉。


# 患者检索页在 biz.py（r_patients2）：那份带搜索框。这里原先还有一份，
# 注册顺序靠后会被覆盖，已删以免以后误改这一份。


@route("GET", "/desk/schedule")
def r_schedule(h, sess):
    if not sess:
        return h.redirect("/login")
    return h.send(200, p_schedule(sess))


@route("POST", "/desk/schedule/(\\d+)/stop")
def r_roster_stop(h, sess, rid):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk/schedule?err=只有店长及以上可以停诊")
    import biz as _bz
    con = db()
    # 整段包 try/finally：中途任何异常都不能让连接带着写事务跑掉，
    # 否则 SQLite 单写者模型下全站写操作都会 database is locked。
    try:
        r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (int(rid),)).fetchone()
        if not r:
            return h.redirect("/desk/schedule?err=排班不存在")
        if not _bz.same_clinic(sess, cid=r["clinic_id"]):
            return h.redirect("/desk/schedule?err=只能停本店的班")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute("UPDATE ROSTER SET is_void=1, void_reason=?, void_at=?, void_account_id=?"
                    " WHERE roster_id=?", ("门店手动停诊", now,
                                           sess.get("account_id"), int(rid)))
        # 已约的患者一并取消，否则患者白跑一趟
        aff = con.execute("SELECT appointment_id, roster_id FROM APPOINTMENT"
                          " WHERE roster_id=? AND IFNULL(is_void,0)=0 AND status='已预约'",
                          (int(rid),)).fetchall()
        for a in aff:
            con.execute("UPDATE APPOINTMENT SET status='已取消',"
                        " cancellation_category='医生停诊', void_reason=?, void_at=?,"
                        " void_account_id=? WHERE appointment_id=?",
                        ("排班停诊，系统自动取消", now, sess.get("account_id"),
                         a["appointment_id"]))
        con.commit()
        # 通知在同一条连接里接着写（此时已 commit，事务是干净的）
        sent = 0
        for a in aff:
            if _bz._notify_stop(con, a["appointment_id"], r["roster_date"],
                                r["slot_start"], r["roster_date"], r["slot_end"]):
                sent += 1
        _bz.audit(sess, "ROSTER", int(rid), "is_void", "0", "1", con=con)
        con.commit()
        return h.redirect("/desk/schedule?ok=已停诊，取消 %d 条预约，发出 %d 条通知"
                          % (len(aff), sent))
    except Exception as e:  # noqa: BLE001
        try:
            con.rollback()
        except Exception:  # noqa: BLE001
            pass
        return h.redirect("/desk/schedule?err=停诊失败：%s"
                          % str(e).split(":")[-1].strip()[:50])
    finally:
        con.close()


@route("POST", "/desk/schedule/(\\d+)/resume")
def r_roster_resume(h, sess, rid):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk/schedule?err=没有权限")
    con = db()
    r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (int(rid),)).fetchone()
    if not r:
        con.close()
        return h.redirect("/desk/schedule?err=排班不存在")
    import biz as _bz
    if not _bz.same_clinic(sess, cid=r["clinic_id"]):
        con.close()
        return h.redirect("/desk/schedule?err=只能恢复本店的班")
    con.execute("UPDATE ROSTER SET is_void=0, void_reason=NULL, void_at=NULL,"
                " void_account_id=NULL WHERE roster_id=?", (int(rid),))
    con.commit()
    con.close()
    _bz.audit(sess, "ROSTER", int(rid), "is_void", "1", "0")
    # 停诊时被取消的预约不会自动回来（患者可能已经另有安排），只能重新约
    return h.redirect("/desk/schedule?ok=已恢复出诊；停诊期间取消的预约需要患者或前台重新约")


@route("POST", "/desk/schedule/(\\d+)/cap")
def r_roster_cap(h, sess, rid):
    """改容量：原来容量建完就再也改不了，只能删了重排，等于把已有的号扔了。"""
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk/schedule?err=没有权限")
    f = h.form()
    try:
        cap = int(f.get("cap") or 0)
    except ValueError:
        return h.redirect("/desk/schedule?err=容量要填数字")
    con = db()
    r = con.execute("SELECT * FROM ROSTER WHERE roster_id=?", (int(rid),)).fetchone()
    if not r:
        con.close()
        return h.redirect("/desk/schedule?err=排班不存在")
    import biz as _bz
    if not _bz.same_clinic(sess, cid=r["clinic_id"]):
        con.close()
        return h.redirect("/desk/schedule?err=只能改本店的班")
    used = con.execute(
        "SELECT COUNT(*) FROM APPOINTMENT WHERE roster_id=?"
        " AND IFNULL(is_void,0)=0 AND status IN ('已预约','已到诊')", (int(rid),)).fetchone()[0]
    if cap < used:
        con.close()
        return h.redirect("/desk/schedule?err=已经约了 %d 位，容量不能小于这个数" % used)
    if cap < 1 or cap > 40:
        con.close()
        return h.redirect("/desk/schedule?err=容量要在 1~40 之间")
    con.execute("UPDATE ROSTER SET slot_capacity=? WHERE roster_id=?", (cap, int(rid)))
    con.commit()
    con.close()
    return h.redirect("/desk/schedule?ok=容量已改成 %d" % cap)


@route("POST", "/desk/schedule/new")
def r_roster_new(h, sess):
    if not sess:
        return h.redirect("/login")
    if sess["desk"] not in ("manager", "hq", "ops", "admin"):
        return h.redirect("/desk/schedule?err=没有权限")
    f = h.form()
    try:
        cid = int(f.get("clinic_id") or 0)
        did = int(f.get("dentist_id") or 0)
        d = (f.get("roster_date") or "").strip()
        s0 = (f.get("slot_start") or "").strip()
        s1 = (f.get("slot_end") or "").strip()
        cap = int(f.get("slot_capacity") or 6)
    except ValueError:
        return h.redirect("/desk/schedule?err=填的数字不对")
    if not (cid and did and d and s0 and s1):
        return h.redirect("/desk/schedule?err=门店、牙医、日期、时段都要填")
    import biz as _bz
    if not _bz.same_clinic(sess, cid=cid):
        return h.redirect("/desk/schedule?err=只能给本店排班")
    if s1 <= s0:
        return h.redirect("/desk/schedule?err=结束时间要晚于开始时间")
    if d < datetime.now().strftime("%Y-%m-%d"):
        return h.redirect("/desk/schedule?err=不能给过去的日期排班")
    con = db()
    # 原来只比 slot_start/slot_end 完全相等，于是「09:00-12:00」和「10:00-13:00」
    # 能同时排给同一个牙医——他要在两个诊室同时看两个人。改成区间相交判断。
    dup = con.execute(
        "SELECT roster_id, slot_start, slot_end FROM ROSTER"
        " WHERE dentist_id=? AND roster_date=? AND IFNULL(is_void,0)=0"
        "   AND slot_start < ? AND slot_end > ?",(did, d, s1, s0)).fetchone()
    if dup:
        con.close()
        return h.redirect("/desk/schedule?err=跟已有排班 %s—%s 时间重叠了"
                          % (dup["slot_start"], dup["slot_end"]))
    con.execute("INSERT INTO ROSTER(clinic_id, dentist_id, roster_date, slot_start,"
                " slot_end, slot_capacity, roster_status, is_published)"
                " VALUES(?,?,?,?,?,?,?,1)", (cid, did, d, s0, s1, cap, "手工排班"))
    nrid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    import biz as _bz
    _bz.audit(sess, "ROSTER", nrid, "roster_id", "", "新建 %s %s-%s" % (d, s0, s1),
              con=con)
    con.commit()
    con.close()
    return h.redirect("/desk/schedule?ok=排班已建立")


@route("GET", "/db-status")
def r_db(h, sess):
    return h.send(200, p_db_status(sess))


def main():
    # 业务路由在这里注册：biz 会 import server，所以必须等本模块加载完再导入，
    # 放在模块级会和 biz 形成循环导入（biz.register 还不存在）。
    import biz
    biz.register(sys.modules[__name__])
    try:
        import api as _api
        _api.register(sys.modules[__name__], biz)
    except Exception:
        # 接口层挂了不影响网页端：只记日志，不阻断启动。
        traceback.print_exc()
    import biz2
    biz2.register(sys.modules[__name__], biz)
    import biz4
    biz4.register(sys.modules[__name__], biz)

    if "--init-only" in sys.argv:
        print("已建库：%s（%d 张表）" % (DB_PATH, init_db()))
        return
    if not os.path.exists(DB_PATH):
        print("已建库：%s（%d 张表）" % (DB_PATH, init_db()))
        print("提示：先运行 python tools/seed.py 灌入演示数据")
    print("=" * 56)
    print("  ADC 诊疗管理系统   http://127.0.0.1:%d" % PORT)
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
