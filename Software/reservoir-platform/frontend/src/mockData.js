// 业务常量与示例数据

/**
 * 项目名（占位，待替换）
 * @type {string}
 */
export const PROJECT_NAME = '智护库安智能助手'

/** 欢迎文案 */
export const WELCOME_TEXT =
  '守护水库安澜，保障灌溉民生，筑牢防汛防线，您可咨询大坝巡检、防汛调度、生态管护、水利法规相关业务。'

/** loading 提示 */
export const LOADING_TEXT = '正在检索水利知识库，请稍候……'

/** 数字人标题 */
export const DIGITAL_HUMAN_TITLE = 'AI值班机器人'

/** 数字人副标题 */
export const DIGITAL_HUMAN_SUBTITLE = '在线值守 · 7×24 小时'

/**
 * 「大家都在问」快捷标签（6 个）
 * @type {import('./types.js').QuickTag[]}
 */
export const QUICK_TAGS = [
  { id: 'tag-1', text: '防汛巡检' },
  { id: 'tag-2', text: '农业灌溉' },
  { id: 'tag-3', text: '大坝安全' },
  { id: 'tag-4', text: '生态保护' },
  { id: 'tag-5', text: '应急救援' },
  { id: 'tag-6', text: '水利法规' },
]

/**
 * 右侧热门问题（6 条）
 * @type {import('./types.js').HotQuestion[]}
 */
export const HOT_QUESTIONS = [
  { id: 'hot-1', text: '汛期大坝巡查重点部位', heat: 986 },
  { id: 'hot-2', text: '超汛限科学调度泄洪', heat: 947 },
  { id: 'hot-3', text: '灌溉用水申请流程', heat: 912 },
  { id: 'hot-4', text: '大坝渗漏异常处置', heat: 873 },
  { id: 'hot-5', text: '如何判断管涌险情', heat: 821 },
  { id: 'hot-6', text: '生态放流标准', heat: 764 },
]

/**
 * 右侧快捷跳转卡片（3 张）
 * @type {import('./types.js').QuickLink[]}
 */
export const QUICK_LINKS = [
  {
    id: 'link-1',
    title: '水库监测总览',
    description: '实时水位、雨量与渗流监测',
    icon: 'monitor',
    route: 'monitor',
  },
  {
    id: 'link-2',
    title: '巡检台账',
    description: '巡查记录与隐患整改进度',
    icon: 'ledger',
    route: 'inspection',
  },
  {
    id: 'link-3',
    title: '政策文档查阅',
    description: '水利法规与行业标准文件',
    icon: 'document',
    route: 'policy',
  },
]

/**
 * 示例对话（7 条，含 2 处安全警示红色高亮）
 * @type {import('./types.js').ChatMessage[]}
 */
export const SAMPLE_MESSAGES = [
  {
    id: 'msg-1',
    role: 'user',
    content: '汛期大坝巡查重点部位有哪些？',
    time: '09:12',
  },
  {
    id: 'msg-2',
    role: 'assistant',
    content:
      '汛期巡查应重点覆盖以下部位：一是坝顶与防浪墙，查看有无裂缝、错位、塌陷；二是上游坝坡护坡块石，检查有无松动、隆起、脱落；三是下游坝坡与排水棱体，观察有无散浸、渗水、流土；四是坝脚与坝基，留意有无渗漏、冒水、翻砂；五是溢洪道与放水设施，确认闸门启闭灵活、无淤堵。巡查频次在暴雨期间应加密至每 2 小时一次，并做好影像与文字记录。发现异常应立即上报，严禁擅自处置。',
    highlights: [{ text: '发现异常应立即上报，严禁擅自处置。', type: 'danger' }],
    time: '09:12',
  },
  {
    id: 'msg-3',
    role: 'user',
    content: '遇到超汛限水位应该怎么调度泄洪？',
    time: '09:15',
  },
  {
    id: 'msg-4',
    role: 'assistant',
    content:
      '超汛限水位时应按下述步骤科学调度：第一，核实水位、库容与入库流量，确认超限幅度；第二，依据批准的汛期调度运用计划确定下泄流量，优先保障大坝安全；第三，及时向下游及防汛主管部门发布泄洪预警，通知沿岸群众避险；第四，开启闸门应逐级、均匀、缓慢开启，避免下游水位骤涨；第五，持续监测库水位与下游河道水位，动态调整。严禁未预警擅自开闸泄洪。若遭遇连续强降雨，应服从上级防汛指挥部统一调度指令。',
    highlights: [{ text: '严禁未预警擅自开闸泄洪。', type: 'danger' }],
    time: '09:15',
  },
  {
    id: 'msg-5',
    role: 'user',
    content: '农业灌溉用水申请流程是怎样的？',
    time: '09:20',
  },
  {
    id: 'msg-6',
    role: 'assistant',
    content:
      '农业灌溉用水申请流程一般为：第一步，由用水户或村级用水合作组织向水库管理单位提出书面申请，写明灌溉面积、作物种类、需水时段与预计用水量；第二步，管理单位结合水库蓄水情况与年度供水计划进行审核；第三步，签订供用水合同，明确取水口、流量、时段与计量方式；第四步，按合同约定开闸放水并抄表计量；第五步，灌溉结束后结算水费。建议提前 3—5 个工作日提交申请，避开集中用水高峰。',
    time: '09:20',
  },
  {
    id: 'msg-7',
    role: 'user',
    content: '好的，明白了，谢谢！',
    time: '09:21',
  },
]
