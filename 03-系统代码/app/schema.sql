-- ADC 诊疗管理系统 建库脚本（由 tools/_dump_schema.py 从 data/adc.db 导出）
-- 用法：python app/server.py --init-only
-- 说明：表结构由 生成脚本/db_model9.py 设计，本文件是它落库后的实际形态，
--       含后续追加的 SEQ 发号表、NOTICE 通知表与防并发唯一索引。


-- table: ACCOUNT_PAYABLE
CREATE TABLE IF NOT EXISTS ACCOUNT_PAYABLE (
  payable_id               INTEGER PRIMARY KEY,
  supplier_id              INTEGER REFERENCES SUPPLIER,
  po_id                    INTEGER REFERENCES PURCHASE_ORDER,
  statement_id             INTEGER REFERENCES STATEMENT,
  payable_no               INTEGER,
  payable_amount           REAL,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: ALLERGY
CREATE TABLE IF NOT EXISTS ALLERGY (
  allergy_id               INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  allergy_name             TEXT,
  allergen_type            TEXT,
  severity                 TEXT,
  reaction                 TEXT,
  discovered_date          TEXT,
  is_confirmed             INTEGER,
  confirming_dentist_id    INTEGER REFERENCES DENTIST
);

-- table: APPOINTMENT
CREATE TABLE IF NOT EXISTS APPOINTMENT (
  appointment_id           INTEGER PRIMARY KEY,
  appointment_no           INTEGER,
  patient_id               INTEGER REFERENCES PATIENT,
  roster_id                INTEGER REFERENCES ROSTER,
  appointment_datetime     TEXT,
  status                   TEXT,
  cancellation_category    TEXT,
  visit_reason             TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: AUDIT_LOG
CREATE TABLE IF NOT EXISTS AUDIT_LOG (
  audit_log_id             INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  record_table             TEXT,
  record_id_ref            TEXT,
  changed_field            TEXT,
  old_value                TEXT,
  new_value                TEXT,
  operator_name            TEXT,
  changed_datetime         TEXT
);

-- table: CLINIC
CREATE TABLE IF NOT EXISTS CLINIC (
  clinic_id                INTEGER PRIMARY KEY,
  clinic_no                INTEGER,
  clinic_name              TEXT,
  postal_address           TEXT,
  region                   TEXT,
  manager_name             TEXT,
  phone                    TEXT,
  email                    TEXT,
  office_area_sqm          REAL,
  license_no               TEXT,
  license_valid_until      TEXT,
  service_scope            TEXT,
  opened_date              TEXT
);

-- table: CLINIC_CALENDAR
CREATE TABLE IF NOT EXISTS CLINIC_CALENDAR (
  calendar_id              INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  weekday                  INTEGER,
  open_time                TEXT,
  close_time               TEXT,
  is_operating             INTEGER,
  chair_count              INTEGER
);

-- table: COMPLAINT
CREATE TABLE IF NOT EXISTS COMPLAINT (
  complaint_id             INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  visit_id                 INTEGER REFERENCES VISIT,
  clinic_id                INTEGER REFERENCES CLINIC,
  channel                  TEXT,
  content                  TEXT,
  filed_date               TEXT,
  status                   TEXT,
  resolution               TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: COST_VERSION
CREATE TABLE IF NOT EXISTS COST_VERSION (
  version_id               INTEGER PRIMARY KEY,
  version_no               INTEGER,
  effective_date           TEXT,
  description              TEXT
);

-- table: DENTIST
CREATE TABLE IF NOT EXISTS DENTIST (
  dentist_id               INTEGER PRIMARY KEY,
  employee_no              INTEGER,
  name                     TEXT,
  date_of_birth            TEXT,
  home_address             TEXT,
  phone                    TEXT,
  email                    TEXT,
  active                   INTEGER
);

-- table: DENTIST_LEAVE
CREATE TABLE IF NOT EXISTS DENTIST_LEAVE (
  leave_id                 INTEGER PRIMARY KEY,
  dentist_id               INTEGER REFERENCES DENTIST,
  clinic_id                INTEGER REFERENCES CLINIC,
  leave_start              TEXT,
  leave_end                TEXT,
  leave_type               TEXT,
  leave_reason             TEXT,
  approval_status          TEXT,
  approver_staff_id        INTEGER REFERENCES STAFF,
  approved_date            TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: DENTIST_QUALIFICATION
CREATE TABLE IF NOT EXISTS DENTIST_QUALIFICATION (
  dentist_id               INTEGER REFERENCES DENTIST,
  qualification_id         INTEGER REFERENCES QUALIFICATION,
  obtained_date            TEXT,
  certificate_no           TEXT,
  valid_until              TEXT,
  cert_status              TEXT,
  PRIMARY KEY (dentist_id, qualification_id)
);

-- table: DENTIST_QUARTER_PERFORMANCE
CREATE TABLE IF NOT EXISTS DENTIST_QUARTER_PERFORMANCE (
  perf_id                  INTEGER PRIMARY KEY,
  dentist_id               INTEGER REFERENCES DENTIST,
  quarter                  TEXT,
  revenue_amount           REAL,
  cost_amount              REAL,
  operating_expense_amount REAL,
  visit_count              INTEGER,
  patient_count            INTEGER,
  recall_rate              REAL,
  complaint_count          INTEGER,
  quality_incident_count   INTEGER,
  chair_utilization        REAL,
  work_days                INTEGER
);

-- table: DISINFECTION_RECORD
CREATE TABLE IF NOT EXISTS DISINFECTION_RECORD (
  disinfection_id          INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  record_date              TEXT,
  operator_name            TEXT,
  scope                    TEXT,
  result                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: EXPENSE_ALLOCATION
CREATE TABLE IF NOT EXISTS EXPENSE_ALLOCATION (
  allocation_id            INTEGER PRIMARY KEY,
  expense_id               INTEGER REFERENCES OPERATING_EXPENSE,
  clinic_id                INTEGER REFERENCES CLINIC,
  quarter                  TEXT,
  allocated_amount         REAL,
  basis                    TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: FOLLOWUP_RECALL
CREATE TABLE IF NOT EXISTS FOLLOWUP_RECALL (
  recall_id                INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  visit_id                 INTEGER REFERENCES VISIT,
  due_date                 TEXT,
  channel                  TEXT,
  status                   TEXT,
  completed_date           TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: IMAGE_RECORD
CREATE TABLE IF NOT EXISTS IMAGE_RECORD (
  image_id                 INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  visit_id                 INTEGER REFERENCES VISIT,
  tooth_fdi                TEXT,
  image_type               TEXT,
  image_url                TEXT,
  taken_datetime           TEXT
);

-- table: INCENTIVE_FUND
CREATE TABLE IF NOT EXISTS INCENTIVE_FUND (
  fund_id                  INTEGER PRIMARY KEY,
  perf_id                  INTEGER REFERENCES DENTIST_QUARTER_PERFORMANCE,
  quarter                  TEXT,
  net_profit               REAL,
  fund_rate                REAL,
  fund_amount              REAL,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: INSTALLMENT_PLAN
CREATE TABLE IF NOT EXISTS INSTALLMENT_PLAN (
  installment_id           INTEGER PRIMARY KEY,
  invoice_id               INTEGER REFERENCES INVOICE,
  installment_count        INTEGER,
  first_due_date           TEXT,
  status                   TEXT
);

-- table: INSURANCE_CLAIM
CREATE TABLE IF NOT EXISTS INSURANCE_CLAIM (
  claim_id                 INTEGER PRIMARY KEY,
  invoice_id               INTEGER REFERENCES INVOICE,
  policy_id                INTEGER REFERENCES INSURANCE_POLICY,
  submitted_date           TEXT,
  claimed_amount           REAL,
  approved_amount          REAL,
  status                   TEXT
);

-- table: INSURANCE_POLICY
CREATE TABLE IF NOT EXISTS INSURANCE_POLICY (
  policy_id                INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  insurer_name             TEXT,
  policy_no                INTEGER,
  coverage_scope           TEXT,
  valid_until              TEXT
);

-- table: INVOICE
CREATE TABLE IF NOT EXISTS INVOICE (
  invoice_id               INTEGER PRIMARY KEY,
  invoice_no               INTEGER,
  visit_id                 INTEGER REFERENCES VISIT,
  invoice_date             TEXT,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: INVOICE_LINE
CREATE TABLE IF NOT EXISTS INVOICE_LINE (
  invoice_id               INTEGER REFERENCES INVOICE,
  line_no                  INTEGER,
  item_name                TEXT,
  units_used               TEXT,
  unit_price               REAL,
  line_subtotal            REAL,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT,
  PRIMARY KEY (invoice_id, line_no)
);

-- table: MATERIAL
CREATE TABLE IF NOT EXISTS MATERIAL (
  material_id              INTEGER PRIMARY KEY,
  material_code            TEXT,
  material_name            TEXT,
  unit                     TEXT,
  is_high_value            INTEGER,
  reorder_point            TEXT
);

-- table: MATERIAL_BATCH
CREATE TABLE IF NOT EXISTS MATERIAL_BATCH (
  batch_id                 INTEGER PRIMARY KEY,
  material_id              INTEGER REFERENCES MATERIAL,
  batch_serial_no          INTEGER,
  expiry_date              TEXT,
  purchase_unit_price      REAL
, received_qty REAL DEFAULT 0, issued_qty REAL DEFAULT 0);

-- table: MATERIAL_ISSUE
CREATE TABLE IF NOT EXISTS MATERIAL_ISSUE (
  issue_id                 INTEGER PRIMARY KEY,
  issue_no                 INTEGER,
  batch_id                 INTEGER REFERENCES MATERIAL_BATCH,
  visit_id                 INTEGER REFERENCES VISIT,
  quantity                 REAL,
  issued_datetime          TEXT,
  issued_by                TEXT
, clinic_id INTEGER);

-- table: MEDICAL_HISTORY
CREATE TABLE IF NOT EXISTS MEDICAL_HISTORY (
  history_id               INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  record_date              TEXT,
  condition_description    TEXT,
  status                   TEXT
);

-- table: MEMBER
CREATE TABLE IF NOT EXISTS MEMBER (
  member_id                INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  member_no                INTEGER,
  member_level             TEXT,
  joined_date              TEXT
);

-- table: NOTICE
CREATE TABLE IF NOT EXISTS NOTICE (
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

-- table: OPERATING_EXPENSE
CREATE TABLE IF NOT EXISTS OPERATING_EXPENSE (
  expense_id               INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  quarter                  TEXT,
  expense_category         TEXT,
  amount                   REAL,
  description              TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: PATIENT
CREATE TABLE IF NOT EXISTS PATIENT (
  patient_id               INTEGER PRIMARY KEY,
  patient_no               INTEGER,
  name                     TEXT,
  date_of_birth            TEXT,
  billing_address          TEXT,
  phone                    TEXT,
  email                    TEXT,
  id_card_no               TEXT,
  insurance_card_no        TEXT,
  occupation               TEXT,
  source_channel           TEXT,
  first_visit_date         TEXT,
  emergency_contact_name   TEXT,
  emergency_contact_phone  TEXT,
  account_id               INTEGER REFERENCES USER_ACCOUNT
);

-- table: PAYMENT
CREATE TABLE IF NOT EXISTS PAYMENT (
  payment_id               INTEGER PRIMARY KEY,
  invoice_id               INTEGER REFERENCES INVOICE,
  payment_no               INTEGER,
  amount                   REAL,
  method                   TEXT,
  paid_datetime            TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
, refund_reason TEXT, refund_no TEXT);

-- table: PAYMENT_RECORD
CREATE TABLE IF NOT EXISTS PAYMENT_RECORD (
  payment_record_id        INTEGER PRIMARY KEY,
  payable_id               INTEGER REFERENCES ACCOUNT_PAYABLE,
  supplier_id              INTEGER REFERENCES SUPPLIER,
  record_no                INTEGER,
  amount                   REAL,
  method                   TEXT,
  paid_date                TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: PURCHASE_ORDER
CREATE TABLE IF NOT EXISTS PURCHASE_ORDER (
  po_id                    INTEGER PRIMARY KEY,
  po_no                    INTEGER,
  supplier_id              INTEGER REFERENCES SUPPLIER,
  term_id                  INTEGER REFERENCES SETTLEMENT_TERM,
  order_date               TEXT,
  expected_date            TEXT,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
, clinic_id INTEGER REFERENCES CLINIC(clinic_id));

-- table: PURCHASE_ORDER_LINE
CREATE TABLE IF NOT EXISTS PURCHASE_ORDER_LINE (
  po_id                    INTEGER REFERENCES PURCHASE_ORDER,
  line_no                  INTEGER,
  material_id              INTEGER REFERENCES MATERIAL,
  quantity                 REAL,
  unit_price               REAL,
  PRIMARY KEY (po_id, line_no)
);

-- table: QUALIFICATION
CREATE TABLE IF NOT EXISTS QUALIFICATION (
  qualification_id         INTEGER PRIMARY KEY,
  qualification_code       TEXT,
  qualification_name       TEXT,
  issuing_body             TEXT
);

-- table: QUALITY_INCIDENT
CREATE TABLE IF NOT EXISTS QUALITY_INCIDENT (
  incident_id              INTEGER PRIMARY KEY,
  visit_id                 INTEGER REFERENCES VISIT,
  clinic_id                INTEGER REFERENCES CLINIC,
  incident_type            TEXT,
  description              TEXT,
  occurred_date            TEXT,
  severity                 TEXT,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: RECEIPT_LINE
CREATE TABLE IF NOT EXISTS RECEIPT_LINE (
  receipt_id               INTEGER REFERENCES RECEIPT_NOTE,
  line_no                  INTEGER,
  material_id              INTEGER REFERENCES MATERIAL,
  batch_id                 INTEGER REFERENCES MATERIAL_BATCH,
  quantity                 REAL,
  PRIMARY KEY (receipt_id, line_no)
);

-- table: RECEIPT_NOTE
CREATE TABLE IF NOT EXISTS RECEIPT_NOTE (
  receipt_id               INTEGER PRIMARY KEY,
  receipt_no               INTEGER,
  po_id                    INTEGER REFERENCES PURCHASE_ORDER,
  clinic_id                INTEGER REFERENCES CLINIC,
  received_date            TEXT,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: RECORD_ACCESS_LOG
CREATE TABLE IF NOT EXISTS RECORD_ACCESS_LOG (
  access_log_id            INTEGER PRIMARY KEY,
  patient_id               INTEGER REFERENCES PATIENT,
  clinic_id                INTEGER REFERENCES CLINIC,
  operator_name            TEXT,
  access_datetime          TEXT,
  purpose                  TEXT,
  authorization_ref        TEXT
);

-- table: ROSTER
CREATE TABLE IF NOT EXISTS ROSTER (
  roster_id                INTEGER PRIMARY KEY,
  dentist_id               INTEGER REFERENCES DENTIST,
  clinic_id                INTEGER REFERENCES CLINIC,
  roster_date              TEXT,
  slot_start               TEXT,
  slot_end                 TEXT,
  slot_capacity            INTEGER,
  roster_status            TEXT,
  is_published             INTEGER,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT,
  is_reserved              INTEGER
);

-- table: SEQ
CREATE TABLE IF NOT EXISTS SEQ (
  name TEXT PRIMARY KEY,
  val  INTEGER NOT NULL DEFAULT 0
);

-- table: SESSION
CREATE TABLE IF NOT EXISTS SESSION (
  session_id               TEXT PRIMARY KEY,
  account_id               INTEGER REFERENCES USER_ACCOUNT,
  role                     TEXT,
  is_guest                 INTEGER,
  csrf_token               TEXT,
  issued_at                TEXT,
  expires_at               TEXT
);

-- table: SETTLEMENT_TERM
CREATE TABLE IF NOT EXISTS SETTLEMENT_TERM (
  term_id                  INTEGER PRIMARY KEY,
  term_code                TEXT,
  payment_days             INTEGER,
  return_ratio             REAL,
  fee_items                TEXT
);

-- table: SHIFT_REQUEST
CREATE TABLE IF NOT EXISTS SHIFT_REQUEST (
  request_id               INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  requester_staff_id       INTEGER REFERENCES STAFF,
  dentist_id               INTEGER REFERENCES DENTIST,
  request_date             TEXT,
  slot_start               TEXT,
  slot_end                 TEXT,
  direction                TEXT,
  reason                   TEXT,
  request_status           TEXT,
  approver_staff_id        INTEGER REFERENCES STAFF,
  approved_date            TEXT,
  result_roster_id         INTEGER REFERENCES ROSTER,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: SHIFT_REQUISITION
CREATE TABLE IF NOT EXISTS SHIFT_REQUISITION (
  requisition_id           INTEGER PRIMARY KEY,
  from_clinic_id           INTEGER REFERENCES CLINIC,
  to_clinic_id             INTEGER REFERENCES CLINIC,
  dentist_id               INTEGER REFERENCES DENTIST,
  requisition_date         TEXT,
  start_time               TEXT,
  end_time                 TEXT,
  requisition_reason       TEXT,
  requisition_status       TEXT,
  requester_account_id     INTEGER REFERENCES USER_ACCOUNT,
  approver_account_id      INTEGER REFERENCES USER_ACCOUNT,
  submitted_at             TEXT,
  approved_at              TEXT
);

-- table: SHIFT_SUBSTITUTION
CREATE TABLE IF NOT EXISTS SHIFT_SUBSTITUTION (
  substitution_id          INTEGER PRIMARY KEY,
  roster_id                INTEGER REFERENCES ROSTER,
  absent_dentist_id        INTEGER REFERENCES DENTIST,
  substitute_dentist_id    INTEGER REFERENCES DENTIST,
  source_clinic_id         INTEGER REFERENCES CLINIC,
  effective_from           TEXT,
  effective_to             TEXT,
  reason_type              TEXT,
  request_id               INTEGER REFERENCES SHIFT_REQUEST
);

-- table: STAFF
CREATE TABLE IF NOT EXISTS STAFF (
  staff_id                 INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  staff_no                 INTEGER,
  name                     TEXT,
  role                     TEXT,
  phone                    TEXT,
  email                    TEXT
);

-- table: STANDARD_COST
CREATE TABLE IF NOT EXISTS STANDARD_COST (
  cost_id                  INTEGER PRIMARY KEY,
  catalog_id               INTEGER REFERENCES TREATMENT_CATALOG,
  version_id               INTEGER REFERENCES COST_VERSION,
  standard_cost            REAL,
  effective_date           TEXT
);

-- table: STATEMENT
CREATE TABLE IF NOT EXISTS STATEMENT (
  statement_id             INTEGER PRIMARY KEY,
  statement_no             INTEGER,
  supplier_id              INTEGER REFERENCES SUPPLIER,
  period_start             TEXT,
  period_end               TEXT,
  status                   TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: STATEMENT_LINE
CREATE TABLE IF NOT EXISTS STATEMENT_LINE (
  statement_id             INTEGER REFERENCES STATEMENT,
  line_no                  INTEGER,
  source_type              TEXT,
  source_no                INTEGER,
  amount                   REAL,
  PRIMARY KEY (statement_id, line_no)
);

-- table: STOCK_LEDGER
CREATE TABLE IF NOT EXISTS STOCK_LEDGER (
  ledger_id                INTEGER PRIMARY KEY,
  clinic_id                INTEGER REFERENCES CLINIC,
  material_id              INTEGER REFERENCES MATERIAL,
  on_hand_qty              REAL,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- table: STOCK_MOVEMENT
CREATE TABLE IF NOT EXISTS STOCK_MOVEMENT (
  movement_id              INTEGER PRIMARY KEY,
  ledger_id                INTEGER REFERENCES STOCK_LEDGER,
  movement_type            TEXT,
  direction                TEXT,
  quantity                 REAL,
  source_type              TEXT,
  source_no                INTEGER,
  moved_datetime           TEXT
);

-- table: SUPPLIER
CREATE TABLE IF NOT EXISTS SUPPLIER (
  supplier_id              INTEGER PRIMARY KEY,
  supplier_code            TEXT,
  supplier_name            TEXT,
  contact_name             TEXT,
  phone                    TEXT
);

-- table: TREATMENT_CATALOG
CREATE TABLE IF NOT EXISTS TREATMENT_CATALOG (
  catalog_id               INTEGER PRIMARY KEY,
  item_code                TEXT,
  item_name                TEXT,
  unit                     TEXT,
  standard_unit_price      REAL,
  is_whole_mouth           INTEGER
);

-- table: TREATMENT_ITEM
CREATE TABLE IF NOT EXISTS TREATMENT_ITEM (
  visit_id                 INTEGER REFERENCES VISIT,
  line_no                  INTEGER,
  catalog_id               INTEGER REFERENCES TREATMENT_CATALOG,
  dentist_id               INTEGER REFERENCES DENTIST,
  tooth_fdi                TEXT,
  standard_units           REAL,
  standard_unit_price      REAL,
  agreed_price             REAL,
  added_during_visit       TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT,
  PRIMARY KEY (visit_id, line_no)
);

-- table: TREATMENT_PLAN
CREATE TABLE IF NOT EXISTS TREATMENT_PLAN (
  plan_id                  INTEGER PRIMARY KEY,
  visit_id                 INTEGER REFERENCES VISIT,
  plan_no                  INTEGER,
  created_date             TEXT,
  plan_description         TEXT
);

-- table: USER_ACCOUNT
CREATE TABLE IF NOT EXISTS USER_ACCOUNT (
  account_id               INTEGER PRIMARY KEY,
  login_name               TEXT,
  password_hash            TEXT,
  password_salt            TEXT,
  role                     TEXT,
  staff_id                 INTEGER REFERENCES STAFF,
  dentist_id               INTEGER REFERENCES DENTIST,
  account_status           TEXT,
  registered_at            TEXT,
  last_login_at            TEXT
);

-- table: VISIT
CREATE TABLE IF NOT EXISTS VISIT (
  visit_id                 INTEGER PRIMARY KEY,
  visit_no                 INTEGER,
  appointment_id           INTEGER REFERENCES APPOINTMENT,
  clinic_id                INTEGER REFERENCES CLINIC,
  visit_datetime           TEXT,
  treated                  INTEGER,
  special_notes            TEXT,
  chief_complaint          TEXT,
  present_history          TEXT,
  examination              TEXT,
  diagnosis                TEXT,
  treatment_note           TEXT,
  is_void                  INTEGER,
  void_reason              TEXT,
  void_at                  TEXT,
  void_account_id          INTEGER REFERENCES USER_ACCOUNT
);

-- index: IX_NOTICE_ACCT
CREATE INDEX IF NOT EXISTS IX_NOTICE_ACCT ON NOTICE(account_id, read_at);

-- index: UX_APPT_ACTIVE
CREATE UNIQUE INDEX IF NOT EXISTS UX_APPT_ACTIVE ON APPOINTMENT(patient_id, roster_id) WHERE is_void=0 AND status IN ('已预约','已到诊');

-- index: UX_INVOICE_NO
CREATE UNIQUE INDEX IF NOT EXISTS UX_INVOICE_NO
  ON INVOICE(invoice_no) WHERE IFNULL(is_void,0)=0;

-- index: UX_INVOICE_VISIT
CREATE UNIQUE INDEX IF NOT EXISTS UX_INVOICE_VISIT
  ON INVOICE(visit_id) WHERE IFNULL(is_void,0)=0;

-- index: UX_PAYMENT_NO
CREATE UNIQUE INDEX IF NOT EXISTS UX_PAYMENT_NO
  ON PAYMENT(payment_no) WHERE payment_no IS NOT NULL;

-- index: UX_VISIT_APPT
CREATE UNIQUE INDEX IF NOT EXISTS UX_VISIT_APPT
  ON VISIT(appointment_id) WHERE appointment_id IS NOT NULL;
