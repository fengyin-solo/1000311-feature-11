<template>
  <section class="page" data-module="gas_alarm">
    <header class="page-head">
      <div>
        <h2>气体告警联动处置</h2>
        <p class="page-desc">
          在监测点位、监测气体与阈值之间编排处置策略；同一事件的连续抖动、阈值调整与处置人交接会被识别合并，
          告警中心、处置记录与点位详情共用等级、负责人和恢复状态。
        </p>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in summaryCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.cls">{{ item.value }}</strong>
      </article>
    </div>

    <nav class="tab-bar">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="btn"
        :class="{ primary: activeTab === tab.key }"
        type="button"
        @click="switchTab(tab.key as 'events' | 'records' | 'rules')"
      >
        {{ tab.label }}
      </button>
    </nav>

    <p v-if="message" class="page-tip" :class="{ 'error-text': !messageOk }">{{ message }}</p>

    <!-- 告警中心 -->
    <div v-if="activeTab === 'events'">
      <form class="filter-bar" @submit.prevent="reloadEvents">
        <label class="filter-item">
          <span>恢复状态</span>
          <select v-model="eventFilter.status">
            <option value="">全部</option>
            <option value="未恢复">未恢复</option>
            <option value="处置中">处置中</option>
            <option value="已恢复">已恢复</option>
          </select>
        </label>
        <label class="filter-item">
          <span>等级</span>
          <select v-model="eventFilter.level">
            <option value="">全部</option>
            <option value="预警">预警</option>
            <option value="报警">报警</option>
          </select>
        </label>
        <label class="filter-item">
          <span>点位/事件编号</span>
          <input v-model="eventFilter.keyword" placeholder="如 GAS-0001" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in eventColumns" :key="column">{{ column }}</th>
            <th>抑制说明</th>
            <th>联动操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in events" :key="row.id">
            <td v-for="column in eventColumns" :key="column">
              <span v-if="column === '等级'" class="level-tag" :class="levelClass(row[column])">{{ row[column] }}</span>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="suppress-cell">{{ row['抑制说明'] || '—' }}</td>
            <td class="row-actions">
              <template v-if="row['事件状态'] === '处置中'">
                <button class="link" type="button" @click="openReport(row['点位编号'])">上报读数</button>
                <button class="link" type="button" @click="openHandle(row)">现场处置</button>
                <button class="link" type="button" @click="openHandover(row)">负责人交接</button>
              </template>
              <button class="link" type="button" @click="openTimeline(row)">处置记录</button>
            </td>
          </tr>
          <tr v-if="!events.length">
            <td :colspan="eventColumns.length + 2" class="empty-state">暂无告警事件，可在下方「处置编排」里维护阈值，或到气体监测页上报读数</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ eventTotal }} 条事件</span></footer>
    </div>

    <!-- 处置记录 -->
    <div v-if="activeTab === 'records'">
      <form class="filter-bar" @submit.prevent="reloadRecords">
        <label class="filter-item">
          <span>点位编号</span>
          <input v-model="recordFilter.point" placeholder="如 GAS-0001" />
        </label>
        <label class="filter-item">
          <span>抑制</span>
          <select v-model="recordFilter.suppressed">
            <option value="">全部</option>
            <option value="true">仅看抑制</option>
            <option value="false">仅看非抑制</option>
          </select>
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in recordColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in records" :key="row.id">
            <td v-for="column in recordColumns" :key="column">
              <span v-if="column === '是否抑制'" :class="row[column] ? 'suppress-tag' : ''">
                {{ row[column] ? '已抑制' : '—' }}
              </span>
              <span v-else-if="column === '等级'" class="level-tag" :class="levelClass(row[column])">{{ row[column] || '—' }}</span>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
          </tr>
          <tr v-if="!records.length">
            <td :colspan="recordColumns.length" class="empty-state">暂无处置记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ recordTotal }} 条记录（等级/负责人/恢复状态随事件实时同步）</span></footer>
    </div>

    <!-- 处置编排 -->
    <div v-if="activeTab === 'rules'">
      <div class="filter-bar">
        <button class="btn primary" type="button" @click="openRuleForm()">新增处置编排</button>
      </div>
      <table class="data-table">
        <thead>
          <tr><th v-for="column in ruleColumns" :key="column">{{ column }}</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in rules" :key="row.id">
            <td v-for="column in ruleColumns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openRuleForm(row)">调整阈值/负责人</button>
              <button class="link" type="button" @click="openReport(row['点位编号'])">上报读数</button>
            </td>
          </tr>
          <tr v-if="!rules.length">
            <td :colspan="ruleColumns.length + 1" class="empty-state">暂无处置编排</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 点位详情：与告警中心、处置记录同源 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <h3>点位详情 · {{ detail['点位']['点位编号'] }}</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <h4>点位档案（等级 / 负责人 / 恢复状态由联动事件回写）</h4>
        <table class="data-table kv-table">
          <tbody>
            <tr><th>监测气体</th><td>{{ detail['点位']['监测气体'] }}</td><th>所在管沟</th><td>{{ detail['点位']['所在管沟'] }}</td></tr>
            <tr><th>当前浓度</th><td>{{ detail['点位']['当前浓度'] }}</td><th>点位状态</th><td>{{ detail['点位']['点位状态'] }}</td></tr>
            <tr><th>告警等级</th><td><span class="level-tag" :class="levelClass(detail['点位']['告警等级'])">{{ detail['点位']['告警等级'] || '—' }}</span></td><th>恢复状态</th><td>{{ detail['点位']['恢复状态'] || '—' }}</td></tr>
            <tr><th>负责人</th><td>{{ detail['点位']['告警负责人'] || '—' }}</td><th>抑制说明</th><td>{{ detail['点位']['抑制说明'] || '—' }}</td></tr>
          </tbody>
        </table>
        <h4>处置编排</h4>
        <p v-if="!detail['处置编排']" class="page-tip">该点位尚未配置处置编排，告警将回退使用点位档案上的报警阈值，负责人默认值班长。</p>
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
            <tr><th>事件编号</th><td>{{ detail['活动事件']['事件编号'] }}</td><th>等级</th><td><span class="level-tag" :class="levelClass(detail['活动事件']['当前等级'])">{{ detail['活动事件']['当前等级'] }}</span></td></tr>
            <tr><th>负责人</th><td>{{ detail['活动事件']['负责人'] }}</td><th>恢复状态</th><td>{{ detail['活动事件']['恢复状态'] }}</td></tr>
            <tr><th>抑制说明</th><td colspan="3">{{ detail['活动事件']['抑制说明'] || '—' }}</td></tr>
          </tbody>
        </table>
        <h4>最近处置记录</h4>
        <table class="data-table">
          <thead><tr><th>记录时间</th><th>类型</th><th>等级</th><th>负责人</th><th>恢复状态</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="row in detail['最近记录']" :key="row.id">
              <td>{{ row['记录时间'] }}</td>
              <td>{{ row['记录类型'] }}{{ row['是否抑制'] ? '（抑制）' : '' }}</td>
              <td><span class="level-tag" :class="levelClass(row['等级'])">{{ row['等级'] || '—' }}</span></td>
              <td>{{ row['负责人'] || '—' }}</td>
              <td>{{ row['恢复状态'] || '—' }}</td>
              <td>{{ row['处置说明'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 上报读数 -->
    <div v-if="reportForm" class="modal-mask" @click.self="reportForm = null">
      <form class="modal-card" @submit.prevent="submitReport">
        <header class="modal-head"><h3>上报读数 · {{ reportForm.code }}</h3></header>
        <label class="form-item"><span>当前浓度</span><input v-model="reportForm.concentration" type="number" step="0.1" required /></label>
        <label class="form-item"><span>上报/处置人（换人即识别为交接）</span><input v-model="reportForm.operator" placeholder="如 赵抢修" /></label>
        <p class="page-tip">读数达到预警/报警阈值会自动定级；处置期间重复越限会按抖动、调阈、交接合并为同一事件。</p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="reportForm = null">取消</button>
          <button class="btn primary" type="submit">提交读数</button>
        </footer>
      </form>
    </div>

    <!-- 现场处置 -->
    <div v-if="handleForm" class="modal-mask" @click.self="handleForm = null">
      <div class="modal-card">
        <header class="modal-head"><h3>现场处置 · {{ handleForm['事件编号'] }}</h3></header>
        <label class="form-item"><span>处置人</span><input v-model="handleForm.operator" :placeholder="String(handleForm['负责人'])" /></label>
        <label class="form-item"><span>处置说明</span><input v-model="handleForm.note" placeholder="如 已开启排风、现场复测" /></label>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="handleForm = null">取消</button>
          <button class="btn" type="button" @click="submitHandle('处置')">记录处置</button>
          <button class="btn primary" type="button" @click="submitHandle('恢复')">确认恢复</button>
        </footer>
      </div>
    </div>

    <!-- 负责人交接 -->
    <div v-if="handoverForm" class="modal-mask" @click.self="handoverForm = null">
      <form class="modal-card" @submit.prevent="submitHandover">
        <header class="modal-head"><h3>负责人交接 · {{ handoverForm['事件编号'] }}</h3></header>
        <p class="page-tip">当前负责人：{{ handoverForm['负责人'] }}。交接后仍沿用同一事件，不重复开单。</p>
        <label class="form-item"><span>新负责人</span><input v-model="handoverForm.owner" required /></label>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="handoverForm = null">取消</button>
          <button class="btn primary" type="submit">确认交接</button>
        </footer>
      </form>
    </div>

    <!-- 处置编排表单 -->
    <div v-if="ruleForm" class="modal-mask" @click.self="ruleForm = null">
      <form class="modal-card" @submit.prevent="submitRule">
        <header class="modal-head"><h3>{{ ruleForm.id ? '调整处置编排' : '新增处置编排' }}</h3></header>
        <label class="form-item"><span>点位编号</span><input v-model="ruleForm['点位编号']" required :disabled="Boolean(ruleForm.id)" /></label>
        <label class="form-item"><span>监测气体</span><input v-model="ruleForm['监测气体']" required :disabled="Boolean(ruleForm.id)" /></label>
        <label class="form-item"><span>预警阈值</span><input v-model.number="ruleForm['预警阈值']" type="number" step="0.1" required /></label>
        <label class="form-item"><span>报警阈值</span><input v-model.number="ruleForm['报警阈值']" type="number" step="0.1" required /></label>
        <label class="form-item"><span>负责人</span><input v-model="ruleForm['负责人']" placeholder="默认 值班长" /></label>
        <label class="form-item"><span>通知方式</span><input v-model="ruleForm['通知方式']" placeholder="如 短信+工单" /></label>
        <p class="page-tip">调整阈值后 10 分钟内再次越限，会被识别为「阈值刚调整」并入同一事件。</p>
        <footer class="modal-foot">
          <button class="btn" type="button" @click="ruleForm = null">取消</button>
          <button class="btn primary" type="submit">保存编排</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

const ENDPOINT = '/api/gas_alarm'

type Row = Record<string, any>
type Detail = Record<string, any>

const tabs = [
  { key: 'events', label: '告警中心' },
  { key: 'records', label: '处置记录' },
  { key: 'rules', label: '处置编排' },
]
const activeTab = ref<'events' | 'records' | 'rules'>('events')

const eventColumns = ['事件编号', '点位编号', '监测气体', '等级', '负责人', '恢复状态', '首次上报时间', '最近上报时间', '最近读数', '上报次数', '事件状态']
const recordColumns = ['记录时间', '事件编号', '点位编号', '监测气体', '记录类型', '等级', '负责人', '恢复状态', '操作人', '是否抑制', '处置说明']
const ruleColumns = ['点位编号', '监测气体', '所在管沟', '预警阈值', '报警阈值', '负责人', '通知方式']

const summaryCards = ref([
  { label: '活动事件', value: 0, cls: '' },
  { label: '报警中', value: 0, cls: 'level-alarm' },
  { label: '预警中', value: 0, cls: 'level-warn' },
  { label: '已恢复', value: 0, cls: '' },
  { label: '抑制读数', value: 0, cls: 'suppress-tag' },
  { label: '编排规则', value: 0, cls: '' },
])

const events = ref<Row[]>([])
const eventTotal = ref(0)
const eventFilter = ref({ status: '', level: '', keyword: '' })

const records = ref<Row[]>([])
const recordTotal = ref(0)
const recordFilter = ref({ point: '', suppressed: '' })

const rules = ref<Row[]>([])

const message = ref('')
const messageOk = ref(true)
const detail = ref<Detail | null>(null)
const reportForm = ref<{ code: string; concentration: string; operator: string } | null>(null)
const handleForm = ref<(Row & { operator: string; note: string }) | null>(null)
const handoverForm = ref<(Row & { owner: string }) | null>(null)
const ruleForm = ref<Record<string, any> | null>(null)

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function levelClass(level: unknown) {
  if (level === '报警') return 'level-alarm'
  if (level === '预警') return 'level-warn'
  return ''
}

async function postJson(path: string, body: unknown) {
  const response = await request(`${ENDPOINT}${path}`, { method: 'POST', body: JSON.stringify(body) })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload) {
    throw new Error(payload?.detail ? String(payload.detail) : '操作未生效，请稍后重试')
  }
  return payload as { ok: boolean; message: string; entry?: Row }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    const data = await response.json()
    summaryCards.value[0].value = data['活动事件']
    summaryCards.value[1].value = data['报警中']
    summaryCards.value[2].value = data['预警中']
    summaryCards.value[3].value = data['已恢复']
    summaryCards.value[4].value = data['抑制读数']
    summaryCards.value[5].value = data['编排规则']
  } catch {
    // 统计读不出来不阻塞列表
  }
}

async function reloadEvents() {
  const query = new URLSearchParams()
  if (eventFilter.value.status) query.set('status', eventFilter.value.status)
  if (eventFilter.value.level) query.set('level', eventFilter.value.level)
  if (eventFilter.value.keyword) query.set('keyword', eventFilter.value.keyword)
  try {
    const response = await request(`${ENDPOINT}/events?${query.toString()}`)
    const payload = await response.json()
    events.value = payload.items ?? []
    eventTotal.value = payload.total ?? 0
  } catch (error) {
    flash(error instanceof Error ? error.message : '告警中心读取失败', false)
  }
}

async function reloadRecords() {
  const query = new URLSearchParams()
  if (recordFilter.value.point) query.set('point', recordFilter.value.point)
  if (recordFilter.value.suppressed) query.set('suppressed', recordFilter.value.suppressed)
  try {
    const response = await request(`${ENDPOINT}/records?${query.toString()}`)
    const payload = await response.json()
    records.value = payload.items ?? []
    recordTotal.value = payload.total ?? 0
  } catch (error) {
    flash(error instanceof Error ? error.message : '处置记录读取失败', false)
  }
}

async function reloadRules() {
  try {
    const response = await request(`${ENDPOINT}/rules`)
    const payload = await response.json()
    rules.value = payload.items ?? []
  } catch (error) {
    flash(error instanceof Error ? error.message : '处置编排读取失败', false)
  }
}

function switchTab(key: 'events' | 'records' | 'rules') {
  activeTab.value = key
  if (key === 'events') void reloadEvents()
  if (key === 'records') void reloadRecords()
  if (key === 'rules') void reloadRules()
}

function openReport(code: string) {
  reportForm.value = { code, concentration: '', operator: '' }
}

async function submitReport() {
  if (!reportForm.value) return
  const { code, concentration, operator } = reportForm.value
  try {
    const result = await postJson(`/points/${encodeURIComponent(code)}/readings`, {
      concentration: Number(concentration),
      operator: operator || null,
    })
    flash(result.message, result.ok)
    reportForm.value = null
    await Promise.all([loadSummary(), reloadEvents()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '读数上报失败', false)
  }
}

function openHandle(row: Row) {
  handleForm.value = { ...row, operator: '', note: '' }
}

async function submitHandle(action: string) {
  if (!handleForm.value) return
  const id = handleForm.value.id
  try {
    const result = await postJson(`/events/${id}/actions`, {
      action,
      operator: handleForm.value.operator || null,
      note: handleForm.value.note || null,
    })
    flash(result.message, result.ok)
    handleForm.value = null
    await Promise.all([loadSummary(), reloadEvents()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '现场处置失败', false)
  }
}

function openHandover(row: Row) {
  handoverForm.value = { ...row, owner: '' }
}

async function submitHandover() {
  if (!handoverForm.value) return
  const id = handoverForm.value.id
  try {
    const result = await postJson(`/events/${id}/handover`, { owner: handoverForm.value.owner })
    flash(result.message, result.ok)
    handoverForm.value = null
    await Promise.all([loadSummary(), reloadEvents()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '负责人交接失败', false)
  }
}

async function openTimeline(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/points/${encodeURIComponent(String(row['点位编号']))}/detail`)
    if (!response.ok) throw new Error('点位详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    flash(error instanceof Error ? error.message : '点位详情读取失败', false)
  }
}

function openRuleForm(row?: Row) {
  if (row) {
    ruleForm.value = { ...row }
  } else {
    ruleForm.value = {
      '点位编号': '',
      '监测气体': '',
      '预警阈值': 0,
      '报警阈值': 0,
      '负责人': '',
      '通知方式': '',
    }
  }
}

async function submitRule() {
  if (!ruleForm.value) return
  try {
    const result = await postJson('/rules', { values: ruleForm.value })
    flash(result.message, result.ok)
    ruleForm.value = null
    await Promise.all([loadSummary(), reloadRules()])
  } catch (error) {
    flash(error instanceof Error ? error.message : '处置编排保存失败', false)
  }
}

onMounted(() => {
  void loadSummary()
  void reloadEvents()
})
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin-bottom: 12px; }
.page-tip { margin: 6px 0 10px; color: var(--muted); font-size: 13px; }
.level-tag { padding: 1px 8px; border-radius: 10px; font-size: 12px; background: #eef2f6; }
.level-warn { background: #fdf3d8; color: #9a6700; }
.level-alarm { background: #fde2e0; color: #b42318; }
.suppress-tag { color: #9a6700; }
.suppress-cell { color: #9a6700; font-size: 12px; max-width: 260px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: flex-start; justify-content: center; padding: 40px 16px; overflow-y: auto; z-index: 50; }
.modal-card { background: #fff; border-radius: 10px; padding: 16px 20px; width: min(860px, 100%); box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2); }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.modal-head h3 { margin: 0; font-size: 16px; }
.modal-card h4 { margin: 14px 0 6px; font-size: 13px; color: var(--muted); }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-item input, .form-item select, .filter-item select { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.filter-item select { width: auto; min-width: 110px; }
.kv-table th { width: 90px; background: #f8fafc; color: var(--muted); font-weight: normal; }
</style>
