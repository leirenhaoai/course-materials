const app = getApp();

Page({
  data: {
    mode: "login",          // login | register
    login_name: "",
    password: "",
    patient_name: "",
    phone: "",
    busy: false,
    tip: ""
  },

  onLoad() {
    if (app.globalData.token) {
      wx.reLaunch({ url: "/pages/index/index" });
    }
  },

  toRegister() { this.setData({ mode: "register", tip: "" }); },
  toLogin() { this.setData({ mode: "login", tip: "" }); },

  onInput(e) {
    const k = e.currentTarget.dataset.k;
    const o = {};
    o[k] = e.detail.value;
    this.setData(o);
  },

  submit() {
    const d = this.data;
    if (d.busy) return;
    if (!d.login_name || !d.password) {
      return this.setData({ tip: "请填写登录名和口令" });
    }
    if (d.mode === "register" && !d.patient_name) {
      return this.setData({ tip: "请填写就诊人姓名" });
    }
    this.setData({ busy: true, tip: "" });
    const path = d.mode === "register" ? "/api/register" : "/api/login";
    const body = { login_name: d.login_name.trim(), password: d.password };
    if (d.mode === "register") {
      body.patient_name = d.patient_name.trim();
      body.phone = (d.phone || "").trim();
    }
    app.req(path, body)
      .then((r) => {
        app.setToken(r.token);
        app.globalData.patients = r.patients || [];
        wx.reLaunch({ url: "/pages/index/index" });
      })
      .catch((e) => {
        if (e && e.message && e.message !== "未登录") {
          this.setData({ tip: e.message });
        }
      })
      .then(() => this.setData({ busy: false }));
  },

  useDemo() {
    this.setData({ login_name: "zhangsan", password: "123456" });
  }
});
