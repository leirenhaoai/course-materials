# 附录 A　数据库设计规范与数据字典

对象：安德鲁牙科连锁店（ADC）诊疗管理系统——广东省 15 家牙科诊所，三年内拟翻一番。
案例出处：*Andrew's Dental Chain：数据建模*，案例编号 W44694，Ivey Business School Foundation。
本附录与正文第六章「D-设计：建立数据层」配套：第六章给出映射准则与类到表的对应，
本附录把同一套模型固化成可执行的建库规范（命名、通用字段、类型与约束），并给出全量数据字典与外键清单。

模型口径（与 `db_model7.py` 完全一致，本附录全部内容由该文件遍历生成）：

| 项目 | 数量 |
|---|---|
| 表 | 49 张（按主题域分为患者、门店人员、预约就诊、诊疗记录、结算收款、耗材库存、采购供应商、对账付款、核算、质量合规、影像共 11 个域） |
| 列 | 300 列 |
| 外键 | 58 条 |
| 联合主键表 | 6 张（DENTIST_QUALIFICATION、INVOICE_LINE、PURCHASE_ORDER_LINE、RECEIPT_LINE、STATEMENT_LINE、TREATMENT_ITEM） |
| 非规范化列 | 3 列（ACCOUNT_PAYABLE.payable_amount、INCENTIVE_FUND.net_profit、INVOICE_LINE.line_subtotal） |
| 通用审计列 | 0 列（约定见 A.2） |

映射规则出处（与第六章一致）：按「类→表、属性→列、对象→行」；「1:N 外键放多方，
M:N 另建关联表、两端标识进该表；组合外键放多方且 NOT NULL」；「主键唯一、恒定，并与领域字段分开」。

### A.1 命名规范

命名的作用是让 49 张表、300 列在没有中文注释的建库脚本里也能读懂。本模型采用英文标识符，
与第六章图 10 的数据库总图完全一致，规则如下。

**1) 表名：全大写、单词间用下划线分隔、用单数。**
类图上每个实体类对应一张同名表，表名即类名的英文大写形式；多单词用下划线连接，不用驼峰、不用缩写。

- 单表：`PATIENT`（患者）、`APPOINTMENT`（预约）、`MATERIAL`（耗材）、`SUPPLIER`（供应商）。
- 多单词：`MEDICAL_HISTORY`（病史记录）、`TREATMENT_CATALOG`（治疗项目目录）、
  `DENTIST_QUARTER_PERFORMANCE`（牙医季度业绩）、`RECEIPT_NOTE`（入库单）。
- 单据-明细成对出现时，明细表在单据表名后加 `_LINE`：`INVOICE` / `INVOICE_LINE`、
  `PURCHASE_ORDER` / `PURCHASE_ORDER_LINE`、`RECEIPT_NOTE` / `RECEIPT_LINE`、`STATEMENT` / `STATEMENT_LINE`。
- M:N 关联表用两张父表名拼接：`DENTIST_QUALIFICATION`（牙医×资质）。

**2) 列名：全小写、单词间用下划线分隔，不使用任何 DBMS 保留字。**

- 单单词：`name`、`phone`、`email`、`quantity`、`amount`、`status`、`active`。
- 多单词：`appointment_datetime`（预约日期时间）、`standard_unit_price`（标准单位价格）、
  `emergency_contact_phone`（紧急联系人电话）、`operating_expense_amount`（季度运营费用金额）。

**3) 主键列名：一律 `<表名单数小写>_id`。**

实体表不使用业务字段作主键，而是另设整型代理键，列名规则化为「表名的单数小写下划线形式 + `_id`」：
`PATIENT.patient_id`、`DENTIST.dentist_id`、`CLINIC.clinic_id`、`INVOICE.invoice_id`、
`MATERIAL_BATCH.batch_id`、`ACCOUNT_PAYABLE.payable_id`。
这样做的理由：代理键唯一、恒定、与领域字段分开，业务编号改了也不会牵连任何引用它的外键。

**4) 外键列名与所引用目标表的主键列名完全相同（同名同义）。**

本模型 58 条外键全部满足这一条，可以直接按列名看出指向：

| 子表.外键列 | 父表.主键列 | 列名是否相同 |
|---|---|---|
| `ALLERGY.patient_id` | `PATIENT.patient_id` | 相同 |
| `MEDICAL_HISTORY.patient_id` | `PATIENT.patient_id` | 相同 |
| `MEMBER.patient_id` | `PATIENT.patient_id` | 相同 |
| `STAFF.clinic_id` | `CLINIC.clinic_id` | 相同 |
| `ROSTER.dentist_id` | `DENTIST.dentist_id` | 相同 |
| `ROSTER.clinic_id` | `CLINIC.clinic_id` | 相同 |
| …（其余 52 条见 A.5 全量清单，列名同样与父表主键同名） | — | 相同 |

因此一条外键可以只写成 `patient_id → PATIENT`，读图或读脚本都不必回头查父表的键名。
注意 `STOCK_LEDGER` 的代理键列写作 `ledger_id`（表名 `STOCK_LEDGER` 去 `_LEDGER` 后加 `_id`），
`STOCK_MOVEMENT` 的代理键写作 `movement_id`——去掉冗余的后缀词，避免出现 `stock_ledger_id` 这类拗口长名。

**5) 布尔列用语义化命名，不使用 `flag`、`status1` 这类无含义名字。**

本模型共 4 个布尔列，命名分两类：

| 列 | 所在表 | 中文含义 | 命名法 | 取值 |
|---|---|---|---|---|
| `treated` | VISIT | 是否已就诊 | 过去分词作状态 | 0/false＝未就诊（初始值），1/true＝已就诊 |
| `active` | DENTIST | 是否在职 | 形容词作状态 | 1/true＝在职，0/false＝离职 |
| `is_high_value` | MATERIAL | 是否高值耗材 | `is_` 前缀 | 1/true＝高值（种植体等，须登记批号追溯），0/false＝普通 |
| `is_whole_mouth` | TREATMENT_CATALOG | 是否全口项目 | `is_` 前缀 | 1/true＝全口（全口洁治、涂氟），0/false＝按牙位 |

无形容词可用的新布尔列统一用 `is_` 前缀（如未来增加「是否医保」写作 `is_insured`）；
已有的 `treated`、`active` 与案例原文口径一致（案例明确要求「以布尔字段显示，初始值设置为 0/false，
如患者已就诊，则更新为 1/true」），保持原词不改成 `is_treated`。
命名法与取值约定同时写进 A.3 的约束约定，建库时布尔列统一 `TINYINT(1)` 并加 `CHECK (列名 IN (0,1))`。

**6) 明细表的行号列统一叫 `line_no`。**

单据-明细拆两张表是本设计的既定口径（第六章 6.1.4），明细表主键＝「单据号＋行号」。
行号列在全部 6 张明细/关联表中一律命名 `line_no`，不用 `seq`、`item_no`、`lineno` 等变体：

| 明细表 | 联合主键 |
|---|---|
| DENTIST_QUALIFICATION（牙医资质（M:N）） | `dentist_id` ＋ `qualification_id` |
| TREATMENT_ITEM（就诊治疗行） | `visit_id` ＋ `line_no` |
| INVOICE_LINE（结算单明细） | `invoice_id` ＋ `line_no` |
| PURCHASE_ORDER_LINE（采购订单明细） | `po_id` ＋ `line_no` |
| RECEIPT_LINE（入库单明细） | `receipt_id` ＋ `line_no` |
| STATEMENT_LINE（对账单明细） | `statement_id` ＋ `line_no` |

其中只有 `DENTIST_QUALIFICATION` 没有行号列——它是 M:N 关联表，联合主键由两端标识构成；
其余 5 张都是「头表主键 + `line_no`」的明细表。`line_no` 从 1 开始、在单据内连续，只表示行序，
数值本身没有业务含义，重排行也不会影响任何引用（没有任何外键指向它）。

**7) 业务编号带领域含义、可能变化，一律只作普通列，绝不参与主键。**

案例中的员工编号、门店编号、单号等都是给业务人员看的标识，会因整改、合并、重排而变动；
按「主键唯一、恒定、与领域字段分开」的准则，本模型把它们全部保留为普通列，只在其上加唯一约束。

| 业务编号列 | 所在表 | 中文含义 | 约束 |
|---|---|---|---|
| `patient_no` | PATIENT | 患者编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `member_no` | MEMBER | 会员编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `clinic_no` | CLINIC | 门店编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `staff_no` | STAFF | 员工编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `employee_no` | DENTIST | 员工编号（业务编号，唯一；带领域含义，可变更） | 普通列 + UNIQUE；不参与主键 |
| `qualification_code` | QUALIFICATION | 资质编码 | 普通列 + UNIQUE；不参与主键 |
| `item_code` | TREATMENT_CATALOG | 项目编码 | 普通列 + UNIQUE；不参与主键 |
| `visit_no` | VISIT | 就诊编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `plan_no` | TREATMENT_PLAN | 治疗计划编号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `invoice_no` | INVOICE | 结算单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `payment_no` | PAYMENT | 收款单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `policy_no` | INSURANCE_POLICY | 保单号（业务编号） | 普通列 + UNIQUE；不参与主键 |
| `material_code` | MATERIAL | 耗材编码 | 普通列 + UNIQUE；不参与主键 |
| `batch_serial_no` | MATERIAL_BATCH | 批号或序列号（业务编号，唯一；高值耗材追溯依据） | 普通列 + UNIQUE；不参与主键 |
| `po_no` | PURCHASE_ORDER | 采购订单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `receipt_no` | RECEIPT_NOTE | 入库单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `issue_no` | MATERIAL_ISSUE | 领用单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `supplier_code` | SUPPLIER | 供应商编码 | 普通列 + UNIQUE；不参与主键 |
| `term_code` | SETTLEMENT_TERM | 条款编码 | 普通列 + UNIQUE；不参与主键 |
| `statement_no` | STATEMENT | 对账单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `payable_no` | ACCOUNT_PAYABLE | 应付单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `record_no` | PAYMENT_RECORD | 付款单号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |
| `version_no` | COST_VERSION | 版本号（业务编号，唯一） | 普通列 + UNIQUE；不参与主键 |

**8) 命名禁则。** 不使用中文列名、不使用空格与连字符、不使用 `tbl_`/`tb_` 前缀、
不使用 `data1`/`value`/`type` 这类无法区分的泛名——需要表达分类时写成 `source_type`、
`movement_type`、`incident_type`、`image_type` 等带限定词的名称。

### A.2 通用字段约定

**本模型不设 `CreatedAt`／`UpdatedAt`／`CreatedBy`／`UpdatedBy` 一类通用审计列。**
这不是遗漏，而是一条明确约定，理由有四条。

**第一，它们不属于领域模型。** 这组列回答的是「这行记录是哪个进程什么时候写进来的」，
属于运行环境与安全审计的事实，不来自案例的需求（患者、预约、治疗、结算、耗材、激励），
在类图上找不到对应的属性。把它们塞进每一张表，等于把存储实现的细节混进领域设计。

**第二，逐表添加会污染数据字典。** 本模型 300 列，若 49 张表各加 4 列，会凭空多出近 200 列，
占比超过三成，逐字段清单里全是 `created_at`／`updated_at` 的重复行，真正的业务列被淹没。
把它写成一条约定而不是逐表落列，正是为了让 A.4 的字典保持可读——每张表列的都是业务事实。

**第三，它们可以由数据库或应用层统一维护。** 建库时用触发器（`BEFORE INSERT` 写创建时间、
`BEFORE UPDATE` 写更新时间），或由持久化框架统一拦截填充，一处配置覆盖全库；
将来要加字段、改时区、换实现，也只需改这一处，不必对 49 张表做结构变更。

**第四，也是最重要的一条：需要留痕的场景，本模型用带业务含义的列来表达，不用通用审计列。**
通用审计列只记「谁在什么时候动了这行」，记不出「改了哪个字段、改前是什么、为什么改」；
而 ADC 真正要留痕的两件事都需要后者，因此专门建表，并挂在患者病历上：

| 留痕场景 | 承载的表 | 记录的内容 | 案例／第六章依据 |
|---|---|---|---|
| 病历内容修改留痕 | `AUDIT_LOG` | `record_table`、`record_id_ref`、`changed_field`、`old_value`、`new_value`、`operator_name`、`changed_datetime`，按 `patient_id` 归档 | 用例规约 UC-01 质量需求：「病历内容被修改时必须留痕」 |
| 跨门店病历调阅留痕 | `RECORD_ACCESS_LOG` | `operator_name`、`access_datetime`、`purpose`、`authorization_ref`，按 `patient_id`＋`clinic_id` 归档 | 第六章设计约束：「患者档案与治疗记录允许跨门店查询并保留调阅记录」 |

除这两张专表之外，各单据自身也带业务化的经手与时间列，它们同样是领域事实，而非审计列：

| 业务列 | 所在表 | 说明 |
|---|---|---|
| `issued_by` | MATERIAL_ISSUE | 领用人：耗材去向的责任人，用于追溯与成本归集 |
| `operator_name` | DISINFECTION_RECORD | 消毒操作人：感控记录的必要内容 |
| `status` | INVOICE、PURCHASE_ORDER、RECEIPT_NOTE、STATEMENT、ACCOUNT_PAYABLE、COMPLAINT 等 12 张表 | 单据状态：表示业务进展到哪一步（枚举取值见 A.3），不是技术状态 |
| 各 `*_date` / `*_datetime` | 全模型 28 列 | 业务发生时间：`invoice_date` 开单日期、`paid_datetime` 收款时间、`moved_datetime` 出入库时间、`issued_datetime` 领用时间等 |

验收口径：数据字典 A.4 中不得出现 `created_at`、`updated_at`、`created_by`、`updated_by`（本附录自检即为 0）；
任何想「顺手加一列审计字段」的改动，都应先判断它是否属于上述两类留痕场景，属于就进 `AUDIT_LOG`／`RECORD_ACCESS_LOG`，
不属于就不要加。

### A.3 数据类型与约束约定

#### A.3.1 类型推导规则

数据字典里的类型不是逐列手工指定的，而是由列名后缀按一套规则统一推导（见 `db_model7.py` 的 `type_of()`），
并与三张分析类图上的类型标注对齐；少数无法从后缀判断的列用显式覆盖表钉死（`TYPE_OVERRIDES`）。规则如下：

| 序号 | 判定条件（按顺序匹配） | 推导类型 | 真实例子 |
|---|---|---|---|
| 1 | 出现在显式覆盖表中 | 按覆盖值 | `treated`/`active`/`is_high_value`/`is_whole_mouth`→布尔；`tooth_fdi`/`quarter`/各类地址与电话邮箱→字符串；`appointment_datetime`/`visit_datetime`/`paid_datetime`/`taken_datetime`→日期时间 |
| 2 | 列名以 `_id` 结尾 | 整数 | `patient_id`、`invoice_id`、`batch_id`（全部 108 个） |
| 3 | 列名以 `_no` 或 `_count` 结尾 | 整数 | `line_no`（行号，从 1 开始）、`installment_count`（分期期数）；业务编号类 `_no` 列（`patient_no`、`invoice_no` 等）也归入整数，建库时可放宽为 `VARCHAR`，见下方注 |
| 4 | 列名以 `_date` 结尾 | 日期 | `record_date`、`expiry_date`、`due_date`、`order_date`、`effective_date` |
| 5 | 列名以 `_at`、`_datetime` 或 `_time` 结尾 | 日期时间 | `paid_datetime`、`moved_datetime`、`issued_datetime`、`access_datetime`、`changed_datetime`、`slot_start`/`slot_end` |
| 6 | 列名以 `_price`、`_amount`、`_cost`、`_qty`、`_units`、`_ratio`、`_area_sqm` 结尾，或列名恰为 `quantity` | 小数 | `standard_unit_price`、`unit_price`、`purchase_unit_price`、`claimed_amount`、`payable_amount`、`net_profit`、`standard_cost`、`on_hand_qty`、`standard_units`、`return_ratio`、`office_area_sqm`、`quantity` |
| 7 | 列名以 `is_` 或 `has_` 开头 | 布尔 | `is_high_value`、`is_whole_mouth` |
| 8 | 其余 | 字符串 | `name`、`status`、`material_name`、`special_notes`、`image_url`、`severity`、`method` |

按此规则推导的结果：整数 134 列、字符串 111 列（其中 73 个不同列名）、日期 20 列、小数 23 列、日期时间 8 列、布尔 4 列，合计 300 列。

> 注（业务编号的落地取舍）：规则 3 把 `_no` 结尾的列推成整数，理由是「编号是数字」；
> 但本模型的业务编号（`patient_no`、`invoice_no`、`po_no`、`batch_serial_no` 等）含前缀、年份、补零位，
> 例如 `INV-2026-000123`、`BN-2026-0001` 这类形式无法用整数表达。建库时对这些列表述为 `VARCHAR(32)` 并加 `UNIQUE`，
> A.4 的数据类型一栏因而写成「整数（VARCHAR(32)）」：括号外是规则推导的逻辑类型，括号内是建库落地类型，两种口径都能对上。
> 唯一例外是 `line_no`：它是明细内部的行序，确定是整数，用 `INT` 并参与联合主键。
>
> 同类规则边界还有一处：`date_of_birth`（PATIENT／DENTIST）与 `valid_until`（INSURANCE_POLICY）语义上是日期，
> 但列名不带 `_date` 后缀，按规则 8 归入字符串。为了不改动模型口径，A.4 仍按模型标注 `字符串（VARCHAR(100)）`，
> 并在该列「约束与说明」中注明建议落地为 `DATE`；建库时按 `DATE` 处理即可。

#### A.3.2 映射到具体 DBMS 的建议

上表是逻辑类型；建库时按下表映射。以 MySQL／MariaDB 为例（其余 DBMS 对应关系类似）：

| 逻辑类型 | 建议物理类型 | 说明 | 本模型列数 |
|---|---|---|---|
| 整数 | `INT`（代理键用 `INT UNSIGNED AUTO_INCREMENT`；行号 `line_no` 用 `INT`；预计超 21 亿行的流水表如 `STOCK_MOVEMENT`、`AUDIT_LOG` 可用 `BIGINT`） | 所有 `*_id` 代理键与 `line_no`、`installment_count` | 135 |
| 小数 | `DECIMAL(10,2)`（比例类如 `return_ratio`、`fund_rate` 用 `DECIMAL(5,4)`；数量类如 `quantity`、`on_hand_qty`、`standard_units` 用 `DECIMAL(12,3)`；面积 `office_area_sqm` 用 `DECIMAL(8,2)`） | 金额一律定点，绝不用 `FLOAT`／`DOUBLE`，避免激励基金与结算金额出现舍入争议 | 30 |
| 字符串 | `VARCHAR(n)`：名称与地址类 `VARCHAR(100)`；编码与编号类 `VARCHAR(32)`；文本内容类（`content`、`resolution`、`description`、`special_notes`、`plan_description`）`VARCHAR(500)`；URL（`image_url`）`VARCHAR(255)` | 按用途定长，避免全表 `VARCHAR(255)` | 101 |
| 日期 | `DATE` | 只到天的业务日期 | 22 |
| 日期时间 | `DATETIME`（时间点统一用 `DATETIME` 不用 `TIMESTAMP`；`slot_start`/`slot_end` 只表示时段，也可用 `TIME`） | 需精确到分钟的时点 | 8 |
| 布尔 | `TINYINT(1)` + `CHECK (列名 IN (0,1))` | 与案例「0/false、1/true」的表述一致 | 4 |

字符集与排序规则：全库统一 `utf8mb4` / `utf8mb4_general_ci`（中文姓名、备注与表情符号都能存）；
时点列统一按同一时区（建议 `Asia/Shanghai`）解释，跨门店不存在时区差异。

#### A.3.3 约束约定

**1) 主键。** 实体表用单列整型代理键，声明 `PRIMARY KEY`。本模型共 49 张表，
其中 43 张为单列代理键，6 张为联合主键：

- `DENTIST_QUALIFICATION`：`PRIMARY KEY (dentist_id, qualification_id)`——M:N 关联表，主键即两端标识（案例：多数资质由多位牙医共有）。
- `TREATMENT_ITEM`：`PRIMARY KEY (visit_id, line_no)`——单据-明细表，主键＝单据主键＋行号。
- `INVOICE_LINE`：`PRIMARY KEY (invoice_id, line_no)`——单据-明细表，主键＝单据主键＋行号。
- `PURCHASE_ORDER_LINE`：`PRIMARY KEY (po_id, line_no)`——单据-明细表，主键＝单据主键＋行号。
- `RECEIPT_LINE`：`PRIMARY KEY (receipt_id, line_no)`——单据-明细表，主键＝单据主键＋行号。
- `STATEMENT_LINE`：`PRIMARY KEY (statement_id, line_no)`——单据-明细表，主键＝单据主键＋行号。

**2) 外键。** 全部 58 条关系一律声明 `FOREIGN KEY`，不允许只在应用层维护：

- 写法：`FOREIGN KEY (列名) REFERENCES 父表(列名)`，例如 `VISIT.appointment_id REFERENCES APPOINTMENT(appointment_id)`。
- **组合（composition）外键加 `NOT NULL` 并按 `ON DELETE CASCADE` 级联**：明细行不能脱离主体存在，
  例如 `TREATMENT_ITEM.visit_id`、`INVOICE.visit_id`、`INVOICE_LINE.invoice_id`、`STOCK_MOVEMENT.ledger_id`。
- 一般引用的外键（如字典表方向）用 `ON DELETE RESTRICT`，禁止删掉仍被引用的父行。
- 可空外键先在应用层判空再写库，例如 `FOLLOWUP_RECALL.visit_id` 允许为空（只按患者发起召回时不指向具体就诊）。

**3) 单据状态列一律用枚举取值，不用自由文本。** 本模型有 12 个状态列（另有 `severity`、`direction`、`movement_type` 等分类列同法处理）：

| 表.列 | 允许取值 |
|---|---|
| `APPOINTMENT.status` | 预约中/已就诊/已取消/爽约 |
| `INVOICE.status` | 待收/部分收款/已结清 |
| `INSTALLMENT_PLAN.status` | 执行中/已结清/已逾期 |
| `INSURANCE_CLAIM.status` | 已提交/审核中/已赔付/被拒赔 |
| `MEDICAL_HISTORY.status` | 活动/已痊愈 |
| `PURCHASE_ORDER.status` | 草稿/已下达/部分到货/已到货/已关闭 |
| `RECEIPT_NOTE.status` | 待入库/已入库/已冲销 |
| `STATEMENT.status` | 待确认/已确认/已核销 |
| `ACCOUNT_PAYABLE.status` | 未付/部分付款/已结清 |
| `COMPLAINT.status` | 待处理/处理中/已回访/已关闭 |
| `QUALITY_INCIDENT.status` | 待整改/整改中/已关闭 |
| `FOLLOWUP_RECALL.status` | 待联系/已通知/已完成/已失访 |

落地方式：字段用 `VARCHAR(16)` 存代码值，并用 `CHECK (status IN (...))` 约束，
或另建字典表＋外键；两种都行，但取值集合必须写进设计说明，避免各门店口径不一。

**4) 唯一约束（`UNIQUE`）。** 三类列必须唯一：

- **业务编号**（23 个）：`patient_no`、`member_no`、`clinic_no`、`staff_no`、`employee_no`、`qualification_code`、`item_code`、`visit_no`、`plan_no`、`invoice_no`、`payment_no`、`policy_no`、`material_code`、`batch_serial_no`、`po_no`、`receipt_no`、`issue_no`、`supplier_code`、`term_code`、`statement_no`、`payable_no`、`record_no`、`version_no`——案例明确要求「除了唯一的单号外」，单号必须唯一，它们是跨门店对账与打印的对外标识。
- **账目唯一性**：`STOCK_LEDGER` 的 `(clinic_id, material_id)` 唯一（一家门店一种耗材只有一行余额）；
  `DENTIST_QUARTER_PERFORMANCE` 的 `(dentist_id, quarter)` 与 `INCENTIVE_FUND` 的 `(perf_id, quarter)` 唯一（同一季度不重复核算）。
- **已隐含唯一的联合主键**：6 张联合主键表的主键组合本身已保证唯一，例如 `TREATMENT_ITEM(visit_id, line_no)`。

**5) 非空（`NOT NULL`）。** 主键、全部组合外键、以及案例明确要求的字段（如 `PATIENT.name`、
`DENTIST.employee_no`、`CLINIC.postal_address`、`TREATMENT_ITEM.standard_units`、`INVOICE.invoice_no`）加 `NOT NULL`；
案例标注为可选的只有 `PATIENT.email`（原文「电子邮箱地址（可选）」），保持可空。
其余字符串列按业务需要取舍，写库前由应用层校验，不强求全表 `NOT NULL`。

**6) 检查约束（`CHECK`）。** 布尔列限 0/1；金额与数量列 `>= 0`；
`INVOICE_LINE.line_subtotal` 加 `CHECK (line_subtotal = units_used * unit_price)`（非规范化列的一致性兜底，见 A.2 与该列说明）；
`SETTLEMENT_TERM.return_ratio` 与 `INCENTIVE_FUND.fund_rate` 限 `BETWEEN 0 AND 1`。

### A.4 主要表的数据字典

本节逐张列出全部 49 张表的 300 个字段。表格四列：字段、中文含义、数据类型（A.3.1 逻辑类型，括号内为 A.3.2 的落地类型）、约束与说明。
约束列的记号：`PK` 主键；`FK→父表` 外键及其目标；`联合主键` 标出该表主键的全部组成列；`UNIQUE` 唯一；`NOT NULL` 非空；`多态` 表示数据库外键无法表达、由应用层校验的引用。
每张表的用途一行取自模型的表用途定义，括号中的「行业惯例补充」表示该表案例未直接提及、按口腔连锁行业惯例补齐。

#### 表 A-1　PATIENT（患者）

**用途**：患者主档：账号、姓名、出生日期、账单地址、电话、邮箱（可选）、紧急联系人。

**主题域**：患者与就诊档案。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `patient_id` | 患者标识 | 整数（INT） | PK，自增代理键 |
| `patient_no` | 患者编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `name` | 姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `date_of_birth` | 出生日期 | 日期（DATE） | 语义上是日期：列名无 `_date` 后缀故按规则推导为字符串，建库时建议落地为 `DATE`（见 A.3.1 注） |
| `billing_address` | 账单地址 | 字符串（VARCHAR(100)） | 普通列 |
| `phone` | 电话号码 | 字符串（VARCHAR(100)） | 普通列 |
| `email` | 电子邮箱（可选） | 字符串（VARCHAR(100)） | 普通列 |
| `emergency_contact_name` | 紧急联系人姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `emergency_contact_phone` | 紧急联系人电话 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-2　ALLERGY（过敏症）

**用途**：患者过敏症，1:N 逐条注明（乳胶/麻醉剂/金属/树脂等）。

**主题域**：患者与就诊档案。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `allergy_id` | 过敏症标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `allergy_name` | 过敏症名称（乳胶/麻醉剂/金属/树脂等） | 字符串（VARCHAR(100)） | 普通列 |
| `severity` | 严重程度 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-3　MEDICAL_HISTORY（病史记录）

**用途**：病史与既往治疗记录，支撑跨门店调阅（行业惯例补充）。

**主题域**：患者与就诊档案。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `history_id` | 病史记录标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `record_date` | 记录日期 | 日期（DATE） | 普通列 |
| `condition_description` | 病症描述 | 字符串（VARCHAR(100)） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：活动/已痊愈 |

#### 表 A-4　MEMBER（会员）

**用途**：患者会员档案：等级与积分运营（行业惯例补充）。

**主题域**：患者与就诊档案。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `member_id` | 会员标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `member_no` | 会员编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `member_level` | 会员等级 | 字符串（VARCHAR(100)） | 普通列 |
| `joined_date` | 入会日期 | 日期（DATE） | 普通列 |

#### 表 A-5　CLINIC（诊所门店）

**用途**：诊所位置数据：邮政地址、主管姓名、电话、邮箱、办公面积（平方米）。

**主题域**：门店与人员。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `clinic_id` | 门店标识 | 整数（INT） | PK，自增代理键 |
| `clinic_no` | 门店编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `clinic_name` | 门店名称 | 字符串（VARCHAR(100)） | 普通列 |
| `postal_address` | 邮政地址 | 字符串（VARCHAR(100)） | 普通列 |
| `manager_name` | 主管姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `phone` | 电话号码 | 字符串（VARCHAR(100)） | 普通列 |
| `email` | 电子邮箱（可选） | 字符串（VARCHAR(100)） | 普通列 |
| `office_area_sqm` | 办公面积（平方米） | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-6　STAFF（门店员工）

**用途**：门店非牙医员工档案（前台/助理），行业惯例补充。

**主题域**：门店与人员。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `staff_id` | 员工标识 | 整数（INT） | PK，自增代理键 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；NOT NULL，随主体级联删除 |
| `staff_no` | 员工编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `name` | 姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `role` | 岗位角色（前台/助理等） | 字符串（VARCHAR(100)） | 普通列 |
| `phone` | 电话号码 | 字符串（VARCHAR(100)） | 普通列 |
| `email` | 电子邮箱（可选） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-7　DENTIST（牙医）

**用途**：牙医个人信息：员工编号、姓名、出生日期、家庭住址、电话、邮箱；不专属任何诊所。

**主题域**：门店与人员。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `dentist_id` | 牙医标识 | 整数（INT） | PK，自增代理键 |
| `employee_no` | 员工编号（业务编号，唯一；带领域含义，可变更） | 整数（VARCHAR(32)） | UNIQUE |
| `name` | 姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `date_of_birth` | 出生日期 | 日期（DATE） | 语义上是日期：列名无 `_date` 后缀故按规则推导为字符串，建库时建议落地为 `DATE`（见 A.3.1 注） |
| `home_address` | 家庭住址 | 字符串（VARCHAR(100)） | 普通列 |
| `phone` | 电话号码 | 字符串（VARCHAR(100)） | 普通列 |
| `email` | 电子邮箱（可选） | 字符串（VARCHAR(100)） | 普通列 |
| `active` | 在职标记（1=在职，0=离职） | 布尔（TINYINT(1)） | 0/false 与 1/true，CHECK (列名 IN (0,1)) |

#### 表 A-8　QUALIFICATION（专业资质）

**用途**：资质字典：牙髓病学、口腔病理学、口腔放射学、儿科等。

**主题域**：门店与人员。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `qualification_id` | 资质标识 | 整数（INT） | PK，自增代理键 |
| `qualification_code` | 资质编码 | 字符串（VARCHAR(100)） | UNIQUE |
| `qualification_name` | 资质名称（牙髓病学/口腔病理学/口腔放射学/儿科等） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-9　DENTIST_QUALIFICATION（牙医资质（M:N））

**用途**：牙医-资质多对多关联，主键＝两端标识（案例：多数资质由多位牙医共有）。

**主键**：联合主键 ``dentist_id` ＋ `qualification_id``。

**主题域**：门店与人员。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `dentist_id` | 牙医标识 | 整数（INT） | PK（联合主键组成之一）；FK→DENTIST.dentist_id；NOT NULL，随主体级联删除 |
| `qualification_id` | 资质标识 | 整数（INT） | PK（联合主键组成之一）；FK→QUALIFICATION.qualification_id；NOT NULL，随主体级联删除 |
| `obtained_date` | 取得日期 | 日期（DATE） | 普通列 |

#### 表 A-10　ROSTER（接诊安排）

**用途**：牙医×诊所×日期×时段的轮转接诊安排（牙医按技能在多诊所轮转）。

**主题域**：预约与就诊。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `roster_id` | 接诊安排标识 | 整数（INT） | PK，自增代理键 |
| `dentist_id` | 牙医标识 | 整数（INT） | FK→DENTIST.dentist_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；NOT NULL，随主体级联删除 |
| `roster_date` | 出诊日期 | 日期（DATE） | 普通列 |
| `slot_start` | 时段开始时间 | 字符串（VARCHAR(100)） | 普通列 |
| `slot_end` | 时段结束时间 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-11　APPOINTMENT（预约）

**用途**：通话预约：指定具体日期时间与接诊牙医（经 ROSTER）；取消跟踪与取消率统计。

**主题域**：预约与就诊。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `appointment_id` | 预约标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `roster_id` | 接诊安排标识 | 整数（INT） | FK→ROSTER.roster_id；NOT NULL，随主体级联删除 |
| `appointment_datetime` | 预约日期时间 | 日期时间（DATETIME） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：预约中/已就诊/已取消/爽约 |
| `cancellation_category` | 取消原因分类（患者取消/患者爽约/诊所改约/医生停诊） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-12　VISIT（就诊）

**用途**：就诊记录：含已就诊布尔 treated（初始 false，就诊后置 true）与特殊需求记录。

**主题域**：预约与就诊。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `visit_id` | 就诊标识 | 整数（INT） | PK，自增代理键 |
| `visit_no` | 就诊编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `appointment_id` | 预约标识 | 整数（INT） | FK→APPOINTMENT.appointment_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；NOT NULL，随主体级联删除 |
| `visit_datetime` | 就诊日期时间 | 日期时间（DATETIME） | 普通列 |
| `treated` | 是否已就诊（布尔，初始 0/false，就诊后置 1/true） | 布尔（TINYINT(1)） | 0/false 与 1/true，CHECK (列名 IN (0,1)) |
| `special_notes` | 特殊需求与说明 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-13　TREATMENT_PLAN（治疗计划）

**用途**：就诊的治疗计划（通话中患者说明的期望治疗，行业惯例补充）。

**主题域**：预约与就诊。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `plan_id` | 治疗计划标识 | 整数（INT） | PK，自增代理键 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `plan_no` | 治疗计划编号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `created_date` | 建立日期 | 日期（DATE） | 普通列 |
| `plan_description` | 治疗计划说明 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-14　TREATMENT_ITEM（就诊治疗行）

**用途**：就诊的治疗行：项目/牙位FDI/标准单位数/标准单位价格/本次成交价；支持就诊期间追加。

**主键**：联合主键 ``visit_id` ＋ `line_no``。

**主题域**：诊疗记录。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `visit_id` | 就诊标识 | 整数（INT） | PK（联合主键组成之一）；FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `line_no` | 行号（单据内顺序号，联合主键的一部分） | 整数（INT） | PK（联合主键组成之一） |
| `catalog_id` | 治疗项目标识 | 整数（INT） | FK→TREATMENT_CATALOG.catalog_id；可空引用 |
| `dentist_id` | 牙医标识 | 整数（INT） | FK→DENTIST.dentist_id；可空引用 |
| `tooth_fdi` | 牙位（FDI 编号；全口项目留空） | 字符串（VARCHAR(100)） | FDI 牙位编号，全口项目留空 |
| `standard_units` | 施用标准单位数 | 小数（DECIMAL(10,2)） | 普通列 |
| `standard_unit_price` | 标准单位价格 | 小数（DECIMAL(10,2)） | 普通列 |
| `agreed_price` | 本次成交价（实际收费以成交价为准） | 小数（DECIMAL(10,2)） | 普通列 |
| `added_during_visit` | 是否就诊期间追加（1=追加，0=计划内） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-15　TREATMENT_CATALOG（治疗项目目录）

**用途**：治疗项目目录：编码、名称、计价单位、标准单位价格。

**主题域**：诊疗记录。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `catalog_id` | 治疗项目标识 | 整数（INT） | PK，自增代理键 |
| `item_code` | 项目编码 | 字符串（VARCHAR(100)） | UNIQUE |
| `item_name` | 治疗项目名称 | 字符串（VARCHAR(100)） | 普通列 |
| `unit` | 计价单位 | 字符串（VARCHAR(100)） | 普通列 |
| `standard_unit_price` | 标准单位价格 | 小数（DECIMAL(10,2)） | 普通列 |
| `is_whole_mouth` | 是否全口项目（布尔，1=全口如全口洁治/涂氟） | 布尔（TINYINT(1)） | 0/false 与 1/true，CHECK (列名 IN (0,1)) |

#### 表 A-16　INVOICE（结算单）

**用途**：每次就诊一张结算单：唯一单号、总价、状态；组合外键 visit_id 不为空。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `invoice_id` | 结算单标识 | 整数（INT） | PK，自增代理键 |
| `invoice_no` | 结算单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `invoice_date` | 开单日期 | 日期（DATE） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待收/部分收款/已结清 |

#### 表 A-17　INVOICE_LINE（结算单明细）

**用途**：结算单逐行明细：治疗名称、施用单位数量、单位价格、小计；逐行来自治疗数据。

**主键**：联合主键 ``invoice_id` ＋ `line_no``。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `invoice_id` | 结算单标识 | 整数（INT） | PK（联合主键组成之一）；FK→INVOICE.invoice_id；NOT NULL，随主体级联删除 |
| `line_no` | 行号（单据内顺序号，联合主键的一部分） | 整数（INT） | PK（联合主键组成之一） |
| `item_name` | 治疗项目名称 | 字符串（VARCHAR(100)） | 普通列 |
| `units_used` | 施用单位数量 | 字符串（VARCHAR(100)） | 普通列 |
| `unit_price` | 单位价格 | 小数（DECIMAL(10,2)） | 普通列 |
| `line_subtotal` | 行小计（=施用单位数量×单位价格；非规范化列，取值由本行两列算出） | 小数（DECIMAL(10,2)） | 非规范化列：案例原文要求结算单逐行明细显示小计（施用单位数量×单位价格）；取值由明细两列算出 |

#### 表 A-18　PAYMENT（收款）

**用途**：患者收款流水：金额、方式、时间。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `payment_id` | 收款标识 | 整数（INT） | PK，自增代理键 |
| `invoice_id` | 结算单标识 | 整数（INT） | FK→INVOICE.invoice_id；NOT NULL，随主体级联删除 |
| `payment_no` | 收款单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `amount` | 金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `method` | 收款方式 | 字符串（VARCHAR(100)） | 普通列 |
| `paid_datetime` | 收款日期时间 | 日期时间（DATETIME） | 普通列 |

#### 表 A-19　INSTALLMENT_PLAN（分期计划）

**用途**：大额账单分期还款计划（行业惯例补充）。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `installment_id` | 分期计划标识 | 整数（INT） | PK，自增代理键 |
| `invoice_id` | 结算单标识 | 整数（INT） | FK→INVOICE.invoice_id；NOT NULL，随主体级联删除 |
| `installment_count` | 分期期数 | 整数（INT） | 普通列 |
| `first_due_date` | 首期应付日期 | 日期（DATE） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：执行中/已结清/已逾期 |

#### 表 A-20　INSURANCE_POLICY（保险保单）

**用途**：患者保险保单（行业惯例补充）。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `policy_id` | 保单标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `insurer_name` | 保险公司名称 | 字符串（VARCHAR(100)） | 普通列 |
| `policy_no` | 保单号（业务编号） | 整数（VARCHAR(32)） | UNIQUE |
| `coverage_scope` | 承保范围 | 字符串（VARCHAR(100)） | 普通列 |
| `valid_until` | 保单有效期至 | 字符串（VARCHAR(100)） | 语义上是日期：列名无 `_date` 后缀故按规则推导为字符串，建库时建议落地为 `DATE`（见 A.3.1 注） |

#### 表 A-21　INSURANCE_CLAIM（保险理赔）

**用途**：结算单发起的保险理赔（行业惯例补充）。

**主题域**：结算与收款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `claim_id` | 理赔标识 | 整数（INT） | PK，自增代理键 |
| `invoice_id` | 结算单标识 | 整数（INT） | FK→INVOICE.invoice_id；NOT NULL，随主体级联删除 |
| `policy_id` | 保单标识 | 整数（INT） | FK→INSURANCE_POLICY.policy_id；NOT NULL，随主体级联删除 |
| `submitted_date` | 提交日期 | 日期（DATE） | 普通列 |
| `claimed_amount` | 申请理赔金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `approved_amount` | 核定赔付金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：已提交/审核中/已赔付/被拒赔 |

#### 表 A-22　MATERIAL（耗材）

**用途**：耗材主档：编码、名称、计价单位、是否高值、再订货点。

**主题域**：耗材与库存。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `material_id` | 耗材标识 | 整数（INT） | PK，自增代理键 |
| `material_code` | 耗材编码 | 字符串（VARCHAR(100)） | UNIQUE |
| `material_name` | 耗材名称 | 字符串（VARCHAR(100)） | 普通列 |
| `unit` | 计价单位 | 字符串（VARCHAR(100)） | 普通列 |
| `is_high_value` | 是否高值耗材（布尔，1=高值，须登记批号追溯） | 布尔（TINYINT(1)） | 0/false 与 1/true，CHECK (列名 IN (0,1)) |
| `reorder_point` | 再订货点 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-23　MATERIAL_BATCH（耗材批次）

**用途**：耗材批次：批号或序列号、有效期、采购单价（效期追溯）。

**主题域**：耗材与库存。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `batch_id` | 耗材批次标识 | 整数（INT） | PK，自增代理键 |
| `material_id` | 耗材标识 | 整数（INT） | FK→MATERIAL.material_id；NOT NULL，随主体级联删除 |
| `batch_serial_no` | 批号或序列号（业务编号，唯一；高值耗材追溯依据） | 整数（VARCHAR(32)） | UNIQUE |
| `expiry_date` | 有效期至 | 日期（DATE） | 普通列 |
| `purchase_unit_price` | 采购单价 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-24　STOCK_LEDGER（库存余额）

**用途**：库存余额表：余额只由 STOCK_MOVEMENT 流水推动，不许手工改。

**主题域**：耗材与库存。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `ledger_id` | 库存余额标识 | 整数（INT） | PK，自增代理键 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；NOT NULL，随主体级联删除 |
| `material_id` | 耗材标识 | 整数（INT） | FK→MATERIAL.material_id；NOT NULL，随主体级联删除 |
| `on_hand_qty` | 在库数量（由库存流水推动，不许手工改） | 小数（DECIMAL(10,2)） | 不许手工改，只由 STOCK_MOVEMENT 推动 |

#### 表 A-25　STOCK_MOVEMENT（库存流水）

**用途**：库存流水表：每笔出入库的方向、数量与来源单据追溯。

**主题域**：耗材与库存。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `movement_id` | 库存流水标识 | 整数（INT） | PK，自增代理键 |
| `ledger_id` | 库存余额标识 | 整数（INT） | FK→STOCK_LEDGER.ledger_id；NOT NULL，随主体级联删除 |
| `movement_type` | 流水类型（采购入库/领用出库/盘点调整等） | 字符串（VARCHAR(100)） | 普通列 |
| `direction` | 方向（入/出） | 字符串（VARCHAR(100)） | 普通列 |
| `quantity` | 数量 | 小数（DECIMAL(10,2)） | 普通列 |
| `source_type` | 来源单据类型（多态引用，应用层校验） | 字符串（VARCHAR(100)） | 多态引用：指向 PURCHASE_ORDER／RECEIPT_NOTE／MATERIAL_ISSUE 等来源单据，应用层校验 |
| `source_no` | 来源单据号（多态引用，应用层校验） | 整数（VARCHAR(32)） | 多态引用：指向 PURCHASE_ORDER／RECEIPT_NOTE／MATERIAL_ISSUE 等来源单据，应用层校验 |
| `moved_datetime` | 发生日期时间 | 日期时间（DATETIME） | 普通列 |

#### 表 A-26　PURCHASE_ORDER（采购订单）

**用途**：耗材采购订单头：供应商、结算条款、状态。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `po_id` | 采购订单标识 | 整数（INT） | PK，自增代理键 |
| `po_no` | 采购订单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `supplier_id` | 供应商标识 | 整数（INT） | FK→SUPPLIER.supplier_id；可空引用 |
| `term_id` | 结算条款标识 | 整数（INT） | FK→SETTLEMENT_TERM.term_id；可空引用 |
| `order_date` | 下单日期 | 日期（DATE） | 普通列 |
| `expected_date` | 期望到货日期 | 日期（DATE） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：草稿/已下达/部分到货/已到货/已关闭 |

#### 表 A-27　PURCHASE_ORDER_LINE（采购订单明细）

**用途**：采购订单明细行：耗材、数量、单价（联合主键）。

**主键**：联合主键 ``po_id` ＋ `line_no``。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `po_id` | 采购订单标识 | 整数（INT） | PK（联合主键组成之一）；FK→PURCHASE_ORDER.po_id；NOT NULL，随主体级联删除 |
| `line_no` | 行号（单据内顺序号，联合主键的一部分） | 整数（INT） | PK（联合主键组成之一） |
| `material_id` | 耗材标识 | 整数（INT） | FK→MATERIAL.material_id；NOT NULL，随主体级联删除 |
| `quantity` | 数量 | 小数（DECIMAL(10,2)） | 普通列 |
| `unit_price` | 单位价格 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-28　RECEIPT_NOTE（入库单）

**用途**：入库单头：关联采购订单与入库诊所。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `receipt_id` | 入库单标识 | 整数（INT） | PK，自增代理键 |
| `receipt_no` | 入库单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `po_id` | 采购订单标识 | 整数（INT） | FK→PURCHASE_ORDER.po_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；NOT NULL，随主体级联删除 |
| `received_date` | 入库日期 | 日期（DATE） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待入库/已入库/已冲销 |

#### 表 A-29　RECEIPT_LINE（入库单明细）

**用途**：入库单明细行：入库耗材与批次（联合主键）。

**主键**：联合主键 ``receipt_id` ＋ `line_no``。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `receipt_id` | 入库单标识 | 整数（INT） | PK（联合主键组成之一）；FK→RECEIPT_NOTE.receipt_id；NOT NULL，随主体级联删除 |
| `line_no` | 行号（单据内顺序号，联合主键的一部分） | 整数（INT） | PK（联合主键组成之一） |
| `material_id` | 耗材标识 | 整数（INT） | FK→MATERIAL.material_id；NOT NULL，随主体级联删除 |
| `batch_id` | 耗材批次标识 | 整数（INT） | FK→MATERIAL_BATCH.batch_id；NOT NULL，随主体级联删除 |
| `quantity` | 数量 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-30　MATERIAL_ISSUE（耗材领用）

**用途**：耗材领用：关联批次与治疗行，实现耗材-治疗成本追溯。

**主题域**：耗材与库存。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `issue_id` | 领用单标识 | 整数（INT） | PK，自增代理键 |
| `issue_no` | 领用单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `batch_id` | 耗材批次标识 | 整数（INT） | FK→MATERIAL_BATCH.batch_id；NOT NULL，随主体级联删除 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `quantity` | 数量 | 小数（DECIMAL(10,2)） | 普通列 |
| `issued_datetime` | 领用日期时间 | 日期时间（DATETIME） | 普通列 |
| `issued_by` | 领用人 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-31　SUPPLIER（供应商）

**用途**：供应商主档（行业惯例补充）。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `supplier_id` | 供应商标识 | 整数（INT） | PK，自增代理键 |
| `supplier_code` | 供应商编码 | 字符串（VARCHAR(100)） | UNIQUE |
| `supplier_name` | 供应商名称 | 字符串（VARCHAR(100)） | 普通列 |
| `contact_name` | 联系人姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `phone` | 电话号码 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-32　SETTLEMENT_TERM（结算条款）

**用途**：供应商结算条款：账期、退换比例、费用项（行业惯例补充）。

**主题域**：采购与供应商。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `term_id` | 结算条款标识 | 整数（INT） | PK，自增代理键 |
| `term_code` | 条款编码 | 字符串（VARCHAR(100)） | UNIQUE |
| `payment_days` | 账期天数 | 整数（INT） | 普通列 |
| `return_ratio` | 退换比例 | 小数（DECIMAL(10,2)） | 普通列 |
| `fee_items` | 费用项说明 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-33　STATEMENT（对账单）

**用途**：供应商对账单头：对账期间与状态（行业惯例补充）。

**主题域**：对账与付款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `statement_id` | 对账单标识 | 整数（INT） | PK，自增代理键 |
| `statement_no` | 对账单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `supplier_id` | 供应商标识 | 整数（INT） | FK→SUPPLIER.supplier_id；可空引用 |
| `period_start` | 对账期间开始日 | 字符串（VARCHAR(100)） | 普通列 |
| `period_end` | 对账期间结束日 | 字符串（VARCHAR(100)） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待确认/已确认/已核销 |

#### 表 A-34　STATEMENT_LINE（对账单明细）

**用途**：对账单明细行：来源类型+来源单号多态引用（行业惯例补充）。

**主键**：联合主键 ``statement_id` ＋ `line_no``。

**主题域**：对账与付款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `statement_id` | 对账单标识 | 整数（INT） | PK（联合主键组成之一）；FK→STATEMENT.statement_id；NOT NULL，随主体级联删除 |
| `line_no` | 行号（单据内顺序号，联合主键的一部分） | 整数（INT） | PK（联合主键组成之一） |
| `source_type` | 来源单据类型（多态引用，应用层校验） | 字符串（VARCHAR(100)） | 多态引用：指向 PURCHASE_ORDER／RECEIPT_NOTE／MATERIAL_ISSUE 等来源单据，应用层校验 |
| `source_no` | 来源单据号（多态引用，应用层校验） | 整数（VARCHAR(32)） | 多态引用：指向 PURCHASE_ORDER／RECEIPT_NOTE／MATERIAL_ISSUE 等来源单据，应用层校验 |
| `amount` | 金额 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-35　ACCOUNT_PAYABLE（应付账款）

**用途**：应付账款余额：按供应商/采购单挂账与核销状态（行业惯例补充）。

**主题域**：对账与付款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `payable_id` | 应付账款标识 | 整数（INT） | PK，自增代理键 |
| `supplier_id` | 供应商标识 | 整数（INT） | FK→SUPPLIER.supplier_id；可空引用 |
| `po_id` | 采购订单标识 | 整数（INT） | FK→PURCHASE_ORDER.po_id；NOT NULL，随主体级联删除 |
| `statement_id` | 对账单标识 | 整数（INT） | FK→STATEMENT.statement_id；NOT NULL，随主体级联删除 |
| `payable_no` | 应付单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `payable_amount` | 应付金额（由对账明细汇总；非规范化列，确认后冻结） | 小数（DECIMAL(10,2)） | 非规范化列：应付金额由对账明细汇总，方便检索与对账；确认后冻结，更正须追加调整记录 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：未付/部分付款/已结清 |

#### 表 A-36　PAYMENT_RECORD（付款记录）

**用途**：向供应商的付款记录（行业惯例补充）。

**主题域**：对账与付款。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `payment_record_id` | 付款记录标识 | 整数（INT） | PK，自增代理键 |
| `payable_id` | 应付账款标识 | 整数（INT） | FK→ACCOUNT_PAYABLE.payable_id；NOT NULL，随主体级联删除 |
| `supplier_id` | 供应商标识 | 整数（INT） | FK→SUPPLIER.supplier_id；可空引用 |
| `record_no` | 付款单号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `amount` | 金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `method` | 收款方式 | 字符串（VARCHAR(100)） | 普通列 |
| `paid_date` | 付款日期 | 日期（DATE） | 普通列 |

#### 表 A-37　OPERATING_EXPENSE（运营费用）

**用途**：门店运营费用：按季度记录，用于激励公式中扣除。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `expense_id` | 运营费用标识 | 整数（INT） | PK，自增代理键 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `quarter` | 季度（如 2026Q1） | 字符串（VARCHAR(100)） | 普通列 |
| `expense_category` | 费用类别 | 字符串（VARCHAR(100)） | 普通列 |
| `amount` | 金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `description` | 说明 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-38　EXPENSE_ALLOCATION（费用分摊）

**用途**：运营费用在门店/牙医间的分摊明细（行业惯例补充）。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `allocation_id` | 费用分摊标识 | 整数（INT） | PK，自增代理键 |
| `expense_id` | 运营费用标识 | 整数（INT） | FK→OPERATING_EXPENSE.expense_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `quarter` | 季度（如 2026Q1） | 字符串（VARCHAR(100)） | 普通列 |
| `allocated_amount` | 分摊金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `basis` | 分摊依据（面积/人次等） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-39　COST_VERSION（成本口径版本）

**用途**：成本口径版本：标准成本与核算口径的版本化管理。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `version_id` | 成本口径版本标识 | 整数（INT） | PK，自增代理键 |
| `version_no` | 版本号（业务编号，唯一） | 整数（VARCHAR(32)） | UNIQUE |
| `effective_date` | 生效日期 | 日期（DATE） | 普通列 |
| `description` | 说明 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-40　STANDARD_COST（项目标准成本）

**用途**：某口径版本下各治疗项目的标准成本。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `cost_id` | 标准成本标识 | 整数（INT） | PK，自增代理键 |
| `catalog_id` | 治疗项目标识 | 整数（INT） | FK→TREATMENT_CATALOG.catalog_id；NOT NULL，随主体级联删除 |
| `version_id` | 成本口径版本标识 | 整数（INT） | FK→COST_VERSION.version_id；NOT NULL，随主体级联删除 |
| `standard_cost` | 标准成本 | 小数（DECIMAL(10,2)） | 普通列 |
| `effective_date` | 生效日期 | 日期（DATE） | 普通列 |

#### 表 A-41　DENTIST_QUARTER_PERFORMANCE（牙医季度业绩）

**用途**：按季度跟踪每位牙医的收入、成本、运营费用（激励制度依据）。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `perf_id` | 牙医季度业绩标识 | 整数（INT） | PK，自增代理键 |
| `dentist_id` | 牙医标识 | 整数（INT） | FK→DENTIST.dentist_id；NOT NULL，随主体级联删除 |
| `quarter` | 季度（如 2026Q1） | 字符串（VARCHAR(100)） | UNIQUE |
| `revenue_amount` | 季度收入金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `cost_amount` | 季度医疗用品成本金额 | 小数（DECIMAL(10,2)） | 普通列 |
| `operating_expense_amount` | 季度运营费用金额 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-42　INCENTIVE_FUND（激励基金）

**用途**：激励基金：净利润（收入-医疗用品成本-运营费用）×10%，按季度分配。

**主题域**：核算域。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `fund_id` | 激励基金标识 | 整数（INT） | PK，自增代理键 |
| `perf_id` | 牙医季度业绩标识 | 整数（INT） | FK→DENTIST_QUARTER_PERFORMANCE.perf_id；NOT NULL，随主体级联删除 |
| `quarter` | 季度（如 2026Q1） | 字符串（VARCHAR(100)） | UNIQUE |
| `net_profit` | 净利润（收入-医疗用品成本-运营费用；非规范化列，季度核算快照） | 小数（DECIMAL(10,2)） | 非规范化列：净利润（收入-医疗用品成本-每位牙医运营费用）为季度核算快照，是激励发放的依据事实，跨多表计算后落一次账，非实时派生列 |
| `fund_rate` | 基金计提比例（10%） | 小数（DECIMAL(10,2)） | 普通列 |
| `fund_amount` | 激励基金金额 | 小数（DECIMAL(10,2)） | 普通列 |

#### 表 A-43　COMPLAINT（投诉）

**用途**：患者投诉受理与处理跟踪（行业惯例补充）。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `complaint_id` | 投诉标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `channel` | 渠道（电话/到店/在线等） | 字符串（VARCHAR(100)） | 普通列 |
| `content` | 投诉内容 | 字符串（VARCHAR(100)） | 普通列 |
| `filed_date` | 受理日期 | 日期（DATE） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待处理/处理中/已回访/已关闭 |
| `resolution` | 处理结果 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-44　QUALITY_INCIDENT（质量事件）

**用途**：医疗质量事件登记与整改跟踪（行业惯例补充）。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `incident_id` | 质量事件标识 | 整数（INT） | PK，自增代理键 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `incident_type` | 事件类型 | 字符串（VARCHAR(100)） | 普通列 |
| `description` | 说明 | 字符串（VARCHAR(100)） | 普通列 |
| `occurred_date` | 发生日期 | 日期（DATE） | 普通列 |
| `severity` | 严重程度 | 字符串（VARCHAR(100)） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待整改/整改中/已关闭 |

#### 表 A-45　FOLLOWUP_RECALL（复诊召回）

**用途**：复诊召回：到期提醒患者复查（行业惯例补充）。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `recall_id` | 召回标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；可空引用 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `due_date` | 应召回日期 | 日期（DATE） | 普通列 |
| `channel` | 渠道（电话/到店/在线等） | 字符串（VARCHAR(100)） | 普通列 |
| `status` | 状态 | 字符串（VARCHAR(100)） | 枚举取值见 A.3.3：待联系/已通知/已完成/已失访 |
| `completed_date` | 完成日期 | 日期（DATE） | 普通列 |

#### 表 A-46　DISINFECTION_RECORD（消毒感控记录）

**用途**：器械消毒与感控记录（行业惯例补充）。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `disinfection_id` | 消毒记录标识 | 整数（INT） | PK，自增代理键 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `record_date` | 记录日期 | 日期（DATE） | 普通列 |
| `operator_name` | 操作人姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `scope` | 消毒范围 | 字符串（VARCHAR(100)） | 普通列 |
| `result` | 结果 | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-47　RECORD_ACCESS_LOG（病历调阅留痕）

**用途**：跨门店病历调阅授权留痕（患者跨诊所就诊）。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `access_log_id` | 调阅留痕标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `clinic_id` | 门店标识 | 整数（INT） | FK→CLINIC.clinic_id；可空引用 |
| `operator_name` | 操作人姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `access_datetime` | 调阅日期时间 | 日期时间（DATETIME） | 普通列 |
| `purpose` | 调阅事由 | 字符串（VARCHAR(100)） | 普通列 |
| `authorization_ref` | 授权依据（患者授权编号等） | 字符串（VARCHAR(100)） | 普通列 |

#### 表 A-48　AUDIT_LOG（病历修改留痕）

**用途**：病历修改留痕：改前值/改后值/操作人。

**主题域**：质量与合规。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `audit_log_id` | 修改留痕标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；NOT NULL，随主体级联删除 |
| `record_table` | 被修改的记录所在表 | 字符串（VARCHAR(100)） | 普通列 |
| `record_id_ref` | 被修改记录的主键值（多态引用） | 字符串（VARCHAR(100)） | 多态引用：指向 record_table 所指表的主键值 |
| `changed_field` | 被修改字段 | 字符串（VARCHAR(100)） | 普通列 |
| `old_value` | 修改前值 | 字符串（VARCHAR(100)） | 普通列 |
| `new_value` | 修改后值 | 字符串（VARCHAR(100)） | 普通列 |
| `operator_name` | 操作人姓名 | 字符串（VARCHAR(100)） | 普通列 |
| `changed_datetime` | 修改日期时间 | 日期时间（DATETIME） | 普通列 |

#### 表 A-49　IMAGE_RECORD（影像记录）

**用途**：口内片/全景片/CBCT 影像，按患者与牙位（FDI）索引（行业惯例补充）。

**主题域**：诊疗记录。

| 字段 | 中文含义 | 数据类型 | 约束与说明 |
|---|---|---|---|
| `image_id` | 影像标识 | 整数（INT） | PK，自增代理键 |
| `patient_id` | 患者标识 | 整数（INT） | FK→PATIENT.patient_id；可空引用 |
| `visit_id` | 就诊标识 | 整数（INT） | FK→VISIT.visit_id；NOT NULL，随主体级联删除 |
| `tooth_fdi` | 牙位（FDI 编号；全口项目留空） | 字符串（VARCHAR(100)） | FDI 牙位编号，全口项目留空 |
| `image_type` | 影像类型（口内片/全景片/CBCT） | 字符串（VARCHAR(100)） | 普通列 |
| `image_url` | 影像存储路径 | 字符串（VARCHAR(100)） | 普通列 |
| `taken_datetime` | 拍摄日期时间 | 日期时间（DATETIME） | 普通列 |

### A.5 索引与外键约束清单

#### A.5.1 外键约束全量清单（58 条）

下表按主题域顺序列出全部外键。「业务含义」一列说明这条外键支撑什么业务约束，
全部 58 条的关系定义与第六章图 10 的数据库总图连线一一对应。

| 序号 | 子表.列 | → 父表.主键 | 基数 | 业务含义 |
|---|---|---|---|---|
| 1 | `ALLERGY.patient_id` | `PATIENT.patient_id` | N:1 | 一位患者可登记多条过敏症，就诊前必须逐条提示；删除患者时随主体级联 |
| 2 | `MEDICAL_HISTORY.patient_id` | `PATIENT.patient_id` | N:1 | 病史挂在患者主档上，支撑跨门店调阅既往病症 |
| 3 | `MEMBER.patient_id` | `PATIENT.patient_id` | N:1 | 一名患者对应一条会员档案，等级与积分按患者唯一 |
| 4 | `STAFF.clinic_id` | `CLINIC.clinic_id` | N:1 | 门店非牙医员工归属唯一门店，用于按门店统计人力 |
| 5 | `ROSTER.dentist_id` | `DENTIST.dentist_id` | N:1 | 接诊安排指定出诊牙医；牙医不专属门店，靠本表实现多门店轮转 |
| 6 | `ROSTER.clinic_id` | `CLINIC.clinic_id` | N:1 | 接诊安排指定出诊门店，一次排班只属于一家门店 |
| 7 | `APPOINTMENT.patient_id` | `PATIENT.patient_id` | N:1 | 一位患者可有多条预约，取消率按患者统计的依据 |
| 8 | `APPOINTMENT.roster_id` | `ROSTER.roster_id` | N:1 | 一次预约占用一条接诊安排，接诊牙医与就诊门店由此确定（案例：通话中安排一位牙医接诊） |
| 9 | `VISIT.appointment_id` | `APPOINTMENT.appointment_id` | 1:0..1 | 一次预约最多生成一次就诊（1:0..1），取消与爽约由此与真实就诊分开 |
| 10 | `VISIT.clinic_id` | `CLINIC.clinic_id` | N:1 | 记录本次实际就诊门店；患者跨门店就诊即由此区分 |
| 11 | `TREATMENT_PLAN.visit_id` | `VISIT.visit_id` | N:1 | 治疗计划属于某次就诊，就诊期间可挂号计划与追加项目 |
| 12 | `TREATMENT_ITEM.catalog_id` | `TREATMENT_CATALOG.catalog_id` | N:1 | 治疗行引用标准项目目录，取得标准单位价格（实际以成交价为准） |
| 13 | `TREATMENT_ITEM.dentist_id` | `DENTIST.dentist_id` | N:1 | 记录本行治疗的执行牙医，支撑单牙医产值与季度激励核算 |
| 14 | `INVOICE.visit_id` | `VISIT.visit_id` | N:1 | 组合外键且不为空：每次就诊生成一张结算单，逐行明细来自该次就诊的治疗数据 |
| 15 | `PAYMENT.invoice_id` | `INVOICE.invoice_id` | N:1 | 一张结算单可分期多次收款，未收金额＝总价-已收金额（视图计算） |
| 16 | `INSTALLMENT_PLAN.invoice_id` | `INVOICE.invoice_id` | N:1 | 大额账单的分期计划挂在结算单上 |
| 17 | `INSURANCE_POLICY.patient_id` | `PATIENT.patient_id` | N:1 | 保单属于患者，理赔时按发票与保单双向关联 |
| 18 | `INSURANCE_CLAIM.invoice_id` | `INVOICE.invoice_id` | N:1 | 理赔由某张结算单发起 |
| 19 | `INSURANCE_CLAIM.policy_id` | `INSURANCE_POLICY.policy_id` | N:1 | 理赔引用具体保单，决定承保范围与赔付上限 |
| 20 | `MATERIAL_BATCH.material_id` | `MATERIAL.material_id` | N:1 | 同一耗材按批号/序列号分别建行，用于效期与追溯 |
| 21 | `STOCK_LEDGER.clinic_id` | `CLINIC.clinic_id` | N:1 | 库存余额按门店建账，15 家门店各自结算 |
| 22 | `STOCK_LEDGER.material_id` | `MATERIAL.material_id` | N:1 | 库存余额按（门店×耗材）唯一，只由流水推动 |
| 23 | `STOCK_MOVEMENT.ledger_id` | `STOCK_LEDGER.ledger_id` | N:1 | 每笔出入库流水挂到余额账上，余额＝流水累计 |
| 24 | `PURCHASE_ORDER.supplier_id` | `SUPPLIER.supplier_id` | N:1 | 采购订单指定供应商 |
| 25 | `PURCHASE_ORDER.term_id` | `SETTLEMENT_TERM.term_id` | N:1 | 采购订单选用结算条款，决定账期与退换比例 |
| 26 | `PURCHASE_ORDER_LINE.material_id` | `MATERIAL.material_id` | N:1 | 采购明细指定耗材，与数量单价构成订货内容 |
| 27 | `RECEIPT_NOTE.po_id` | `PURCHASE_ORDER.po_id` | N:1 | 入库单对应采购订单，用于到货跟踪 |
| 28 | `RECEIPT_NOTE.clinic_id` | `CLINIC.clinic_id` | N:1 | 入库单落到收货门店，与库存余额账对应 |
| 29 | `RECEIPT_LINE.material_id` | `MATERIAL.material_id` | N:1 | 入库明细指定耗材 |
| 30 | `RECEIPT_LINE.batch_id` | `MATERIAL_BATCH.batch_id` | N:1 | 入库明细落到具体批次，形成批次库存与效期基础 |
| 31 | `MATERIAL_ISSUE.batch_id` | `MATERIAL_BATCH.batch_id` | N:1 | 领用登记到批号或序列号，实现耗材-治疗成本追溯（激励制度算成本的输入） |
| 32 | `MATERIAL_ISSUE.visit_id` | `VISIT.visit_id` | N:1 | 领用挂在就诊上，把耗材成本归集到治疗项目与牙医 |
| 33 | `STATEMENT.supplier_id` | `SUPPLIER.supplier_id` | N:1 | 对账单按供应商出具，对账期间内该供应商的采购与入库汇成一张账单 |
| 34 | `ACCOUNT_PAYABLE.supplier_id` | `SUPPLIER.supplier_id` | N:1 | 应付账款按供应商挂账 |
| 35 | `ACCOUNT_PAYABLE.po_id` | `PURCHASE_ORDER.po_id` | N:1 | 应付账款可追溯到采购订单 |
| 36 | `ACCOUNT_PAYABLE.statement_id` | `STATEMENT.statement_id` | N:1 | 应付账款由对账单确认生成 |
| 37 | `PAYMENT_RECORD.payable_id` | `ACCOUNT_PAYABLE.payable_id` | N:1 | 付款记录核销应付账款 |
| 38 | `PAYMENT_RECORD.supplier_id` | `SUPPLIER.supplier_id` | N:1 | 付款记录同时按供应商汇总，便于账期分析 |
| 39 | `OPERATING_EXPENSE.clinic_id` | `CLINIC.clinic_id` | N:1 | 运营费用按门店季度记录，是激励公式的扣减项 |
| 40 | `EXPENSE_ALLOCATION.expense_id` | `OPERATING_EXPENSE.expense_id` | N:1 | 费用分摊明细挂在运营费用上 |
| 41 | `EXPENSE_ALLOCATION.clinic_id` | `CLINIC.clinic_id` | N:1 | 分摊结果落到门店，支撑门店损益 |
| 42 | `STANDARD_COST.catalog_id` | `TREATMENT_CATALOG.catalog_id` | N:1 | 项目标准成本按治疗项目口径维护 |
| 43 | `STANDARD_COST.version_id` | `COST_VERSION.version_id` | N:1 | 标准成本挂在成本口径版本下，避免口径变更引起争议 |
| 44 | `DENTIST_QUARTER_PERFORMANCE.dentist_id` | `DENTIST.dentist_id` | N:1 | 按季度跟踪每位牙医的收入、成本与运营费用 |
| 45 | `INCENTIVE_FUND.perf_id` | `DENTIST_QUARTER_PERFORMANCE.perf_id` | N:1 | 激励基金基于牙医季度业绩计算：净利润×10% |
| 46 | `COMPLAINT.patient_id` | `PATIENT.patient_id` | N:1 | 投诉关联患者，可与既往就诊合并查看 |
| 47 | `COMPLAINT.visit_id` | `VISIT.visit_id` | N:1 | 投诉指向具体就诊，便于定位责任牙医与门店 |
| 48 | `COMPLAINT.clinic_id` | `CLINIC.clinic_id` | N:1 | 投诉按门店统计，支撑门店质量对比 |
| 49 | `QUALITY_INCIDENT.visit_id` | `VISIT.visit_id` | N:1 | 质量事件指向具体就诊 |
| 50 | `QUALITY_INCIDENT.clinic_id` | `CLINIC.clinic_id` | N:1 | 质量事件按门店汇总整改 |
| 51 | `FOLLOWUP_RECALL.patient_id` | `PATIENT.patient_id` | N:1 | 复诊召回针对患者 |
| 52 | `FOLLOWUP_RECALL.visit_id` | `VISIT.visit_id` | N:1 | 召回由上次就诊推算到期日 |
| 53 | `DISINFECTION_RECORD.clinic_id` | `CLINIC.clinic_id` | N:1 | 消毒感控记录按门店按日登记 |
| 54 | `RECORD_ACCESS_LOG.patient_id` | `PATIENT.patient_id` | N:1 | 跨门店调阅病历按患者留痕（案例：患者会在多个诊所就诊） |
| 55 | `RECORD_ACCESS_LOG.clinic_id` | `CLINIC.clinic_id` | N:1 | 记录调阅发生的门店，用于授权审计 |
| 56 | `AUDIT_LOG.patient_id` | `PATIENT.patient_id` | N:1 | 病历修改留痕按患者归档，记录改前值/改后值 |
| 57 | `IMAGE_RECORD.patient_id` | `PATIENT.patient_id` | N:1 | 影像属于患者病历，按患者索引 |
| 58 | `IMAGE_RECORD.visit_id` | `VISIT.visit_id` | N:1 | 影像产生于某次就诊，配合牙位（FDI）索引 |

三点说明。

第一，`VISIT.appointment_id → APPOINTMENT.appointment_id`（1:0..1）与其余 N:1 外键不同：
一次预约最多生成一次就诊，取消与爽约因此不会产生就诊记录——这正是患者责任取消率可算的前提。
第二，6 张联合主键的明细表还有 7 个列同时兼任外键，它们在上表 58 条之外，因为按模型定义它们归类为主键列（`kind="pk"`）而非纯外键列：

| 序号 | 子表.列 | → 父表.主键 | 说明 |
|---|---|---|---|
| 1 | `DENTIST_QUALIFICATION.dentist_id` | `DENTIST.dentist_id` | 联合主键组成部分，同时指向父表主键 |
| 2 | `DENTIST_QUALIFICATION.qualification_id` | `QUALIFICATION.qualification_id` | 联合主键组成部分，同时指向父表主键 |
| 3 | `TREATMENT_ITEM.visit_id` | `VISIT.visit_id` | 联合主键组成部分，同时指向父表主键 |
| 4 | `INVOICE_LINE.invoice_id` | `INVOICE.invoice_id` | 联合主键组成部分，同时指向父表主键 |
| 5 | `PURCHASE_ORDER_LINE.po_id` | `PURCHASE_ORDER.po_id` | 联合主键组成部分，同时指向父表主键 |
| 6 | `RECEIPT_LINE.receipt_id` | `RECEIPT_NOTE.receipt_id` | 联合主键组成部分，同时指向父表主键 |
| 7 | `STATEMENT_LINE.statement_id` | `STATEMENT.statement_id` | 联合主键组成部分，同时指向父表主键 |

这 7 个列在 A.4 中标注为「PK（联合主键组成之一）；FK→父表.列」，声明外键时按普通外键一并建 `FOREIGN KEY` 约束即可。
第三，全设计有两处引用数据库外键无法表达，须由应用层兜底（第六章已登记）：
`STATEMENT_LINE.source_type ＋ source_no` 与 `STOCK_MOVEMENT.source_type ＋ source_no`，
它们指向采购订单／入库单／领用单等多张表之一，属多态引用；应用层在写库前校验来源单据确实存在且口径一致。

#### A.5.2 索引建议

索引按「主键 → 外键 → 高频查询 → 唯一」四类建，够用即可，避免为每列建索引反而拖慢写入。

**1) 主键索引。** 每张表的 `PRIMARY KEY` 自动建唯一聚簇索引，本模型 49 张表全覆盖：
单列代理键表建立于 `*_id`；6 张联合主键表建立于 `(单据主键, line_no)` 或 `(dentist_id, qualification_id)`。
联合主键的列顺序按「先父表键、后行号」——`TREATMENT_ITEM(visit_id, line_no)` 的排序即「某次就诊的全部治疗行按序排列」，
取一次就诊的明细可以直接走主键索引，不必回表排序。

**2) 外键索引。** 外键列不会自动建索引，但本模型 58 条外键中的绝大多数都会出现在查询条件或联接里，
必须为每条外键的**子表列**单独建索引（父表侧由主键索引覆盖）：

- 单列外键索引：`ALLERGY(patient_id)`、`APPOINTMENT(patient_id)`、`APPOINTMENT(roster_id)`、
  `VISIT(appointment_id)`、`VISIT(clinic_id)`、`TREATMENT_ITEM(visit_id)`、`INVOICE(visit_id)`、
  `INVOICE_LINE(invoice_id)`、`PAYMENT(invoice_id)`、`STOCK_MOVEMENT(ledger_id)`、`RECEIPT_LINE(receipt_id)` 等，逐条对应 A.5.1 清单。
- 复合外键按查询前缀建复合索引：`STOCK_LEDGER(clinic_id, material_id)`（与唯一约束同一索引）、
  `TREATMENT_ITEM(visit_id, dentist_id)`（按牙医统计某次就诊的治疗行）、
  `RECEIPT_LINE(receipt_id, batch_id)`（按批次回查入库来源）、`MATERIAL_ISSUE(visit_id, batch_id)`（按就诊归集耗材成本）。
- 说明：组合外键带 `ON DELETE CASCADE`，没有索引时父行删除会全表扫描子表，因此这类索引是必需的，不是优化项。

**3) 高频查询索引。** 按系统要回答的问题（第六章的使用场景与激励核算）建以下几组：

| 查询场景 | 建议索引 | 支撑的业务 |
|---|---|---|
| 患者档案与就诊史（跨门店） | `VISIT(patient_id, visit_datetime)`、`APPOINTMENT(patient_id, appointment_datetime)` | 接待员按患者调取既往治疗与预约（UC-01 步骤 2） |
| 按门店、按季度汇总 | `VISIT(clinic_id, visit_datetime)`、`INVOICE(invoice_id, invoice_date)`、`OPERATING_EXPENSE(clinic_id, quarter)` | 15 家门店经营对比与季度运营费用归集 |
| 按牙医核算价值 | `TREATMENT_ITEM(dentist_id, visit_id)`、`ROSTER(dentist_id, roster_date)`、`DENTIST_QUARTER_PERFORMANCE(dentist_id, quarter)` | 单牙医产值与季度激励（案例：净利润的 10% 作为激励基金） |
| 取消率统计 | `APPOINTMENT(status, appointment_datetime)`、`APPOINTMENT(cancellation_category)` | 按门店／牙医／季度统计患者责任取消率（案例把高取消率列为危险信号） |
| 结算与欠费 | `INVOICE(invoice_date, status)`、`PAYMENT(invoice_id, paid_datetime)`、`INSURANCE_CLAIM(status)` | 开票口径统一、未收金额与理赔跟踪（UC-02） |
| 耗材效期与追溯 | `MATERIAL_BATCH(expiry_date)`、`MATERIAL_BATCH(material_id, expiry_date)`、`MATERIAL_ISSUE(batch_id)` | 近效期预警与种植体等高值耗材的批号追溯 |
| 库存与采购 | `STOCK_MOVEMENT(ledger_id, moved_datetime)`、`PURCHASE_ORDER(supplier_id, order_date)`、`STATEMENT(supplier_id, period_start)` | 余额由流水推动、账期与对账 |
| 成本口径 | `STANDARD_COST(catalog_id, version_id)`、`COST_VERSION(effective_date)` | 按版本取当期标准成本，避免口径变更引起争议 |
| 质量与合规 | `COMPLAINT(clinic_id, filed_date)`、`QUALITY_INCIDENT(clinic_id, occurred_date)`、`FOLLOWUP_RECALL(due_date, status)`、`RECORD_ACCESS_LOG(patient_id, access_datetime)` | 门店质量对比、召回到期提醒、跨门店调阅审计 |
| 病历留痕 | `AUDIT_LOG(patient_id, changed_datetime)`、`AUDIT_LOG(record_table, record_id_ref)` | 按患者或按被改记录回放修改历史 |
| 影像调阅 | `IMAGE_RECORD(patient_id, taken_datetime)`、`IMAGE_RECORD(visit_id, tooth_fdi)` | 按患者或按牙位调取影像 |

**4) 唯一索引。** A.3.3 第 4 条列出的唯一约束由 `UNIQUE` 索引实现（业务编号、`STOCK_LEDGER(clinic_id, material_id)`、
`DENTIST_QUARTER_PERFORMANCE(dentist_id, quarter)`、`INCENTIVE_FUND(perf_id, quarter)`）。
这些索引同时承担查询职责：单号查询（接待员按单号检索）直接命中唯一索引。

**5) 不该建的索引。** 低基数列单独建索引无意义——`treated`（两值）、`status`、`direction`、`severity`、`quarter` 判断是否建索引要看它是否作为复合索引的前缀列（如上文 `APPOINTMENT(status, appointment_datetime)` 是有用的，单列 `status` 则不是）；
大文本列（`content`、`resolution`、`description`、`special_notes`）不建普通索引，需要检索时另建全文索引。

