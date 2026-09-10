/**
 * VOC Radar — 弹层滚动锁
 *
 * 职责：
 *  - 详情抽屉（#detailPanel）/ 报告弹层（#reportModal）任一处于打开
 *    状态时，给 body 挂 voc-locked 类锁定主页面滚动；两者都关闭后
 *    解锁。防止滚轮/触摸在弹层遮罩或滚动容器边界处"链式穿透"滚动
 *    背后的主页面（演示视频中"滚动详情/滚动报告却滚主页面"的根因）。
 *  - 与 style.css 中内层滚动容器的 overscroll-behavior: contain
 *    构成双保险：前者管"滚轮落在遮罩上"，后者管"滚轮落在面板边界"。
 *
 * 用法：组件的 open()/close() 改变弹层 hidden 状态后调用
 *       window.VOC_ScrollLock.sync()。锁定状态按两个弹层的组合状态
 *       计算，报告弹层叠在抽屉之上时互不干扰，谁最后关完谁解锁。
 */
(function (global) {
  "use strict";

  var DIALOG_IDS = ["detailPanel", "reportModal"];

  function sync() {
    var locked = DIALOG_IDS.some(function (id) {
      var el = document.getElementById(id);
      return el && !el.hidden;
    });
    document.body.classList.toggle("voc-locked", locked);
  }

  global.VOC_ScrollLock = { sync: sync };
})(window);
