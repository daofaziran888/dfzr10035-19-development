/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 缺采匹配：失败请求编号与后续成功回执对照后的单行结果。 */
export type UnrecoveredItem = {
  位置: number
  请求编号: string
  接口端点: string
  失败日期: string
  最近失败时间: string
  尝试次数: number
  失败次数: number
  最近响应状态: string
  最近错误信息: string
  恢复状态: string
  回执记录编号: string
  回执响应状态: string
  回执时间: string
  回执返回行数: string
  派发状态: string
  重放任务编号: string
  重放任务状态: string
}

export type UnrecoveredPage = {
  items: UnrecoveredItem[]
  total: number
  page: number
  size: number
}

export type DispatchResultItem = {
  请求编号: string
  结果: string
  任务编号: string
}

export type DispatchResult = {
  ok: boolean
  message: string
  结果: DispatchResultItem[]
  已派发: number
  已剔除: number
  已在队列: number
  未找到: number
}
