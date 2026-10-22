/**
 * AI 跳转目标与展示名。
 *
 * <p>页面标识必须与 `router/index.js` 里的路由名、`router/navigate.js` 的
 * `VALID_TARGETS` 保持一致；跳转按钮和提示文案都从这里取名字，避免两处各写一份。
 */
export const TARGET_TITLES = {
  home: '智能问答',
  monitor: '水库监测总览',
  inspection: '巡检台账',
  policy: '政策文档查阅',
  flood: '防汛调度',
  ecology: '生态管护',
}

/** @param {string} target */
export function targetTitle(target) {
  return TARGET_TITLES[target] || target || '目标页面'
}
