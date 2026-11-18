const app = getApp();

function money(n) {
  return (Number(n) || 0).toLocaleString("zh-CN");
}

Page({
  data: {
    invoices: [],
    loading: true,
    sum: { due: 0, got: 0, owe: 0 }
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/invoices").then((d) => {
      let due = 0, got = 0, owe = 0;
      const rows = (d.invoices || []).map((x) => {
        due += x.due;
        got += x.got;
        owe += x.owe;
        x.dueText = money(x.due);
        x.gotText = money(x.got);
        x.oweText = money(x.owe);
        x.tag = x.owe > 0.01 ? "amber" : "green";
        x.stText = x.owe > 0.01 ? "待付款" : "已结清";
        return x;
      });
      this.setData({
        invoices: rows, loading: false,
        sum: { due: money(due), got: money(got), owe: money(owe) }
      });
    }).catch(() => this.setData({ loading: false }));
  }
});
