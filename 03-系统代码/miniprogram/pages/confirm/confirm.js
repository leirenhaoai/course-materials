const app = getApp();

Page({
  data: {
    roster_id: 0,
    date: "",
    start: "",
    end: "",
    dentist: "",
    clinic: "",
    left: 0,
    patients: [],
    pid: 0,
    phone: "",
    reason: "",
    busy: false,
    err: ""
  },

  onLoad(q) {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.setData({
      roster_id: Number(q.roster_id || 0),
      date: q.date || "",
      start: q.start || "",
      end: q.end || "",
      dentist: decodeURIComponent(q.dentist || ""),
      clinic: decodeURIComponent(q.clinic || ""),
      left: Number(q.left || 0)
    });
    app.req("/api/me").then((d) => {
      const ps = d.patients || [];
      this.setData({
        patients: ps,
        pid: ps.length ? ps[0].patient_id : 0,
        phone: ps.length ? (ps[0].phone || "") : ""
      });
    }).catch(() => {});
  },

  pickPatient(e) {
    const pid = e.currentTarget.dataset.id;
    const p = this.data.patients.find((x) => x.patient_id === pid);
    this.setData({ pid: pid, phone: (p && p.phone) || "" });
  },

  onInput(e) {
    const k = e.currentTarget.dataset.k;
    const o = {};
    o[k] = e.detail.value;
    this.setData(o);
  },

  submit() {
    if (this.data.busy) return;
    if (!this.data.pid) {
      return this.setData({ err: "请选择这次是给谁看" });
    }
    this.setData({ busy: true, err: "" });
    app.req("/api/book", {
      roster_id: this.data.roster_id,
      patient_id: this.data.pid,
      phone: (this.data.phone || "").trim(),
      reason: (this.data.reason || "").trim()
    }).then((r) => {
      wx.showModal({
        title: "预约成功",
        content: "预约号 " + r.appointment_no + "\n到店报预约号或姓名都可以。",
        showCancel: false,
        success: () => {
          wx.switchTab({ url: "/pages/appts/appts" });
        }
      });
    }).catch((e) => {
      if (e && e.message && e.message !== "未登录") {
        this.setData({ err: e.message });
      }
    }).then(() => this.setData({ busy: false }));
  },

  back() { wx.navigateBack({ delta: 1 }); }
});
