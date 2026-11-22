import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  DispatchResult,
  EntryRow,
  OverviewResult,
  PageResult,
  UnrecoveredPage,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/** 缺采匹配：按请求编号/失败日期/接口端点检索未恢复调用，翻页位置稳定。 */
export async function listUnrecovered(
  filters: { 请求编号?: string; 失败日期?: string; 接口端点?: string },
  page: number,
  size: number,
): Promise<UnrecoveredPage> {
  const query = new URLSearchParams()
  if (filters.请求编号) query.set('请求编号', filters.请求编号)
  if (filters.失败日期) query.set('失败日期', filters.失败日期)
  if (filters.接口端点) query.set('接口端点', filters.接口端点)
  query.set('page', String(page))
  query.set('size', String(size))
  const response = await request(`/api/call_log/unrecovered?${query.toString()}`)
  if (!response.ok) throw new Error('缺采匹配结果读取失败')
  return await response.json()
}

/** 把选中的请求编号提交重放，确认结果回写检索清单。 */
export async function dispatchUnrecovered(requestNumbers: string[]): Promise<DispatchResult> {
  const response = await request('/api/call_log/unrecovered/dispatch', {
    method: 'POST',
    body: JSON.stringify({ 请求编号列表: requestNumbers }),
  })
  return await response.json()
}
