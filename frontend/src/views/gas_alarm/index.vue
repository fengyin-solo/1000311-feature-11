<template>
  <section class="page" data-module="gas_alarm">
    <header class="page-head">
      <div>
        <h2>气体告警联动处置</h2>
        <p class="page-desc">
          在监测点位、监测气体与阈值之间编排处置策略；同一点位连续抖动、阈值刚调整或处置人交接时，
          系统识别为同一事件并给出抑制说明，告警中心、处置记录与点位详情的等级、负责人、恢复状态保持同步。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="tab = 'rules'; loadRules">处置编排</button>
        <button class="btn primary" type="button" @click="tab = 'events'">告警中心</button>
        <button class="btn" type="button" @click="tab = 'records'; loadRecords">处置记录</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in cards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p v-for="(line, index) in suppressionRules" :key="index" class="suppress-hint">抑制口径：{{ line }}</p>

    <p v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</p>

    <!-- 告警中心 -->
    <template v-if="tab === 'events'">
      <form class="filter-bar" @submit.prevent="loadEvents">
        <label class="filter-item">
          <span>恢复状态</span>
          <select v-model="eventFilter.status">
            <option value="">全部</option>
            <option value="未恢复">未恢复</option>
            <option value="已恢复">已恢复</option>
          </select>
        </label>
        <label class="filter-item">
          <span>等级</span>
          <select v-model="eventFilter.level">
            <option value="">全部</option>
            <option value="预警值">预警值</option>
            <option value="报警值">报警值</option>
          </select>
        </label>
        <label class="filter-item">
          <span>点位/事件编号</span>
          <input v-model="eventFilter.keyword" placeholder="按点位或事件编号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>事件编号</th>
            <th>点位编号</th>
            <th>监测气体</th>
            <th>等级</th>
            <th>最新浓度</th>
            <th>负责人</th>
            <th>触发时间</th>
            <th>恢复状态</th>
            <th>抑制说明</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in events" :key="row.id">
            <td>{{ row.事件编号 }}</td>
            <td>{{ row.点位编号 }}</td>
            <td>{{ row.监测气体 }}</td>
            <td><span class="level-tag" :data-level="row.等级">{{ row.等级 }}</span></td>
            <td>{{ row.最新浓度 }}</td>
            <td>{{ row.负责人 }}</td>
            <td>{{ row.触发时间 }}</td>
            <td>{{ row.已恢复 ? '已恢复 ' + row.恢复时间 : '未恢复' }}</td>
            <td class="suppress-cell">
              <span v-if="row.抑制中" class="suppress-tag">同一事件已抑制 ×{{ row.重复上报次数 }}</span>
              <span v-else-if="row.重复上报次数" class="muted-text">并入 {{ row.重复上报次数 }} 次续报</span>
              <span v-else>—</span>
              <small v-if="row.抑制说明" class="suppress-detail">{{ row.抑制说明 }}</small>
            </td>
            <td class="row-actions">
              <template v-if="!row.已恢复">
                <button class="link" type="button" @click="openReport(row)">上报读数</button>
                <button class="link" type="button" @click="openHandover(row)">交接</button>
                <button class="link" type="button" @click="openDispose(row)">现场处置</button>
                <button class="link" type="button" @click="recover(row)">确认恢复</button>
              </template>
              <button class="link" type="button" @click="viewRecords(row.事件编号)">处置记录</button>
            </td>
          </tr>
          <tr v-if="!events.length">
            <td colspan="10" class="empty-state">暂无符合条件的告警事件</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ eventTotal }} 个事件</span></footer>
    </template>

    <!-- 处置编排 -->
    <template v-if="tab === 'rules'">
      <form class="filter-bar" @submit.prevent="simulateReading">
        <label class="filter-item">
          <span>选择点位（设备上报）</span>
          <select v-model="readingPoint">
            <option v-for="rule in rules" :key="rule.点位ID" :value="rule.点位ID">
              {{ rule.点位编号 }} · {{ rule.监测气体 }}
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>上报浓度</span>
          <input v-model="readingValue" placeholder="例如 12" />
        </label>
        <label class="filter-item">
          <span>上报人</span>
          <input v-model="readingReporter" placeholder="巡检/设备" />
        </label>
        <button class="btn primary" type="submit">上报读数</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th>点位编号</th>
            <th>监测气体</th>
            <th>预警阈值</th>
            <th>报警阈值</th>
            <th>负责人</th>
            <th>处置方式</th>
            <th>最近调阈值</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in rules" :key="rule.id">
            <td>{{ rule.点位编号 }}</td>
            <td>{{ rule.监测气体 }}</td>
            <td>{{ rule.预警阈值 }}</td>
            <td>{{ rule.报警阈值 }}</td>
            <td>{{ rule.负责人 }}</td>
            <td>{{ rule.处置方式 }}</td>
            <td>{{ rule.调整时间 || '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openThreshold(rule)">调整阈值</button>
              <button class="link" type="button" @click="viewPoint(rule.点位ID)">点位详情</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 处置记录 -->
    <template v-if="tab === 'records'">
      <form class="filter-bar" @submit.prevent="loadRecords">
        <label class="filter-item">
          <span>事件编号</span>
          <input v-model="recordFilter.event_no" placeholder="GAS-EVT-0001" />
        </label>
        <label class="filter-item">
          <span>只看被抑制的重复告警</span>
          <input v-model="recordFilter.suppressed_only" type="checkbox" @change="loadRecords" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>记录时间</th>
            <th>事件编号</th>
            <th>点位编号</th>
            <th>记录类型</th>
            <th>等级</th>
            <th>浓度</th>
            <th>负责人</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in records" :key="record.id" :class="{ 'row-suppressed': record.抑制 }">
            <td>{{ record.记录时间 }}</td>
            <td>{{ record.事件编号 }}</td>
            <td>{{ record.点位编号 }}</td>
            <td>
              <span v-if="record.抑制" class="suppress-tag">{{ record.记录类型 }}</span>
              <span v-else>{{ record.记录类型 }}</span>
            </td>
            <td><span class="level-tag" :data-level="record.等级">{{ record.等级 }}</span></td>
            <td>{{ record.浓度 }}</td>
            <td>{{ record.负责人 }}</td>
            <td>{{ record.说明 }}</td>
          </tr>
          <tr v-if="!records.length">
            <td colspan="8" class="empty-state">暂无处置记录</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot"><span>共 {{ recordTotal }} 条处置记录</span></footer>
    </template>

    <!-- 点位详情抽屉 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>{{ detail.点位.点位编号 }} 点位详情</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-list">
          <div><dt>监测气体</dt><dd>{{ detail.点位.监测气体 }}</dd></div>
          <div><dt>所在管沟</dt><dd>{{ detail.点位.所在管沟 }}</dd></div>
          <div><dt>当前浓度</dt><dd>{{ detail.点位.当前浓度 }}</dd></div>
          <div><dt>等级（与告警中心同步）</dt><dd><span class="level-tag" :data-level="detail.等级">{{ detail.等级 }}</span></dd></div>
          <div><dt>负责人（与告警中心同步）</dt><dd>{{ detail.负责人 }}</dd></div>
          <div><dt>恢复状态</dt><dd>{{ detail.恢复状态 }}</dd></div>
          <div><dt>关联事件</dt><dd>{{ detail.关联事件 || '—' }}</dd></div>
          <div><dt>预警 / 报警阈值</dt><dd>{{ detail.处置编排.预警阈值 }} / {{ detail.处置编排.报警阈值 }}</dd></div>
        </dl>
        <h4>处置记录时间线</h4>
        <ul class="timeline">
          <li v-for="record in detail.处置记录" :key="record.id" :class="{ suppressed: record.抑制 }">
            <strong>{{ record.记录时间 }} {{ record.记录类型 }}</strong>
            <span>{{ record.负责人 }} · {{ record.说明 }}</span>
          </li>
        </ul>
      </aside>
    </div>

    <!-- 通用弹窗：读数 / 交接 / 处置 / 阈值 -->
    <div v-if="dialog" class="drawer-mask" @click.self="dialog = null">
      <form class="dialog" @submit.prevent="submitDialog">
        <h3>{{ dialog.title }}</h3>

        <template v-if="dialog.kind === 'reading'">
          <label class="dialog-item"><span>上报浓度</span><input v-model="dialog.form.concentration" required /></label>
          <label class="dialog-item"><span>上报人</span><input v-model="dialog.form.reporter" /></label>
          <label class="dialog-item"><span>来源</span><input v-model="dialog.form.source" placeholder="便携仪巡检 / 固定式探头" /></label>
        </template>

        <template v-if="dialog.kind === 'handover'">
          <label class="dialog-item"><span>新负责人</span><input v-model="dialog.form.owner" required /></label>
          <label class="dialog-item"><span>交接备注</span><input v-model="dialog.form.note" placeholder="现场情况、注意事项" /></label>
        </template>

        <template v-if="dialog.kind === 'dispose'">
          <label class="dialog-item"><span>处置人</span><input v-model="dialog.form.operator" /></label>
          <label class="dialog-item"><span>处置措施</span><input v-model="dialog.form.action" required placeholder="强制通风、切断气源、复测等" /></label>
          <label class="dialog-item"><span>补充说明</span><input v-model="dialog.form.note" /></label>
        </template>

        <template v-if="dialog.kind === 'threshold'">
          <label class="dialog-item"><span>预警阈值</span><input v-model="dialog.form.warn" required /></label>
          <label class="dialog-item"><span>报警阈值</span><input v-model="dialog.form.alarm" required /></label>
          <label class="dialog-item"><span>调整人</span><input v-model="dialog.form.operator" /></label>
          <label class="dialog-item"><span>调整原因</span><input v-model="dialog.form.reason" /></label>
          <p class="muted-text">调整后 30 分钟宽限期内的越限读数会并入同一事件并说明抑制原因。</p>
        </template>

        <div class="dialog-actions">
          <button class="btn" type="button" @click="dialog = null">取消</button>
          <button class="btn primary" type="submit">确认</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>
interface Card { label: string; value: number }
interface DialogState {
  kind: 'reading' | 'handover' | 'dispose' | 'threshold'
  title: string
  pointId?: number
  eventId?: number
  form: Record<string, string>
}

const tab = ref<'events' | 'rules' | 'records'>('events')
const cards = ref<Card[]>([])
const suppressionRules = ref<string[]>([])
const message = ref('')
const messageOk = ref(true)

const events = ref<Row[]>([])
const eventTotal = ref(0)
const eventFilter = ref({ status: '未恢复', level: '', keyword: '' })

const rules = ref<Row[]>([])
const readingPoint = ref(0)
const readingValue = ref('')
const readingReporter = ref('')

const records = ref<Row[]>([])
const recordTotal = ref(0)
const recordFilter = ref<{ event_no: string; suppressed_only: boolean }>({ event_no: '', suppressed_only: false })

const detail = ref<Record<string, any> | null>(null)
const dialog = ref<DialogState | null>(null)

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function loadCenter() {
  const response = await request('/api/gas_alarm/center')
  if (response.ok) {
    const payload = await response.json()
    cards.value = payload.cards
    suppressionRules.value = payload.抑制口径
  }
}

async function loadEvents() {
  const params = new URLSearchParams()
  Object.entries(eventFilter.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const response = await request(`/api/gas_alarm/events?${params.toString()}`)
  if (!response.ok) {
    flash('告警事件读取失败', false)
    return
  }
  const payload = await response.json()
  events.value = payload.items ?? []
  eventTotal.value = payload.total ?? 0
}

async function loadRules() {
  const response = await request('/api/gas_alarm/rules')
  if (!response.ok) {
    flash('处置编排读取失败', false)
    return
  }
  const payload = await response.json()
  rules.value = payload.items ?? []
  if (!readingPoint.value && rules.value[0]) {
    readingPoint.value = Number(rules.value[0].点位ID)
  }
}

async function loadRecords() {
  const params = new URLSearchParams()
  if (recordFilter.value.event_no) params.set('event_no', recordFilter.value.event_no)
  if (recordFilter.value.suppressed_only) params.set('suppressed_only', 'true')
  const response = await request(`/api/gas_alarm/records?${params.toString()}`)
  if (!response.ok) {
    flash('处置记录读取失败', false)
    return
  }
  const payload = await response.json()
  records.value = payload.items ?? []
  recordTotal.value = payload.total ?? 0
}

async function refreshAll() {
  await Promise.all([loadCenter(), loadEvents(), loadRules(), loadRecords()])
}

async function postJson(path: string, body: Record<string, unknown>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return response.json()
}

async function simulateReading() {
  if (!readingPoint.value || readingValue.value === '') {
    flash('请选择点位并填写上报浓度', false)
    return
  }
  const payload = await postJson(`/api/gas_alarm/points/${readingPoint.value}/readings`, {
    values: { concentration: readingValue.value, reporter: readingReporter.value, source: '便携仪巡检' },
  })
  flash(payload.message, payload.ok)
  readingValue.value = ''
  await refreshAll()
}

function openReport(row: Row) {
  dialog.value = {
    kind: 'reading',
    title: `上报读数 · ${row.事件编号}`,
    pointId: Number(row.点位ID),
    form: { concentration: String(row.最新浓度 ?? ''), reporter: String(row.负责人 ?? ''), source: '' },
  }
}

function openHandover(row: Row) {
  dialog.value = {
    kind: 'handover',
    title: `处置人交接 · ${row.事件编号}`,
    eventId: Number(row.id),
    form: { owner: '', note: '' },
  }
}

function openDispose(row: Row) {
  dialog.value = {
    kind: 'dispose',
    title: `现场处置 · ${row.事件编号}`,
    eventId: Number(row.id),
    form: { operator: String(row.负责人 ?? ''), action: '', note: '' },
  }
}

function openThreshold(row: Row) {
  dialog.value = {
    kind: 'threshold',
    title: `调整阈值 · ${row.点位编号} ${row.监测气体}`,
    pointId: Number(row.点位ID),
    form: {
      warn: String(row.预警阈值 ?? ''),
      alarm: String(row.报警阈值 ?? ''),
      operator: '',
      reason: '',
    },
  }
}

async function recover(row: Row) {
  const payload = await postJson(`/api/gas_alarm/events/${Number(row.id)}/recover`, {
    values: { operator: String(row.负责人 ?? '') },
  })
  flash(payload.message, payload.ok)
  await refreshAll()
}

async function viewRecords(eventNo: string) {
  tab.value = 'records'
  recordFilter.value = { event_no: eventNo, suppressed_only: false }
  await loadRecords()
}

async function viewPoint(pointId: number) {
  const response = await request(`/api/gas_alarm/points/${pointId}/detail`)
  if (!response.ok) {
    flash('点位详情读取失败', false)
    return
  }
  detail.value = await response.json()
}

async function submitDialog() {
  const state = dialog.value
  if (!state) return
  let payload: { ok: boolean; message: string; suppressed?: boolean }
  if (state.kind === 'reading') {
    payload = await postJson(`/api/gas_alarm/points/${state.pointId}/readings`, { values: state.form })
  } else if (state.kind === 'threshold') {
    payload = await postJson(`/api/gas_alarm/rules/${state.pointId}/threshold`, { values: state.form })
  } else {
    const actionPath = state.kind === 'handover' ? 'handover' : 'dispose'
    payload = await postJson(`/api/gas_alarm/events/${state.eventId}/${actionPath}`, { values: state.form })
  }
  dialog.value = null
  flash(payload.suppressed ? `已抑制并归入同一事件：${payload.message}` : payload.message, payload.ok)
  await refreshAll()
}

onMounted(refreshAll)
</script>

<style scoped>
.suppress-hint { margin: 0 0 6px; font-size: 12px; color: var(--muted); }
.ok-text { color: #067647; font-size: 13px; }
.muted-text { color: var(--muted); font-size: 12px; }
.level-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.level-tag[data-level='正常'] { background: #e7f6ec; color: #067647; }
.level-tag[data-level='预警值'] { background: #fdf3e1; color: #b54708; }
.level-tag[data-level='报警值'] { background: #fde8e8; color: #b42318; }
.suppress-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; background: #eef2ff; color: #344054; font-size: 12px; }
.suppress-cell { max-width: 260px; }
.suppress-detail { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
.row-suppressed td { background: #f8faff; }
.drawer-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; justify-content: flex-end; z-index: 20; }
.drawer { width: 460px; background: #fff; height: 100%; overflow-y: auto; padding: 16px 20px; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.detail-list { margin: 0; }
.detail-list div { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border); font-size: 13px; }
.detail-list dt { color: var(--muted); }
.detail-list dd { margin: 0; }
.timeline { list-style: none; margin: 8px 0 0; padding: 0; }
.timeline li { display: flex; flex-direction: column; gap: 2px; border-left: 3px solid var(--brand); padding: 6px 10px; margin-bottom: 6px; background: #f8fafc; font-size: 12px; }
.timeline li.suppressed { border-left-color: #7c8db5; background: #f8faff; }
.dialog { width: 380px; margin: auto; background: #fff; border-radius: 10px; padding: 18px 20px; }
.dialog-item { display: block; margin-bottom: 10px; font-size: 13px; }
.dialog-item span { display: block; color: var(--muted); margin-bottom: 4px; }
.dialog-item input { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.filter-item select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>
