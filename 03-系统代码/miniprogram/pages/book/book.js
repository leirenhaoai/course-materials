const app = getApp();

Page({
  data: {
    clinics: [],
    cid: 0,
    loading: true
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/clinics")
      .then((d) => {
        const cs = d.clinics || [];
        // 记住上次选的门店
        const last = wx.getStorageSync("clinic_id") || (cs[0] && cs[0].clinic_id);
        this.setData({ clinics: cs, cid: last || 0, loading: false });
      })
      .catch(() => this.setData({ loading: false }));
  },

  pick(e) {
    const cid = e.currentTarget.dataset.id;
    wx.setStorageSync("clinic_id", cid);
    this.setData({ cid: cid });
    wx.navigateTo({ url: "/pages/slots/slots?clinic_id=" + cid });
  }
});
