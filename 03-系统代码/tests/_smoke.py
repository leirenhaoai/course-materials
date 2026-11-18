# -*- coding: utf-8 -*-
"""六个角色逐页体检：登录每个演示账号，把它菜单里的每一页都拉一遍，
记录状态码与字节数。任何一页 500 或 0 字节都算失败。"""
import http.cookiejar
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = 'http://127.0.0.1:8000'

ACCOUNTS = [
    ('zhangsan', 'patient'),
    ('recept1', 'receptionist'),
    ('dentist1', 'dentist'),
    ('assist1', 'assistant'),
    ('manager1', 'supervisor'),
    ('ops1', 'ops'),
    ('finance1', 'finance'),
]

PAGES = {
    'patient': ['/me', '/me/book', '/me/book/1/2026-11-12', '/me/appointments',
                '/me/visits', '/db-status'],
    'receptionist': ['/desk', '/desk/appointments', '/desk/walkin', '/desk/patients',
                     '/desk/patient/1', '/db-status'],
    'dentist': ['/desk', '/desk/schedule', '/desk/performance', '/db-status'],
    'assistant': ['/desk', '/desk/materials', '/desk/patients', '/db-status'],
    'supervisor': ['/desk', '/desk/schedule', '/desk/leaves', '/desk/leaves/new',
                   '/desk/shifts', '/desk/complaints', '/desk/complaints/new',
                   '/desk/performance', '/db-status'],
    'ops': ['/desk', '/desk/clinics', '/desk/requisitions', '/desk/quality',
            '/desk/invoices', '/desk/reports', '/desk/accounts', '/desk/audit',
            '/db-status'],
    'finance': ['/desk', '/desk/invoices', '/desk/reports', '/db-status'],
}


def login(name):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(BASE + '/login',
            urllib.parse.urlencode({'login_name': name, 'password': '123456'}).encode()).read()
    return op


bad = []
for name, role in ACCOUNTS:
    op = login(name)
    print('=== %s (%s) ===' % (name, role))
    for path in PAGES[role]:
        try:
            r = op.open(BASE + path)
            b = r.read()
            code, n = r.getcode(), len(b)
            flag = 'OK ' if code == 200 and n > 500 else 'BAD'
            if flag == 'BAD':
                bad.append((name, path, code, n))
            print('  %s %-26s %d  %6d B' % (flag, path, code, n))
        except urllib.error.HTTPError as e:
            bad.append((name, path, e.code, 0))
            print('  BAD %-26s %d  %6d B' % (path, e.code, 0))
        except Exception as e:
            bad.append((name, path, 0, 0))
            print('  BAD %-26s %s' % (path, e))

print()
if bad:
    print('失败 %d 页：' % len(bad))
    for x in bad:
        print('  ', x)
else:
    print('全部页面通过')
