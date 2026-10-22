import { createRouter, createWebHashHistory } from 'vue-router'

/**
 * 平台页面路由。
 *
 * 使用 hash 模式：部署到政务内网的静态服务器时无需额外配置 rewrite 规则，
 * 直接双击 dist/index.html 也能正常跳转。
 *
 * @type {import('vue-router').RouteRecordRaw[]}
 */
export const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { title: '平台登录', public: true },
  },
  {
    path: '/assistant',
    name: 'home',
    component: () => import('../views/HomeView.vue'),
    meta: { title: '智能问答', icon: 'chat', requiresAuth: true },
  },
  {
    path: '/',
    redirect: '/monitor',
  },
  {
    path: '/monitor',
    name: 'monitor',
    component: () => import('../views/MonitorView.vue'),
    meta: { title: '运营总览', icon: 'monitor', requiresAuth: true },
  },
  {
    path: '/monitor/detail',
    name: 'monitor-detail',
    component: () => import('../views/RealtimeMonitorView.vue'),
    meta: { title: '实时监测', icon: 'monitor', requiresAuth: true },
  },
  {
    path: '/inspection',
    name: 'inspection',
    component: () => import('../views/InspectionView.vue'),
    meta: { title: '巡检台账', icon: 'ledger', requiresAuth: true },
  },
  {
    path: '/policy',
    name: 'policy',
    component: () => import('../views/PolicyView.vue'),
    meta: { title: '政策文档查阅', icon: 'document', requiresAuth: true },
  },
  {
    path: '/flood',
    name: 'flood',
    component: () => import('../views/FloodView.vue'),
    meta: { title: '防汛调度', icon: 'flood', requiresAuth: true },
  },
  {
    path: '/ecology',
    name: 'ecology',
    component: () => import('../views/EcologyView.vue'),
    meta: { title: '生态管护', icon: 'ecology', requiresAuth: true },
  },
  {
    path: '/boat',
    name: 'boat',
    component: () => import('../views/BoatView.vue'),
    meta: { title: '无人艇中心', icon: 'boat', requiresAuth: true },
  },
  {
    path: '/devices',
    name: 'devices',
    component: () => import('../views/DeviceManageView.vue'),
    meta: { title: '设备管理', icon: 'devices', requiresAuth: true },
  },
  {
    path: '/dam',
    name: 'dam',
    component: () => import('../views/DamManageView.vue'),
    meta: { title: '库区档案', icon: 'dam', requiresAuth: true },
  },
  {
    path: '/users',
    name: 'users',
    component: () => import('../views/UserManageView.vue'),
    meta: { title: '用户与权限', icon: 'users', requiresAuth: true },
  },
  {
    path: '/parameters',
    name: 'parameters',
    component: () => import('../views/ParamSettingsView.vue'),
    meta: { title: '监测参数设置', icon: 'parameters', requiresAuth: true },
  },
  {
    path: '/notifications',
    name: 'notifications',
    component: () => import('../views/NotificationView.vue'),
    meta: { title: '消息通知', icon: 'notifications', requiresAuth: true },
  },
  {
    path: '/data-maintenance',
    name: 'data-maintenance',
    component: () => import('../views/DataMaintenanceView.vue'),
    meta: { title: '数据维护', icon: 'data-maintenance', requiresAuth: true },
  },
  {
    path: '/service-bus',
    name: 'service-bus',
    component: () => import('../views/ServiceBusView.vue'),
    meta: { title: '服务接入', icon: 'api', requiresAuth: true },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../views/SystemSettingsView.vue'),
    meta: { title: '系统设置', icon: 'settings', requiresAuth: true },
  },
  {
    path: '/operations', name: 'operations', component: () => import('../views/OperationsView.vue'), meta: { title: '运行与审计', requiresAuth: true },
  },
  {
    // 兜底：未匹配的路径回到运营总览
    path: '/:pathMatch(.*)*',
    redirect: '/monitor',
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach((to) => {
  document.title = `${to.meta.title || '智护库安'} - 水库数字化运营平台`
  const token = localStorage.getItem('token')
  if (to.meta.public && to.name === 'login' && token) return { name: 'monitor' }
  if (to.meta.requiresAuth && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
