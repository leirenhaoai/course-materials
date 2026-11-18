const app = getApp();

function tagOf(st) {
  if (st === "已预约") return "blue";
  if (st === "已到诊") return "green";
  if (st === "爽约") return "amber";
  return "gray";
}

Page({
  data: {
    upcoming: [],
    history: [],
    loading: true
  },

  onShow() {
    if (!app.globalData.token) {
      return wx.reLaunch({ url: "/pages/login/login" });
    }
    this.load();
  },

  load() {
    app.req("/api/appointments").then((d) => {
      const up = (d.upcoming || []).map((x) => {
        x.tag = tagOf(x.status);
        return x;
      });
      const his = (d.history || []).map((x) => {
        x.tag = tagOf(x.status);
        return x;
      });
      this.setData({ upcoming: up, history: his, loading: false });
    }).catch(() => this.setData({ loading: false }));
  },

  cancel(e) {
    const id = e.currentTarget.dataset.id;
    wx.showActionSheet({
      itemList: ["临时有事", "身体不适", "已在别处就诊", "约错时间或门店", "其他"],
      success: (r) => {
        const reasons = ["临时有事", "身体不适", "已在别处就诊",
          "约错时间或门店", "其他"];
        wx.showModal({
          title: "确认取消",
          content: "取消后这个号会放回给别人。确定取消吗？",
          success: (m) => {
            if (!m.confirm) return;
            app.req("/api/cancel", {
              appointment_id: id,
              reason: reasons[r.tapIndex]
            }).then(() => {
              wx.showToast({ title: "已取消" });
              this.load();
            }).catch(() => {});
          }
        });
      }
    });
  },

  resched(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: "/pages/resched/resched?appointment_id=" + id });
  },

  goBook() { wx.switchTab({ url: "/pages/book/book" }); }
});
