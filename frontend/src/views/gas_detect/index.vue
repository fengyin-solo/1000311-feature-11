<template>
  <section class="page" data-module="gas_detect">
    <header class="page-head">
      <div>
        <h2>气体监测管理</h2>
        <p class="page-desc">维护监测点位，围绕点位编号、监测气体、所在管沟、当前浓度做登记、筛选与状态流转；等级、负责人与恢复状态与告警联动中心实时同步。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn primary" to="/gas_alarm">告警联动中心</RouterLink>
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
          <th>负责人</th>
          <th>恢复状态</th>
          <th>关联事件</th>
          <th>联动操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row['负责人'] ?? '—' }}</td>
          <td>
            <span :class="['state-tag', row['恢复状态'] === '已恢复' ? 'ok' : 'open']">
              {{ row['恢复状态'] ?? '—' }}
            </span>
          </td>
          <td>{{ row['关联事件'] || '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">告警/处置详情</button>
            <RouterLink class="link" :to="`/gas_alarm`">去联动中心</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 4" class="empty-state">暂无气体监测数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条气体监测记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

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
          <div>
            <dt>等级（与告警中心同步）</dt>
            <dd><span class="level-tag" :data-level="detail.等级">{{ detail.等级 }}</span></dd>
          </div>
          <div><dt>负责人（与告警中心同步）</dt><dd>{{ detail.负责人 }}</dd></div>
          <div><dt>恢复状态</dt><dd>{{ detail.恢复状态 }}</dd></div>
          <div><dt>关联事件</dt><dd>{{ detail.关联事件 || '—' }}</dd></div>
          <div>
            <dt>预警 / 报警阈值</dt>
            <dd>{{ detail.处置编排.预警阈值 }} / {{ detail.处置编排.报警阈值 }}</dd>
          </div>
        </dl>
        <h4>处置记录时间线</h4>
        <ul class="timeline">
          <li v-for="record in detail.处置记录" :key="record.id" :class="{ suppressed: record.抑制 }">
            <strong>{{ record.记录时间 }} {{ record.记录类型 }}</strong>
            <span>{{ record.负责人 }} · {{ record.说明 }}</span>
          </li>
          <li v-if="!detail.处置记录.length">暂无处置记录</li>
        </ul>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/gas_detect'
const columns = ["点位编号", "监测气体", "所在管沟", "当前浓度", "报警阈值", "上次标定日", "监测时间", "点位状态"]
const filterFields = columns.slice(0, 3)

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const detail = ref<Record<string, any> | null>(null)

const stats = computed(() => [
  { label: "正常点位", value: rows.value.filter((row) => row['点位状态'] === '正常').length },
  { label: "预警点位", value: rows.value.filter((row) => row['点位状态'] === '预警值').length },
  { label: "报警点位", value: rows.value.filter((row) => row['点位状态'] === '报警值').length },
  { label: "处置中事件", value: rows.value.filter((row) => row['恢复状态'] === '未恢复').length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`/api/gas_alarm/points/${row.id}/detail`)
    if (!response.ok) {
      throw new Error('点位联动详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点位联动详情读取失败'
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
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '气体监测列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.state-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.state-tag.ok { background: #e7f6ec; color: #067647; }
.state-tag.open { background: #fde8e8; color: #b42318; }
.level-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.level-tag[data-level='正常'] { background: #e7f6ec; color: #067647; }
.level-tag[data-level='预警值'] { background: #fdf3e1; color: #b54708; }
.level-tag[data-level='报警值'] { background: #fde8e8; color: #b42318; }
.drawer-mask { position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45); display: flex; justify-content: flex-end; z-index: 20; }
.drawer { width: 460px; background: #fff; height: 100%; overflow-y: auto; padding: 16px 20px; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; }
.detail-list { margin: 0; }
.detail-list div { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px dashed var(--border); font-size: 13px; }
.detail-list dt { color: var(--muted); }
.detail-list dd { margin: 0; text-align: right; }
.timeline { list-style: none; margin: 8px 0 0; padding: 0; }
.timeline li { display: flex; flex-direction: column; gap: 2px; border-left: 3px solid var(--brand); padding: 6px 10px; margin-bottom: 6px; background: #f8fafc; font-size: 12px; }
.timeline li.suppressed { border-left-color: #7c8db5; background: #f8faff; }
</style>
