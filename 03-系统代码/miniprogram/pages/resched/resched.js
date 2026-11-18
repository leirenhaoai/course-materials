const app = getApp();

Page({
  data: {
    aid: 0,
    cur: null,
    date: "",
    cid: 0,
    slots: [],
    loading: true
  },

  onLoad(q) {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.setData({ aid: Number(q.appointment_id || 0) });
    this.load("");
  },

  // date 为空时后端自动挑「明天起第一个真有空位的日期」
  load(date) {
    const self = this;
    let url = "/api/reschedule?appointment_id=" + this.data.aid;
    if (date) url += "&date=" + date;
    if (this.data.cid) url += "&clinic_id=" + this.data.cid;
    this.setData({ loading: true });
    app.req(url).then((d) => {
      self.setData({
        cur: d.current,
        date: d.date,
        cid: d.clinic_id,
        slots: (d.slots || []).map((s) => ({
          roster_id: s.roster_id, start: s.start, end: s.end,
          dentist: s.dentist, left: s.left
        })),
        loading: false
      });
    }).catch(() => self.setData({ loading: false }));
  },

  pickDay(e) {
    const d = e.currentTarget.dataset.d;
    this.setData({ date: d });
    this.load(d);
  },

  nextDay(step) {
    const ms = new Date(this.data.date.replace(/-/g, "/")).getTime() + step * 86400000;
    const d = new Date(ms);
    const s = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
    this.setData({ date: s });
    this.load(s);
  },

  prevDay() { this.nextDay(-1); },
  afterDay() { this.nextDay(1); },

  pick(e) {
    const rid = e.currentTarget.dataset.id;
    const s = this.data.slots.find((x) => x.roster_id === rid);
    if (!s) return;
    wx.showModal({
      title: "确认改约",
      content: "改到 " + this.data.date + " " + s.start + " — " + s.end +
        "（" + (s.dentist || "医生待定") + "）？",
      success: (r) => {
        if (!r.confirm) return;
        app.req("/api/reschedule", {
          appointment_id: this.data.aid, roster_id: rid
        }).then(() => {
          wx.showToast({ title: "已改约" });
          setTimeout(() => wx.navigateBack({ delta: 1 }), 700);
        }).catch(() => {});
      }
    });
  },

  back() { wx.navigateBack({ delta: 1 }); }
});
