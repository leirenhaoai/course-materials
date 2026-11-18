const app = getApp();

function money(n) {
  return (Number(n) || 0).toLocaleString("zh-CN");
}

Page({
  data: {
    me: null,
    loading: true
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/me")
      .then((d) => {
        if (d.next) {
          d.next.dateText = (d.next.roster_date || "").slice(5);
        }
        d.paidText = money(d.paid);
        this.setData({ me: d, loading: false });
      })
      .catch(() => this.setData({ loading: false }));
  },

  goBook() { wx.switchTab({ url: "/pages/book/book" }); },
  goAppts() { wx.switchTab({ url: "/pages/appts/appts" }); },
  goVisits() { wx.switchTab({ url: "/pages/visits/visits" }); },
  goInvoices() { wx.navigateTo({ url: "/pages/invoices/invoices" }); },
  goNotices() { wx.navigateTo({ url: "/pages/notices/notices" }); },

  logout() {
    wx.showModal({
      title: "退出登录",
      content: "退出后需要重新登录才能预约和查看记录。",
      success: (r) => {
        if (r.confirm) {
          app.setToken("");
          wx.reLaunch({ url: "/pages/login/login" });
        }
      }
    });
  }
});
