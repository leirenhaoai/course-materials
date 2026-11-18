const app = getApp();

Page({
  data: {
    list: [],
    loading: true
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/notices").then((d) => {
      // 接口给的是 read_at（为空即未读），页面用 is_read 更好写
      const list = (d.notices || []).map((x) => {
        x.is_read = !!(x.read_at && x.read_at.length);
        return x;
      });
      this.setData({ list: list, loading: false });
      if (list.some((x) => !x.is_read)) {
        app.req("/api/notices/read", {}).catch(() => {});
      }
    }).catch(() => this.setData({ loading: false }));
  },

  goAppts() { wx.switchTab({ url: "/pages/appts/appts" }); },
  goBook() { wx.switchTab({ url: "/pages/book/book" }); }
});
