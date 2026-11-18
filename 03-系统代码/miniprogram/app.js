// 全局：接口地址、token 存储、request 封装
//
// baseUrl 是唯一要改的地方：
//   · 开发者工具模拟器 → http://127.0.0.1:8000
//   · 手机真机调试     → http://电脑局域网IP:8000（手机和电脑同一 WiFi）
//
// 真机调试必须勾「详情 → 本地设置 → 不校验合法域名、TLS 版本以及 HTTPS 证书」，
// 否则 http 请求会被拦。

const BASE = "http://10.102.71.59:8000";

App({
  globalData: {
    baseUrl: BASE,
    token: "",
    patients: [],
    me: null
  },

  onLaunch() {
    const t = wx.getStorageSync("token") || "";
    if (t) {
      this.globalData.token = t;
    }
  },

  setToken(t) {
    this.globalData.token = t || "";
    if (t) {
      wx.setStorageSync("token", t);
    } else {
      wx.removeStorageSync("token");
    }
  },

  // 统一的请求封装：自动带 token、自动处理 401、自动把 err 弹出来
  req(path, data, method) {
    const self = this;
    method = method || (data ? "POST" : "GET");
    return new Promise(function (resolve, reject) {
      wx.request({
        url: BASE + path,
        method: method,
        data: data || {},
        header: self.globalData.token
          ? { Authorization: "Bearer " + self.globalData.token }
          : {},
        timeout: 15000,
        success(res) {
          const d = res.data || {};
          if (res.statusCode === 401) {
            self.setToken("");
            wx.showToast({ title: "请重新登录", icon: "none" });
            wx.reLaunch({ url: "/pages/login/login" });
            return reject(new Error("未登录"));
          }
          if (d.ok) {
            return resolve(d);
          }
          const msg = d.err || ("请求失败 " + res.statusCode);
          wx.showToast({ title: msg, icon: "none", duration: 2200 });
          reject(new Error(msg));
        },
        fail(e) {
          wx.showModal({
            title: "连不上服务",
            content:
              "确认电脑上 run.bat 正在运行，且手机与电脑在同一个 WiFi。" +
              "真机调试要在「详情 → 本地设置」里勾上「不校验合法域名」。\n\n" +
              (e.errMsg || ""),
            showCancel: false
          });
          reject(e);
        }
      });
    });
  }
});
