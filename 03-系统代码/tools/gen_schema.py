# -*- coding: utf-8 -*-
r"""由 db_model9 生成 SQLite 建表脚本 schema.sql。

映射规则：
  整数 -> INTEGER   小数 -> REAL   布尔 -> INTEGER(0/1)
  字符串 -> TEXT    日期/日期时间/时间 -> TEXT（SQLite 无日期类型，存 ISO 字符串）
外键照模型里的 fk 声明生成 REFERENCES，主键按实体表代理键 / 复合主键两种写法。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
ROOT = os.path.dirname(CODE)
sys.path.insert(0, os.path.join(ROOT, "生成脚本"))

import db_model9 as M  # noqa: E402


def sql_type(cn):
    if cn in ("整数", "布尔"):
        return "INTEGER"
    if cn == "小数":
        return "REAL"
    return "TEXT"


def main():
    lines = [
        "-- 由 生成脚本/db_model9.py 自动生成，不要手改。",
        "-- 56 张表 / 493 列 / 104 个外键。",
        "PRAGMA foreign_keys = ON;",
        "",
    ]
    for table in M.TABLES:
        cols = M.cols_of(table)
        comp = M.COMPOSITE_PK.get(table)
        cn = M.TABLE_CN.get(table, table)
        lines.append("-- %s（%s）" % (table, cn))
        lines.append("CREATE TABLE IF NOT EXISTS %s (" % table)
        body = []
        for col, kind, tgt in cols:
            t = sql_type(M.type_of(table, col))
            piece = "  %-24s %s" % (col, t)
            if comp:
                pass                      # 复合主键在表末统一声明
            elif kind == "pk":
                piece += " PRIMARY KEY"
            if tgt:
                piece += " REFERENCES %s" % tgt
            body.append(piece)
        if comp:
            body.append("  PRIMARY KEY (%s)" % ", ".join(comp))
        lines.append(",\n".join(body))
        lines.append(");")
        lines.append("")
    os.makedirs(os.path.join(CODE, "app"), exist_ok=True)
    out = os.path.join(CODE, "app", "schema.sql")
    io.open(out, "w", encoding="utf-8").write("\n".join(lines))
    print("已生成 %s（%d 张表）" % (out, len(M.TABLES)))


if __name__ == "__main__":
    main()
