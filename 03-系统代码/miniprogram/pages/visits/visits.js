const app = getApp();

function money(n) {
  return (Number(n) || 0).toLocaleString("zh-CN");
}

Page({
  data: {
    visits: [],
    loading: true,
    open: -1
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/visits").then((d) => {
      const vs = (d.visits || []).map((v) => {
        v.dueText = money(v.due);
        v.gotText = money(v.got);
        v.owe = Math.round((v.due - v.got) * 100) / 100;
        v.oweText = money(v.owe);
        v.dateText = (v.visit_datetime || "").slice(0, 16);
        return v;
      });
      this.setData({ visits: vs, loading: false });
    }).catch(() => this.setData({ loading: false }));
  },

  toggle(e) {
    const i = e.currentTarget.dataset.i;
    this.setData({ open: this.data.open === i ? -1 : i });
  },

  goInvoices() { wx.navigateTo({ url: "/pages/invoices/invoices" }); }
});
