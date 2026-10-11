/* 培训师系统前端逻辑 */

// ────────────── 工具 ──────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(url, options = {}) {
  if (options.body) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({ ok: false, msg: '响应解析失败' }));
  if (!resp.ok) {
    const e = new Error(data.msg || `请求失败 (${resp.status})`);
    e.status = resp.status;
    e.data = data;
    throw e;
  }
  return data;
}

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = isError ? 'error' : '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3000);
}

const TRAINER_STATUS = { active: '在职', inactive: '离职' };
const TRAINEE_STATUS = { active: '在读', graduated: '毕业', inactive: '退出' };

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ────────────── Tab 切换 ──────────────
$$('#tabs .tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('#tabs .tab').forEach((b) => b.classList.toggle('active', b === btn));
    $$('.panel').forEach((p) => p.classList.remove('active'));
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'trainers') { loadTrainers(); loadTrainees(); }
    if (btn.dataset.tab === 'bindings') loadBindingsTab();
  });
});

// ────────────── UID 速查（首页） ──────────────
const COMPARE_LABELS = {
  week_level: '当周等级',
  week_schedule_days: '排档天数',
  daily_task_count: '每日任务',
  week_revenue: '礼物流水',
  week_accompany_time: '陪档时长',
  week_rank: '周排名',
  total_revenue: '累计流水',
  best_4week_level: '4周最高等级',
  hall: '所属大厅',
  is_elite: '精英队长',
};

async function initUidQuery() {
  try {
    const r = await api('/api/uid-query/types');
    $('#uq-type').innerHTML = r.items.map((t) => `<option value="${t.key}">${t.label}</option>`).join('');
  } catch (e) {
    $('#uq-type').innerHTML = '<option value="game">新队长-游戏</option>';
  }
}

$('#uq-submit').addEventListener('click', async () => {
  const uid = $('#uq-uid').value.trim();
  const captain_type = $('#uq-type').value;
  if (!uid) return toast('请输入 UID', true);
  const btn = $('#uq-submit');
  btn.disabled = true;
  btn.textContent = '查询中…';
  $('#uq-result').innerHTML = '';
  $('#slots-panel').classList.add('hidden');
  $('#rewards-panel').classList.add('hidden');
  try {
    const r = await api('/api/uid-query', { method: 'POST', body: { uid, captain_type } });
    if (r.slots) renderSlotsPanel(r.slots);
    if (r.rewards_panel) renderRewardsPanel(r.rewards_panel);
    renderUidResult(r.result);
  } catch (e) {
    $('#uq-result').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '查询';
  }
});

function renderUidResult(res) {
  const box = $('#uq-result');
  if (!res.this_week.data.found && !res.last_week.data.found) {
    box.innerHTML = '<div class="empty">未找到该 UID 的数据</div>';
    return;
  }
  const cards = Object.entries(COMPARE_LABELS).map(([key, label]) => {
    const c = res.compare[key];
    if (!c) return '';
    return `<div class="uq-item">
      <div class="k">${label}</div>
      <div class="v">本周 ${esc(c.this)} ｜ 上周 ${esc(c.last)}</div>
      <div class="c ${c.trend || 'flat'}">${esc(c.change || '')}</div>
    </div>`;
  }).join('');
  box.innerHTML = `
    <div class="uq-head">${esc(res.nickname || res.uid)}（${esc(res.type_label)}）</div>
    <div class="muted">本周 ${esc(res.this_week.period)} ｜ 上周 ${esc(res.last_week.period)}</div>
    <div class="uq-grid">${cards}</div>`;
}

// ────────────── 名额面板 ──────────────
let currentSlotsTrainerId = null;

function renderSlotsPanel(s) {
  currentSlotsTrainerId = s.trainer.id;
  $('#slots-month').textContent = `（${esc(s.trainer.nickname)} · ${s.month}）`;
  const overTag = s.over ? '<span class="tag over">已超额！</span>' : '';
  $('#slots-summary').innerHTML = `
    <span class="slot-chip">基础 <b>${s.base_slots}</b></span> +
    <span class="slot-chip">额外 <b>${s.extra_slots}</b></span> =
    <span class="slot-chip total">总名额 <b>${s.total_slots}</b>（上限 ${s.slot_cap}）</span>
    <span class="slot-chip ${s.over ? 'warn' : ''}">已绑定 <b>${s.used_slots}</b> / ${s.total_slots}</span>
    ${overTag}`;
  const tbody = $('#slots-table tbody');
  tbody.innerHTML = s.trainees.length ? s.trainees.map((t) => `
    <tr>
      <td>${esc(t.nickname)}</td>
      <td>${esc(t.uid)}</td>
      <td>${esc(t.bound_at)}</td>
      <td>${esc(t.best_level)}</td>
      <td>${t.slot_plus > 0 ? `<span class="tag plus">+${t.slot_plus}</span>` : '<span class="muted">+0</span>'}</td>
      <td class="muted">${esc(t.last_queried_at || '本月未查询')}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">当前无生效绑定</td></tr>';
  $('#slots-refresh-result').textContent = '';
  $('#slots-panel').classList.remove('hidden');
}

$('#slots-refresh').addEventListener('click', async () => {
  if (!currentSlotsTrainerId) return;
  const btn = $('#slots-refresh');
  btn.disabled = true;
  btn.textContent = '逐个查询中…';
  try {
    const r = await api(`/api/trainers/${currentSlotsTrainerId}/refresh-trainees`, { method: 'POST' });
    renderSlotsPanel(r.slots);
    const errMsg = r.errors.length ? `，${r.errors.length} 人失败：${r.errors.map((e) => e.nickname).join('、')}` : '';
    $('#slots-refresh-result').textContent = `已刷新 ${r.queried.length} 人${errMsg}`;
    toast('学员数据已刷新');
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '刷新全部学员数据';
  }
});

// ────────────── 奖励面板 ──────────────
const REWARD_STATUS = {
  granted: { text: '已发放', cls: 'active' },
  pending: { text: '待发放', cls: 'graduated' },
  ineligible: { text: '未达标', cls: 'inactive' },
};

function renderRewardsPanel(p) {
  $('#rewards-window').textContent = `（${esc(p.trainee.nickname)} · 绑定起 ${p.window_days} 天内有效）`;
  if (p.binding) {
    $('#rewards-binding').innerHTML =
      `当前绑定：培训师 <b>${esc(p.binding.trainer_nickname)}</b>（${esc(p.binding.trainer_uid)}）｜ ` +
      `绑定时间 ${esc(p.binding.bound_at)} ｜ 截止 ${esc(p.window_end)} ｜ ` +
      (p.in_window ? `剩余 <b>${p.days_left}</b> 天` : '<span class="tag over">已过奖励有效期</span>');
  } else {
    $('#rewards-binding').textContent = '当前无生效绑定，无法产生奖励';
  }
  $('#rewards-table tbody').innerHTML = p.rewards.map((r) => {
    const st = REWARD_STATUS[r.status];
    const action = r.status === 'pending'
      ? `<button class="btn small primary" onclick="grantReward(${r.grant_id})">标记已发</button>`
      : r.status === 'granted'
        ? `<button class="btn small" onclick="revokeReward(${r.grant_id})">撤销</button>`
        : '';
    return `<tr>
      <td>${esc(r.label)}</td>
      <td>${r.amount} × 2</td>
      <td><span class="tag ${st.cls}">${st.text}</span></td>
      <td class="muted">${esc(r.granted_at || '—')}</td>
      <td>${action}</td>
    </tr>`;
  }).join('');
  $('#rewards-panel').classList.remove('hidden');
}

async function grantReward(id) {
  try {
    await api(`/api/rewards/${id}/grant`, { method: 'POST' });
    toast('已标记发放');
    refreshRewardsPanel();
  } catch (e) {
    toast(e.message, true);
  }
}

async function revokeReward(id) {
  if (!confirm('确认撤销发放标记？')) return;
  try {
    await api(`/api/rewards/${id}/revoke`, { method: 'POST' });
    toast('已撤销');
    refreshRewardsPanel();
  } catch (e) {
    toast(e.message, true);
  }
}

async function refreshRewardsPanel() {
  // 重新拉当前速查 UID 的面板（不重新爬取）
  const uid = $('#uq-uid').value.trim();
  const t = await api('/api/trainees?kw=' + encodeURIComponent(uid));
  const me = t.items.find((x) => x.uid === uid);
  if (!me) return;
  const r = await api(`/api/trainees/${me.id}/rewards`);
  renderRewardsPanel(r.rewards_panel);
}

// ────────────── 绑定关系 ──────────────
let bindingsActiveView = true;

async function loadBindingsTab() {
  await Promise.all([loadBindSelects(), loadBindings()]);
}

async function loadBindSelects() {
  const keepTrainer = $('#bind-trainer').value;
  const keepTrainee = $('#bind-trainee').value;
  const [trainers, trainees] = await Promise.all([
    api('/api/trainers'), api('/api/trainees?status=active'),
  ]);
  $('#bind-trainer').innerHTML = trainers.items
    .filter((t) => t.status === 'active')
    .map((t) => `<option value="${t.id}">${esc(t.nickname)}（${esc(t.uid)}）名额 ${t.active_trainee_count}/${t.total_slots}</option>`)
    .join('') || '<option value="">（无在职培训师）</option>';
  $('#bind-trainee').innerHTML = trainees.items
    .map((t) => {
      const bound = t.trainer_nickname ? `｜已绑定:${esc(t.trainer_nickname)}` : '';
      return `<option value="${t.id}">${esc(t.nickname)}（${esc(t.uid)}）${bound}</option>`;
    })
    .join('') || '<option value="">（无在读妹妹）</option>';
  if (keepTrainer) $('#bind-trainer').value = keepTrainer;
  if (keepTrainee) $('#bind-trainee').value = keepTrainee;
}

// ────────────── 绑定页内联快捷建档 ──────────────
function toggleQuickAdd(kind, show) {
  $(`#${kind}-select-wrap`).classList.toggle('hidden', show);
  $(`#${kind}-add-wrap`).classList.toggle('hidden', !show);
  $(`#bind-add-${kind}`).style.display = show ? 'none' : '';
  if (show) {
    $(`#qa-${kind}-uid`).value = '';
    $(`#qa-${kind}-nickname`).value = '';
    $(`#qa-${kind}-hall`).value = '';
    if (kind === 'trainer') $('#qa-trainer-slots').value = 2;
    $(`#qa-${kind}-uid`).focus();
  }
}

['trainer', 'trainee'].forEach((kind) => {
  $(`#bind-add-${kind}`).addEventListener('click', () => toggleQuickAdd(kind, true));
  $(`#qa-${kind}-cancel`).addEventListener('click', () => toggleQuickAdd(kind, false));

  $(`#qa-${kind}-autofill`).addEventListener('click', async () => {
    const uid = $(`#qa-${kind}-uid`).value.trim();
    if (!uid) return toast('请先输入 UID', true);
    const btn = $(`#qa-${kind}-autofill`);
    btn.disabled = true;
    try {
      const r = await api(`/api/uid-lookup?uid=${encodeURIComponent(uid)}`);
      if (!r.found) return toast(r.msg || '未找到该 UID', true);
      if (r.info.nickname) $(`#qa-${kind}-nickname`).value = r.info.nickname;
      if (r.info.hall_name) $(`#qa-${kind}-hall`).value = r.info.hall_name;
      toast(`已回填：${r.info.nickname}${r.info.week_level ? `（${r.info.week_level}）` : ''}`);
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  $(`#qa-${kind}-save`).addEventListener('click', async () => {
    const body = {
      uid: $(`#qa-${kind}-uid`).value.trim(),
      nickname: $(`#qa-${kind}-nickname`).value.trim(),
      hall_name: $(`#qa-${kind}-hall`).value.trim(),
    };
    if (kind === 'trainer') body.base_slots = +$('#qa-trainer-slots').value;
    try {
      const r = await api(PERSON_CONF[`${kind}s`].url, { method: 'POST', body });
      toast('建档成功，已选用');
      toggleQuickAdd(kind, false);
      await loadBindSelects();
      $(`#bind-${kind}`).value = r.id;
    } catch (e) {
      toast(e.message, true);
    }
  });
});

async function loadBindings() {
  const data = await api(`/api/bindings?active=${bindingsActiveView ? 1 : 0}`);
  const tbody = $('#bindings-table tbody');
  $$('.col-unbound').forEach((el) => (el.style.display = bindingsActiveView ? 'none' : ''));
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">暂无${bindingsActiveView ? '生效绑定' : '历史记录'}</td></tr>`;
    return;
  }
  tbody.innerHTML = data.items.map((b) => `
    <tr>
      <td>${esc(b.trainer_nickname)}</td>
      <td>${esc(b.trainer_uid)}</td>
      <td>${esc(b.trainee_nickname)}</td>
      <td>${esc(b.trainee_uid)}</td>
      <td>${esc(b.hall_name || '')}</td>
      <td>${esc(b.bound_at)}</td>
      <td class="col-unbound" style="display:${bindingsActiveView ? 'none' : ''}">${esc(b.unbound_at || '')}</td>
      <td>${esc(b.note || '')}</td>
      <td>
        ${bindingsActiveView ? `<button class="btn small danger" onclick="unbind(${b.id})">解绑</button>` : ''}
        <button class="btn small" onclick="gotoUidQuery('${esc(b.trainee_uid)}')">速查</button>
      </td>
    </tr>`).join('');
}

$('#seg-active').addEventListener('click', () => {
  bindingsActiveView = true;
  $('#seg-active').classList.add('active');
  $('#seg-history').classList.remove('active');
  loadBindings();
});
$('#seg-history').addEventListener('click', () => {
  bindingsActiveView = false;
  $('#seg-history').classList.add('active');
  $('#seg-active').classList.remove('active');
  loadBindings();
});

$('#bind-submit').addEventListener('click', async () => {
  const trainer_id = $('#bind-trainer').value;
  const trainee_id = $('#bind-trainee').value;
  const note = $('#bind-note').value;
  if (!trainer_id || !trainee_id) return toast('请选择培训师和妹妹', true);
  await doBind({ trainer_id: +trainer_id, trainee_id: +trainee_id, note });
});

async function doBind(payload) {
  try {
    const r = await api('/api/bindings', { method: 'POST', body: payload });
    toast(r.rebound ? '换绑成功' : '绑定成功');
    $('#bind-note').value = '';
    loadBindingsTab();
  } catch (e) {
    if (e.status === 409 && e.data && e.data.conflict) {
      if (confirm(e.data.msg)) {
        await doBind({ ...payload, force: true });
      }
    } else {
      toast(e.message, true);
    }
  }
}

async function unbind(id) {
  if (!confirm('确认解绑？')) return;
  try {
    await api(`/api/bindings/${id}/unbind`, { method: 'POST' });
    toast('已解绑');
    loadBindingsTab();
  } catch (e) {
    toast(e.message, true);
  }
}

function gotoUidQuery(uid) {
  $('[data-tab="uidquery"]').click();
  $('#uq-uid').value = uid;
  $('#uq-submit').click();
}

// ────────────── 档案管理（培训师/妹妹共用） ──────────────
const PERSON_CONF = {
  trainers: { url: '/api/trainers', kw: '#trainer-kw', table: '#trainers-table', statuses: TRAINER_STATUS },
  trainees: { url: '/api/trainees', kw: '#trainee-kw', table: '#trainees-table', statuses: TRAINEE_STATUS },
};

async function loadTrainers() {
  const conf = PERSON_CONF.trainers;
  const kw = $(conf.kw).value.trim();
  const data = await api(`${conf.url}${kw ? `?kw=${encodeURIComponent(kw)}` : ''}`);
  const tbody = $(`${conf.table} tbody`);
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无数据</td></tr>';
    return;
  }
  tbody.innerHTML = data.items.map((t) => `
    <tr>
      <td>${esc(t.uid)}</td>
      <td>${esc(t.nickname)}</td>
      <td>${esc(t.hall_name || '')}</td>
      <td><span class="tag ${t.status}">${conf.statuses[t.status] || t.status}</span></td>
      <td>${t.active_trainee_count} / ${t.total_slots}${t.active_trainee_count > t.total_slots ? ' <span class="tag over">超</span>' : ''}</td>
      <td>${esc(t.note || '')}</td>
      <td>
        <button class="btn small" onclick="gotoUidQuery('${esc(t.uid)}')">速查</button>
        <button class="btn small" onclick='openPersonModal("trainers", ${JSON.stringify(t)})'>编辑</button>
        <button class="btn small danger" onclick="delPerson('trainers', ${t.id})">删除</button>
      </td>
    </tr>`).join('');
}

async function loadTrainees() {
  const conf = PERSON_CONF.trainees;
  const kw = $(conf.kw).value.trim();
  const status = $('#trainee-status-filter').value;
  const params = new URLSearchParams();
  if (kw) params.set('kw', kw);
  if (status) params.set('status', status);
  const data = await api(`${conf.url}?${params}`);
  const tbody = $(`${conf.table} tbody`);
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无数据</td></tr>';
    return;
  }
  tbody.innerHTML = data.items.map((t) => `
    <tr>
      <td>${esc(t.uid)}</td>
      <td>${esc(t.nickname)}</td>
      <td>${esc(t.hall_name || '')}</td>
      <td><span class="tag ${t.status}">${conf.statuses[t.status] || t.status}</span></td>
      <td>${t.trainer_nickname ? `${esc(t.trainer_nickname)}（${esc(t.trainer_uid)}）` : '<span class="muted">未绑定</span>'}</td>
      <td>${esc(t.note || '')}</td>
      <td>
        <button class="btn small" onclick="gotoUidQuery('${esc(t.uid)}')">速查</button>
        <button class="btn small" onclick='openPersonModal("trainees", ${JSON.stringify(t)})'>编辑</button>
        <button class="btn small danger" onclick="delPerson('trainees', ${t.id})">删除</button>
      </td>
    </tr>`).join('');
}

let searchTimer = null;
$('#trainer-kw').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadTrainers, 300);
});
$('#trainee-kw').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadTrainees, 300);
});
$('#trainee-status-filter').addEventListener('change', loadTrainees);

async function delPerson(kind, id) {
  if (!confirm('确认删除？历史绑定记录会保留。')) return;
  try {
    await api(`${PERSON_CONF[kind].url}/${id}`, { method: 'DELETE' });
    toast('已删除');
    kind === 'trainers' ? loadTrainers() : loadTrainees();
  } catch (e) {
    toast(e.message, true);
  }
}

// ────────────── 档案弹窗 ──────────────
function openPersonModal(kind, person) {
  const conf = PERSON_CONF[kind];
  $('#pm-kind').value = kind;
  $('#pm-title').textContent = person
    ? `编辑${kind === 'trainers' ? '培训师' : '妹妹'}`
    : `新增${kind === 'trainers' ? '培训师' : '妹妹'}`;
  $('#pm-id').value = person ? person.id : '';
  $('#pm-uid').value = person ? person.uid : '';
  $('#pm-nickname').value = person ? person.nickname : '';
  $('#pm-hall').value = person ? (person.hall_name || '') : '';
  $('#pm-note').value = person ? (person.note || '') : '';
  $('#pm-slots-row').style.display = kind === 'trainers' ? '' : 'none';
  $('#pm-slots').value = person && person.base_slots != null ? person.base_slots : 2;
  $('#pm-status').innerHTML = Object.entries(conf.statuses)
    .map(([k, v]) => `<option value="${k}" ${person && person.status === k ? 'selected' : ''}>${v}</option>`)
    .join('');
  $('#person-modal').classList.remove('hidden');
}

$('#trainer-add').addEventListener('click', () => openPersonModal('trainers', null));
$('#trainee-add').addEventListener('click', () => openPersonModal('trainees', null));
$('#pm-cancel').addEventListener('click', () => $('#person-modal').classList.add('hidden'));

$('#pm-autofill').addEventListener('click', async () => {
  const uid = $('#pm-uid').value.trim();
  if (!uid) return toast('请先输入 UID', true);
  const btn = $('#pm-autofill');
  btn.disabled = true;
  try {
    const r = await api(`/api/uid-lookup?uid=${encodeURIComponent(uid)}`);
    if (!r.found) return toast(r.msg || '未找到该 UID', true);
    if (r.info.nickname) $('#pm-nickname').value = r.info.nickname;
    if (r.info.hall_name) $('#pm-hall').value = r.info.hall_name;
    toast(`已回填：${r.info.nickname}${r.info.week_level ? `（${r.info.week_level}）` : ''}`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

$('#pm-save').addEventListener('click', async () => {
  const kind = $('#pm-kind').value;
  const id = $('#pm-id').value;
  const body = {
    uid: $('#pm-uid').value.trim(),
    nickname: $('#pm-nickname').value.trim(),
    hall_name: $('#pm-hall').value.trim(),
    status: $('#pm-status').value,
    note: $('#pm-note').value.trim(),
  };
  if (kind === 'trainers') body.base_slots = +$('#pm-slots').value;
  try {
    if (id) {
      await api(`${PERSON_CONF[kind].url}/${id}`, { method: 'PUT', body });
    } else {
      await api(PERSON_CONF[kind].url, { method: 'POST', body });
    }
    toast('已保存');
    $('#person-modal').classList.add('hidden');
    kind === 'trainers' ? loadTrainers() : loadTrainees();
  } catch (e) {
    toast(e.message, true);
  }
});

// ────────────── 历史数据导入 ──────────────
$('#trainee-import').addEventListener('click', async () => {
  try {
    const r = await api('/api/trainees/import-candidates');
    $('#import-snap').textContent = r.snapshot_date ? `（快照日期 ${r.snapshot_date}）` : '';
    const list = $('#import-list');
    if (!r.items.length) {
      list.innerHTML = '<div class="empty">历史快照中没有妹妹数据</div>';
    } else {
      list.innerHTML = r.items.map((it) => `
        <label class="import-item ${it.already ? 'disabled' : ''}">
          <input type="checkbox" value="${esc(it.uid)}" ${it.already ? 'disabled' : ''}>
          <span>${esc(it.nickname)}（${esc(it.uid)}）</span>
          <span class="muted">${esc(it.hall_name || '')}${it.active ? '' : '｜已解散'}${it.already ? '｜已建档' : ''}</span>
        </label>`).join('');
    }
    updateImportCount();
    $('#import-modal').classList.remove('hidden');
  } catch (e) {
    toast(e.message, true);
  }
});

function updateImportCount() {
  const n = $$('#import-list input:checked').length;
  $('#import-count').textContent = n ? `已选 ${n} 人` : '';
}

$('#import-list').addEventListener('change', updateImportCount);
$('#import-all').addEventListener('click', () => {
  $$('#import-list input:not(:disabled)').forEach((c) => (c.checked = true));
  updateImportCount();
});
$('#import-cancel').addEventListener('click', () => $('#import-modal').classList.add('hidden'));
$('#import-submit').addEventListener('click', async () => {
  const uids = [...$$('#import-list input:checked')].map((c) => c.value);
  if (!uids.length) return toast('请先勾选要导入的妹妹', true);
  try {
    const r = await api('/api/trainees/import', { method: 'POST', body: { uids } });
    toast(`导入 ${r.imported} 人${r.skipped.length ? `，跳过 ${r.skipped.length} 人` : ''}`);
    $('#import-modal').classList.add('hidden');
    loadTrainees();
  } catch (e) {
    toast(e.message, true);
  }
});

// ────────────── 启动（默认首页 = 培训师管理） ──────────────
initUidQuery();
loadTrainers();
loadTrainees();
