<template>
  <section class="reco-panel" data-testid="unrecovered-panel">
    <header class="reco-head">
      <h3>缺采匹配（未恢复调用）</h3>
      <p class="reco-desc">
        把失败请求编号与后续成功回执对照，定位仍未补采的调用；迟到的 200 回执只更新恢复状态，
        翻页保留原编号位置。选中命中项可直接提交重放。
      </p>
    </header>

    <form class="filter-bar" @submit.prevent="search">
      <label class="filter-item">
        <span>请求编号</span>
        <input v-model="requestNo" data-testid="reco-filter-请求编号" placeholder="按请求编号检索" />
      </label>
      <label class="filter-item">
        <span>失败日期</span>
        <input v-model="failDate" data-testid="reco-filter-失败日期" placeholder="如 2026-11-22" />
      </label>
      <label class="filter-item">
        <span>接口端点</span>
        <input v-model="endpoint" data-testid="reco-filter-接口端点" placeholder="按接口端点检索" />
      </label>
      <label class="filter-item">
        <span>每页条数</span>
        <select v-model.number="size" data-testid="reco-size" @change="search">
          <option :value="2">2</option>
          <option :value="3">3</option>
          <option :value="5">5</option>
          <option :value="10">10</option>
        </select>
      </label>
      <button class="btn" data-testid="reco-query" type="submit">查询</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>位置</th>
          <th>请求编号</th>
          <th>接口端点</th>
          <th>失败日期</th>
          <th>尝试次数</th>
          <th>最近响应</th>
          <th>恢复状态</th>
          <th>实际响应依据</th>
          <th>派发状态</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in items"
          :key="item.请求编号"
          :data-testid="`reco-row-${item.请求编号}`"
          :data-recovered="item.恢复状态"
        >
          <td>
            <input
              type="checkbox"
              :disabled="item.恢复状态 === '已恢复'"
              :checked="selected.includes(item.请求编号)"
              :data-testid="`reco-select-${item.请求编号}`"
              @change="toggle(item.请求编号)"
            />
          </td>
          <td>{{ item.位置 }}</td>
          <td>{{ item.请求编号 }}</td>
          <td>{{ item.接口端点 }}</td>
          <td>{{ item.失败日期 }}</td>
          <td>{{ item.尝试次数 }}</td>
          <td>{{ item.最近响应状态 }}</td>
          <td>{{ item.恢复状态 }}</td>
          <td>{{ receiptText(item) }}</td>
          <td>{{ dispatchText(item) }}</td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="10" class="empty-state">当前检索范围内没有缺采匹配结果</td>
        </tr>
      </tbody>
    </table>

    <div class="reco-foot">
      <button class="btn" data-testid="reco-prev" type="button" :disabled="page <= 1" @click="goto(page - 1)">
        上一页
      </button>
      <span data-testid="reco-page-info">第 {{ page }} / {{ pages }} 页，共 {{ total }} 笔</span>
      <button class="btn" data-testid="reco-next" type="button" :disabled="page >= pages" @click="goto(page + 1)">
        下一页
      </button>
      <button
        class="btn primary"
        data-testid="reco-dispatch"
        type="button"
        :disabled="!selected.length || dispatching"
        @click="dispatch"
      >
        {{ dispatching ? '派发中…' : `提交重放（${selected.length}）` }}
      </button>
    </div>
    <p v-if="message" class="reco-message" data-testid="reco-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="reco-error">{{ errorMessage }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { dispatchUnrecovered, listUnrecovered } from '@/api/backend-service'
import type { UnrecoveredItem } from '@/data/types'

const requestNo = ref('')
const failDate = ref('')
const endpoint = ref('')
const page = ref(1)
const size = ref(3)
const total = ref(0)
const items = ref<UnrecoveredItem[]>([])
const selected = ref<string[]>([])
const message = ref('')
const errorMessage = ref('')
const dispatching = ref(false)

const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function receiptText(item: UnrecoveredItem): string {
  if (item.恢复状态 !== '已恢复') return '—'
  return `${item.回执记录编号}（${item.回执响应状态}，${item.回执时间}，${item.回执返回行数}行）`
}

function dispatchText(item: UnrecoveredItem): string {
  if (item.派发状态 !== '已派发') return '未派发'
  return `已派发 ${item.重放任务编号}（${item.重放任务状态}）`
}

function toggle(number: string) {
  const index = selected.value.indexOf(number)
  if (index >= 0) selected.value.splice(index, 1)
  else selected.value.push(number)
}

async function load() {
  errorMessage.value = ''
  try {
    const payload = await listUnrecovered(
      { 请求编号: requestNo.value, 失败日期: failDate.value, 接口端点: endpoint.value },
      page.value,
      size.value,
    )
    items.value = payload.items
    total.value = payload.total
    // 迟到的回执到达后，已恢复的编号不再占选择位（位置仍保留在清单里）
    const recovered = new Set(
      payload.items.filter((item) => item.恢复状态 === '已恢复').map((item) => item.请求编号),
    )
    selected.value = selected.value.filter((number) => !recovered.has(number))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺采匹配结果读取失败'
  }
}

/** 检索范围变更：回到第一页重新判定候选。 */
function search() {
  page.value = 1
  void load()
}

/** 翻页：同一检索范围内取数，编号位置保持稳定。 */
function goto(target: number) {
  if (target < 1 || target > pages.value) return
  page.value = target
  void load()
}

async function dispatch() {
  if (!selected.value.length) return
  dispatching.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    const result = await dispatchUnrecovered([...selected.value])
    if (!result.ok) throw new Error(result.message)
    const details = result.结果.map((item) => `${item.请求编号}:${item.结果}`).join('；')
    message.value = `${result.message}（${details}）`
    selected.value = []
    // 确认结果回写检索清单：保持当前页，刷新派发状态
    await load()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '提交重放失败'
  } finally {
    dispatching.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.reco-panel {
  margin-top: 20px;
  border-top: 2px solid var(--border);
  padding-top: 12px;
}
.reco-head h3 {
  margin: 0 0 4px;
}
.reco-desc {
  color: var(--muted);
  font-size: 12px;
  margin: 0 0 12px;
}
.reco-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
}
.reco-message {
  font-size: 12px;
  color: var(--brand);
}
</style>
