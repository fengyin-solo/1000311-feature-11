<template>
  <section class="page" data-module="gas_detect">
    <header class="page-head">
      <div>
        <h2>气体监测管理</h2>
        <p class="page-desc">维护监测点位，围绕点位编号、监测气体、所在管沟、当前浓度做登记、筛选与状态流转；告警等级、负责人、恢复状态与告警联动中心同步。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn primary" to="/gas_alarm">前往告警联动处置</RouterLink>
        <button class="btn" type="button" @click="exportRows">导出气体监测清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>联动操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '告警等级'" class="level-tag" :class="levelClass(row[column])">{{ row[column] || '—' }}</span>
            <span v-else-if="column === '抑制说明'" class="suppress-cell">{{ row[column] || '—' }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openReport(row)">上报读数</button>
            <button class="link" type="button" @click="openDetail(row)">点位详情</button>
            <RouterLink class="link" to="/gas_alarm">告警中心</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无气体监测数据，可先登记监测点位</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条气体监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 点位详情：等级、负责人、恢复状态与告警中心/处置记录同源 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <h3>点位详情 · {{ detail['点位']['点位编号'] }}</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <table class="data-table kv-table">
          <tbody>
            <tr><th>监测气体</th><td>{{ detail['点位']['监测气体'] }}</td><th>所在管沟</th><td>{{ detail['点位']['所在管沟'] }}</td></tr>
            <tr><th>当前浓度</th><td>{{ detail['点位']['当前浓度'] }}</td><th>点位状态</th><td>{{ detail['点位']['点位状态'] }}</td></tr>
            <tr>
              <th>告警等级</th><td><span class="level-tag" :class="levelClass(detail['点位']['告警等级'])">{{ detail['点位']['告警等级'] || '—' }}</span></td>
              <th>恢复状态</th><td>{{ detail['点位']['恢复状态'] || '—' }}</td>
            </tr>
            <tr><th>负责人</th><td>{{ detail['点位']['告警负责人'] || '—' }}</td><th>抑制说明</th><td>{{ detail['点位']['抑制说明'] || '—' }}</td></tr>
          </tbody>
        </table>
        <h4>处置编排</h4>
        <p v-if="!detail['处置编排']" class="page-tip">尚未配置处置编排，告警回退使用点位档案上的报警阈值，负责人默认值班长。</p>
        <table v-else class="data-table kv-table">
          <tbody>
            <tr><th>预警阈值</th><td>{{ detail['处置编排']['预警阈值'] }}</td><th>报警阈值</th><td>{{ detail['处置编排']['报警阈值'] }}</td></tr>
            <tr><th>负责人</th><td>{{ detail['处置编排']['负责人'] }}</td><th>通知方式</th><td>{{ detail['处置编排']['通知方式'] }}</td></tr>
          </tbody>
        </table>
        <h4>活动事件</h4>
        <p v-if="!detail['活动事件']" class="page-tip">当前没有进行中的告警事件。</p>
        <table v-else class="data-table kv-table">
          <tbody>
            <tr>
              <th>事件编号</th><td>{{ detail['活动事件']['事件编号'] }}</td>
              <th>等级</th><td><span class="level-tag" :class="levelClass(detail['活动事件']['当前等级'])">{{ detail['活动事件']['当前等级'] }}</span></td>
            </tr>
            <tr><th>负责人</th><td>{{ detail['活动事件']['负责人'] }}</td><th>恢复状态</th><td>{{ detail['活动事件']['恢复状态'] }}</td></tr>
          </tbody>
        </table>
        <h4>最近处置记录</h4>
        <table class="data-table">
          <thead><tr><th>记录时间</th><th>类型</th><th>等级</th><th>负责人</th><th>恢复状态</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="item in detail['最近记录']" :key="item.id">
              <td>{{ item['记录时间'] }}</td>
              <td>{{ item['记录类型'] }}{{ item['是否抑制'] ? '（抑制）' : '' }}</td>
              <td><span class="level-tag" :class="levelClass(item['等级'])">{{ item['等级'] || '—' }}</span></td>
              <td>{{ item['负责人'] || '—' }}</td>
              <td>{{ item['恢复状态'] || '—' }}</td>
              <td>{{ item['处置说明'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 上报读数：驱动告警引擎定级、抑制与恢复 -->
    <div v-if="reportForm" class="modal-mask" @click.self="reportForm = null">
      <form class="modal-card narrow" @submit.prevent="submitReport">
        <header class="modal-head"><h3>上报读数 · {{ reportForm.code }}</h3></header>
        <label class="form-item"><span>当前浓度</span><input v-model="reportConcentration" type="number" step="0.1" required /></label>
        <label class="form-item"><span>上报/处置人（换人即识别为交接）</span><input v-model="reportOperator" placeholder="如 赵抢修" /></label>
        <p class="page-tip">达到阈值自动定级；处置期间重复越限会按抖动、调阈、交接并入同一事件，回落到阈值以下自动恢复。</p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="reportForm = null">取消</button>
          <button class="btn primary" type="submit">提交读数</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Detail = Record<string, any>

const ENDPOINT = '/api/gas_detect'
const ALARM_ENDPOINT = '/api/gas_alarm'
const columns = ["点位编号", "监测气体", "所在管沟", "当前浓度", "报警阈值", "监测时间", "点位状态", "告警等级", "告警负责人", "恢复状态", "抑制说明"]
const statuses = ["正常", "预警值", "报警值", "离线"]
const stats = ref([{"label": "正常点位", "value": 0}, {"label": "预警点位", "value": 0}, {"label": "报警点位", "value": 0}])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["点位编号", "监测气体", "所在管沟"]

const detail = ref<Detail | null>(null)
const reportForm = ref<{ code: string } | null>(null)
const reportConcentration = ref('')
const reportOperator = ref('')

function levelClass(level: unknown) {
  if (level === '报警') return 'level-alarm'
  if (level === '预警') return 'level-warn'
  return ''
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openDetail(row: Row) {
  try {
    const response = await request(`${ALARM_ENDPOINT}/points/${encodeURIComponent(String(row['点位编号']))}/detail`)
    if (!response.ok) throw new Error('点位详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点位详情读取失败'
  }
}

function openReport(row: Row) {
  reportForm.value = { code: String(row['点位编号']) }
  reportConcentration.value = String(row['当前浓度'] ?? '')
  reportOperator.value = ''
}

async function submitReport() {
  if (!reportForm.value) return
  try {
    const response = await request(`${ALARM_ENDPOINT}/points/${encodeURIComponent(reportForm.value.code)}/readings`, {
      method: 'POST',
      body: JSON.stringify({
        concentration: Number(reportConcentration.value),
        operator: reportOperator.value || null,
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload?.ok) throw new Error(payload?.message || '读数上报失败')
    errorMessage.value = ''
    reportForm.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '读数上报失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('监测点位列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = rows.value.filter((row) => row['点位状态'] === '正常').length
    stats.value[1].value = rows.value.filter((row) => row['点位状态'] === '预警值').length
    stats.value[2].value = rows.value.filter((row) => row['点位状态'] === '报警值').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '气体监测列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.level-tag { padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #eef2f6; }
.level-warn { background: #fdf3d8; color: #9a6700; }
.level-alarm { background: #fde2e0; color: #b42318; }
.suppress-cell { color: #9a6700; font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: flex-start; justify-content: center; padding: 40px 16px; overflow-y: auto; z-index: 50; }
.modal-card { background: #fff; border-radius: 10px; padding: 16px 20px; width: min(860px, 100%); box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2); }
.modal-card.narrow { width: min(440px, 100%); }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-card h4 { margin: 14px 0 6px; font-size: 13px; color: var(--muted); }
.page-tip { color: var(--muted); font-size: 13px; }
.kv-table th { width: 90px; background: #f8fafc; color: var(--muted); font-weight: normal; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
</style>
