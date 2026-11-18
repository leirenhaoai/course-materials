const app = getApp();

Page({
  data: {
    cid: 0,
    clinic_name: "",
    days: [],
    date: "",
    slots: [],
    loading: true,
    loadingSlots: false,
    weekday: ["日", "一", "二", "三", "四", "五", "六"]
  },

  onLoad(q) {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    const cid = Number(q.clinic_id || wx.getStorageSync("clinic_id") || 1);
    this.setData({ cid: cid });
    app.req("/api/days?clinic_id=" + cid).then((d) => {
      const days = (d.days || []).map((x) => {
        const dt = new Date(x.date.replace(/-/g, "/"));
        return {
          date: x.date,
          md: x.date.slice(5),
          w: this.data.weekday[dt.getDay()],
          remain: x.remain
        };
      });
      // 默认挑第一个还有号的日期
      let pick = days.find((x) => x.remain > 0);
      if (!pick) pick = days[0];
      this.setData({ days: days, date: pick ? pick.date : "", loading: false });
      if (pick) this.loadSlots(pick.date);
    }).catch(() => this.setData({ loading: false }));

    app.req("/api/clinics").then((d) => {
      const c = (d.clinics || []).find((x) => x.clinic_id === cid);
      if (c) this.setData({ clinic_name: c.clinic_name });
      wx.setNavigationBarTitle({ title: c ? c.clinic_name : "选时段" });
    }).catch(() => {});
  },

  pickDay(e) {
    const date = e.currentTarget.dataset.d;
    this.setData({ date: date });
    this.loadSlots(date);
  },

  loadSlots(date) {
    this.setData({ loadingSlots: true, slots: [] });
    app.req("/api/slots?clinic_id=" + this.data.cid + "&date=" + date)
      .then((d) => {
        const slots = (d.slots || []).map((s) => ({
          roster_id: s.roster_id,
          start: s.start,
          end: s.end,
          dentist: s.dentist,
          left: s.left,
          full: s.full
        }));
        this.setData({ slots: slots, loadingSlots: false });
      })
      .catch(() => this.setData({ loadingSlots: false }));
  },

  pickSlot(e) {
    const i = e.currentTarget.dataset.i;
    const s = this.data.slots[i];
    if (!s || s.full) return;
    wx.navigateTo({
      url: "/pages/confirm/confirm?roster_id=" + s.roster_id +
        "&date=" + this.data.date + "&start=" + s.start + "&end=" + s.end +
        "&dentist=" + encodeURIComponent(s.dentist || "") +
        "&clinic=" + encodeURIComponent(this.data.clinic_name || "") +
        "&left=" + s.left
    });
  },

  changeClinic() {
    wx.navigateBack({ delta: 1 });
  }
});
