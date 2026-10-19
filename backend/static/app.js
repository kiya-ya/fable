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
function toast(msg, isError = false, action = null) {
  const el = $('#toast');
  el.innerHTML = esc(msg) + (action
    ? ` <a href="javascript:void(0)" id="toast-action" style="color:#fff;text-decoration:underline;font-weight:600;margin-left:6px">${esc(action.label)}</a>`
    : '');
  el.className = isError ? 'error' : '';
  if (action) {
    $('#toast-action').addEventListener('click', () => {
      el.classList.add('hidden');
      action.fn();
    });
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), action ? 8000 : 3000);
}

const TRAINER_STATUS = { active: '活跃', inactive: '退出' };
const TRAINEE_STATUS = { active: '活跃', inactive: '退出' };
const BIND_TYPE = { trainer: '培训师', sister: '姐妹团' };

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// 分页控件：pagerEl 内渲染，onGo(page) 回调
function renderPager(pagerSel, page, pageSize, total, onGo) {
  const el = $(pagerSel);
  const pages = Math.max(Math.ceil(total / pageSize), 1);
  el.innerHTML = `
    <button class="btn small" ${page <= 1 ? 'disabled' : ''} data-go="${page - 1}">上一页</button>
    <span class="muted">${page} / ${pages} 页 · 共 ${total} 条</span>
    <button class="btn small" ${page >= pages ? 'disabled' : ''} data-go="${page + 1}">下一页</button>`;
  el.querySelectorAll('button[data-go]').forEach((b) =>
    b.addEventListener('click', () => onGo(+b.dataset.go)));
}

// ────────────── Tab 切换 ──────────────
$$('#tabs .tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('#tabs .tab').forEach((b) => b.classList.toggle('active', b === btn));
    $$('.panel').forEach((p) => p.classList.remove('active'));
    $(`#tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'bindings') loadBindingsTab();
    if (btn.dataset.tab === 'dashboard') loadDashboard();
  });
});

// ────────────── UID 速查 ──────────────
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
  try {
    const r = await api('/api/uid-query', { method: 'POST', body: { uid, captain_type } });
    // 面板严格按本次响应显隐，避免上一个 UID 的数据残留
    $('#slots-panel').classList.toggle('hidden', !r.slots);
    $('#rewards-panel').classList.toggle('hidden', !r.rewards_panel);
    if (r.slots) renderSlotsPanel(r.slots);
    if (r.rewards_panel) renderRewardsPanel(r.rewards_panel);
    renderUidResult(r.result);
    if (r.retention) {
      const banner = r.retention.retained
        ? `<div class="retention-banner ok">✓ ${esc(r.retention.msg)}</div>`
        : `<div class="retention-banner bad">✗ ${esc(r.retention.msg)}</div>`;
      $('#uq-result').insertAdjacentHTML('afterbegin', banner);
    }
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
  achieved: { text: '已达标', cls: 'inactive' },
  ineligible: { text: '未达标', cls: 'inactive' },
};

function renderRewardsPanel(p) {
  const retainedTag = p.retained === 0
    ? ' <span class="tag over">疑似解散</span>'
    : p.retained === 1 ? ' <span class="tag active">留存</span>' : '';
  $('#rewards-window').innerHTML =
    `（${esc(p.trainee.nickname)} · 奖励窗口 ${p.window_weeks} 周）${retainedTag}`;
  const box = $('#rewards-blocks');
  if (!p.panels.length) {
    box.innerHTML = '<div class="empty">当前无生效绑定（培训师或姐妹团三胎均可产生奖励）</div>';
  } else {
    box.innerHTML = p.panels.map(renderRewardBlock).join('');
  }
  $('#rewards-panel').classList.remove('hidden');
}

function renderRewardBlock(pb) {
  const statusText = {
    not_started: `<span class="tag graduated">未开始（${esc(pb.window_start)} 起）</span>`,
    in_window: `剩余 <b>${pb.days_left}</b> 天`,
    expired: '<span class="tag over">已过奖励有效期</span>',
  }[pb.window_status];
  const sideTag = pb.side_retained === 0
    ? ` <span class="tag over">${esc(pb.side_label)}未留存·暂停发奖</span>` : '';
  const pendingCount = pb.rewards.filter((r) => r.status === 'pending').length;
  const grantAllBtn = pendingCount > 0
    ? `<button class="btn small primary" onclick="grantAllRewards(${pb.binding.id})">全部标记已发（${pendingCount} 档）</button>`
    : '';
  const rows = pb.rewards.map((r) => {
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
  return `<div class="reward-block">
    <div class="reward-block-head">
      <span class="tag ${pb.bind_type === 'sister' ? 'graduated' : 'active'}">${esc(pb.type_label)}</span>
      ${esc(pb.side_label)} <b>${esc(pb.binding.side_nickname)}</b>（${esc(pb.binding.side_uid)}）
      ｜ 绑定 ${esc(pb.binding.bound_at)} ｜ 窗口 ${esc(pb.window_start)} ~ ${esc(pb.window_end)} ｜ ${statusText}${sideTag}
      <span style="float:right">${grantAllBtn}</span>
    </div>
    <table>
      <thead><tr><th>奖励档位</th><th>金额（×2 双人份）</th><th>状态</th><th>发放时间</th><th>操作</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function grantAllRewards(bindingId) {
  if (!confirm('确认将该绑定的全部待发放奖励标记为已发？')) return;
  try {
    const r = await api('/api/rewards/grant-all', { method: 'POST', body: { binding_id: bindingId } });
    toast(`已标记 ${r.granted} 档为已发放`);
    refreshRewardsPanel();
  } catch (e) {
    toast(e.message, true);
  }
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

// ────────────── 新建绑定（输 UID 自动查询建档） ──────────────
const bindState = { trainer: null, trainee: null };
let bindType = 'trainer';

$$('#bind-type-seg .seg-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('#bind-type-seg .seg-btn').forEach((b) => b.classList.toggle('active', b === btn));
    bindType = btn.dataset.btype;
    $('#bind-left-label').textContent = bindType === 'sister' ? '姐姐 UID' : '培训师 UID';
    bindState.trainer = null;
    $('#bind-trainer-uid').value = '';
    $('#bind-trainer-info').innerHTML = '';
  });
});

async function lookupBindSide(kind) {
  const uid = $(`#bind-${kind}-uid`).value.trim();
  const info = $(`#bind-${kind}-info`);
  if (!uid) return toast('请输入 UID', true);
  const btn = $(`#bind-${kind}-lookup`);
  btn.disabled = true;
  btn.textContent = '查询中…';
  bindState[kind] = null;
  try {
    const r = await api(`/api/uid-lookup?uid=${encodeURIComponent(uid)}`);
    if (!r.found) {
      info.innerHTML = '<span class="tag over">未找到该 UID</span>';
      return toast(r.msg || '未找到该 UID', true);
    }
    // 查本地是否已建档（培训师侧 role=all 覆盖姐姐记录）
    const list = await api(`/api/${kind}s?kw=${encodeURIComponent(uid)}${kind === 'trainer' ? '&role=all' : ''}`);
    const existing = list.items.find((x) => x.uid === uid);
    bindState[kind] = { uid, nickname: r.info.nickname, hall: r.info.hall_name, protection_end: r.info.protection_end || '', existing: !!existing };
    let protTag = '';
    if (kind === 'trainee') {
      const pe = (r.info.protection_end || '').trim();
      if (pe) {
        const m = pe.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
        const inProt = m ? new Date(+m[1], +m[2] - 1, +m[3]) >= new Date(new Date().toDateString()) : false;
        protTag = inProt
          ? ` ｜ <span class="tag active">保护期内（至 ${m[0]}）</span>`
          : ` ｜ <span class="tag over">保护期已于 ${m[0]} 结束</span>`;
      } else {
        protTag = ' ｜ <span class="tag over">无保护期记录</span>';
      }
    }
    info.innerHTML =
      `<b>${esc(r.info.nickname)}</b>（${esc(uid)}）` +
      `${r.info.hall_name ? ` ｜ ${esc(r.info.hall_name)}` : ''}` +
      `${r.info.week_level ? ` ｜ ${esc(r.info.week_level)}` : ''}` +
      protTag + ' ｜ ' +
      (existing
        ? '<span class="tag active">已建档</span>'
        : '<span class="tag graduated">绑定时自动建档</span>');
  } catch (e) {
    info.innerHTML = '';
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '查询';
  }
}

$('#bind-trainer-lookup').addEventListener('click', () => lookupBindSide('trainer'));
$('#bind-trainee-lookup').addEventListener('click', () => lookupBindSide('trainee'));
$('#bind-trainer-uid').addEventListener('input', () => { bindState.trainer = null; $('#bind-trainer-info').innerHTML = ''; });
$('#bind-trainee-uid').addEventListener('input', () => { bindState.trainee = null; $('#bind-trainee-info').innerHTML = ''; });
$('#bind-trainer-uid').addEventListener('keydown', (e) => { if (e.key === 'Enter') lookupBindSide('trainer'); });
$('#bind-trainee-uid').addEventListener('keydown', (e) => { if (e.key === 'Enter') lookupBindSide('trainee'); });

$('#bind-submit').addEventListener('click', async () => {
  if (!bindState.trainer) return toast(`请先查询${bindType === 'sister' ? '姐姐' : '培训师'} UID`, true);
  if (!bindState.trainee) return toast('请先查询妹妹 UID', true);
  // 培训师绑定：客户端先拦不在保护期的（服务端仍会再校验一次）
  if (bindType === 'trainer') {
    const pe = (bindState.trainee.protection_end || '').trim();
    const m = pe.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
    const inProt = m ? new Date(+m[1], +m[2] - 1, +m[3]) >= new Date(new Date().toDateString()) : false;
    if (!inProt) return toast('该妹妹不在保护期内，不能绑定培训师', true);
  }
  await doBind({
    bind_type: bindType,
    trainer_uid: bindState.trainer.uid,
    trainer_nickname: bindState.trainer.nickname,
    trainer_hall: bindState.trainer.hall,
    trainee_uid: bindState.trainee.uid,
    trainee_nickname: bindState.trainee.nickname,
    trainee_hall: bindState.trainee.hall,
    note: $('#bind-note').value,
  });
});

async function doBind(payload) {
  try {
    const r = await api('/api/bindings/by-uid', { method: 'POST', body: payload });
    const created = [r.trainer_created && '左侧', r.trainee_created && '妹妹'].filter(Boolean);
    toast(`${r.rebound ? '换绑' : '绑定'}成功（${BIND_TYPE[r.bind_type]}）${created.length ? `，自动建档：${created.join('、')}` : ''}${r.gate_warn ? `；注意：${r.gate_msg}` : ''}`, !!r.gate_warn, {
      label: '撤销',
      fn: async () => {
        try {
          await api(`/api/bindings/${r.id}/unbind`, { method: 'POST' });
          toast('已撤销刚才的绑定');
          loadBindingsTab();
        } catch (e) {
          toast(e.message, true);
        }
      },
    });
    bindState.trainer = bindState.trainee = null;
    $('#bind-trainer-uid').value = '';
    $('#bind-trainee-uid').value = '';
    $('#bind-trainer-info').innerHTML = '';
    $('#bind-trainee-info').innerHTML = '';
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

// ────────────── 绑定列表（底部分页） ──────────────
let bindingsActiveView = true;
let bindingsTypeFilter = '';
let bindingsPage = 1;

async function loadBindings(page) {
  if (page) bindingsPage = page;
  const params = new URLSearchParams({
    active: bindingsActiveView ? 1 : 0,
    page: bindingsPage,
  });
  if (bindingsTypeFilter) params.set('bind_type', bindingsTypeFilter);
  const data = await api(`/api/bindings?${params}`);
  const tbody = $('#bindings-table tbody');
  $$('.col-unbound').forEach((el) => (el.style.display = bindingsActiveView ? 'none' : ''));
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="14" class="empty">暂无${bindingsActiveView ? '生效绑定' : '历史记录'}</td></tr>`;
  } else {
    tbody.innerHTML = data.items.map((b) => {
      const weeksTag = b.window_status === 'in_window'
        ? `<span class="tag plus">剩 ${b.weeks_left}/4 周</span>`
        : b.window_status === 'not_started'
          ? `<span class="tag graduated">未开始</span>`
          : '<span class="tag inactive">已结束</span>';
      const retainedTag = b.retained === null || b.retained === undefined
        ? '<span class="muted">未查询</span>'
        : b.retained
          ? '<span class="tag active">留存</span>'
          : '<span class="tag over">疑似解散</span>';
      const prot = (b.protection_end || '').trim();
      let protHtml = '<span class="muted">未查询</span>';
      if (prot && prot !== '-') {
        const pm = prot.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
        if (pm) {
          const inProt = new Date(+pm[1], +pm[2] - 1, +pm[3]) >= new Date(new Date().toDateString());
          protHtml = inProt ? `<span class="tag active">${pm[0]}</span>` : `<span class="tag inactive">${pm[0]} 已出保</span>`;
        } else {
          protHtml = esc(prot);
        }
      }
      return `
      <tr>
        <td><span class="tag ${b.bind_type === 'sister' ? 'graduated' : 'active'}">${BIND_TYPE[b.bind_type] || b.bind_type}</span></td>
        <td>${esc(b.trainer_nickname)}</td>
        <td><a href="javascript:void(0)" class="uid-link" onclick="gotoUidQuery('${esc(b.trainer_uid)}')">${esc(b.trainer_uid)}</a></td>
        <td>${esc(b.trainee_nickname)}</td>
        <td><a href="javascript:void(0)" class="uid-link" onclick="gotoUidQuery('${esc(b.trainee_uid)}')">${esc(b.trainee_uid)}</a></td>
        <td>${esc(b.hall_name || '')}</td>
        <td>${protHtml}</td>
        <td>${retainedTag}</td>
        <td>${esc(b.bound_at)}</td>
        <td>${esc(b.window_end)}</td>
        <td>${weeksTag}</td>
        <td class="col-unbound" style="display:${bindingsActiveView ? 'none' : ''}">${esc(b.unbound_at || '')}</td>
        <td>${esc(b.note || '')}</td>
        <td style="white-space:nowrap">
          ${bindingsActiveView
            ? `<button class="btn small danger" onclick="unbind(${b.id})">解绑</button>`
            : `<button class="btn small primary" onclick="restoreBinding(${b.id})">恢复</button>`}
          <button class="btn small" onclick="gotoUidQuery('${esc(b.trainee_uid)}')">速查</button>
        </td>
      </tr>`;
    }).join('');
  }
  renderPager('#bindings-pager', data.page, data.page_size, data.total, (p) => loadBindings(p));
}

$('#seg-active').addEventListener('click', () => {
  bindingsActiveView = true;
  bindingsPage = 1;
  $('#seg-active').classList.add('active');
  $('#seg-history').classList.remove('active');
  loadBindings();
});
$('#seg-history').addEventListener('click', () => {
  bindingsActiveView = false;
  bindingsPage = 1;
  $('#seg-history').classList.add('active');
  $('#seg-active').classList.remove('active');
  loadBindings();
});
$$('#bindings-type-seg .seg-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('#bindings-type-seg .seg-btn').forEach((b) => b.classList.toggle('active', b === btn));
    bindingsTypeFilter = btn.dataset.filter;
    bindingsPage = 1;
    loadBindings();
  });
});

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

// 历史记录恢复绑定
async function restoreBinding(id) {
  try {
    await api(`/api/bindings/${id}/restore`, { method: 'POST' });
    toast('已恢复为生效绑定');
    loadBindingsTab();
  } catch (e) {
    toast(e.message, true);
  }
}

// 行内刷新：实时更新该妹妹的档案大厅/昵称/等级/留存
async function refreshTraineeRow(traineeId, btn) {
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const r = await api(`/api/trainees/${traineeId}/refresh`, { method: 'POST' });
    if (r.dissolved) {
      toast('该妹妹留存字段为空，已自动解散绑定', true);
    } else {
      const info = r.info;
      toast(`已刷新：${info.hall_name || '大厅为空'}${info.week_level ? ` / ${info.week_level}` : ''}${r.retained === false ? ' / 疑似解散（首次为空不自动解散）' : ''}`);
    }
    loadBindingsTab();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '刷新';
  }
}

$('#bindings-refresh').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  btn.textContent = '刷新中…';
  try {
    const r = await api('/api/admin/refresh-all-trainees', { method: 'POST' });
    toast(`已刷新 ${r.queried} 人${r.errors.length ? `，${r.errors.length} 人失败` : ''}`);
    loadBindingsTab();
  } catch (e2) {
    toast(e2.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '刷新全部数据';
  }
});

function gotoUidQuery(uid) {
  $('[data-tab="uidquery"]').click();
  $('#uq-uid').value = uid;
  $('#uq-submit').click();
}

// ────────────── 档案管理（折叠卡片 + 分页） ──────────────
const PERSON_CONF = {
  trainers: { url: '/api/trainers', kw: '#trainer-kw', table: '#trainers-table', statuses: TRAINER_STATUS },
  trainees: { url: '/api/trainees', kw: '#trainee-kw', table: '#trainees-table', statuses: TRAINEE_STATUS },
};
const listState = { trainers: { page: 1 }, trainees: { page: 1 } };

async function refreshTotals() {
  try {
    const [t, s] = await Promise.all([
      api('/api/trainers?page_size=1'), api('/api/trainees?page_size=1'),
    ]);
    $('#trainers-total').textContent = `（共 ${t.total} 人）`;
    $('#trainees-total').textContent = `（共 ${s.total} 人）`;
    $('#trainers-modal-total').textContent = `（共 ${t.total} 人）`;
    $('#trainees-modal-total').textContent = `（共 ${s.total} 人）`;
  } catch (e) { /* 计数失败不影响使用 */ }
}

// 档案弹窗开关（悬浮于一级界面之上）
$('#entry-trainers').addEventListener('click', () => {
  $('#trainers-modal').classList.remove('hidden');
  loadTrainers(1);
});
$('#entry-trainees').addEventListener('click', () => {
  $('#trainees-modal').classList.remove('hidden');
  loadTrainees(1);
});
$$('[data-close]').forEach((btn) =>
  btn.addEventListener('click', () => $(`#${btn.dataset.close}`).classList.add('hidden')));

async function loadTrainers(page) {
  if (page) listState.trainers.page = page;
  const conf = PERSON_CONF.trainers;
  const kw = $(conf.kw).value.trim();
  const params = new URLSearchParams({ page: listState.trainers.page });
  if (kw) params.set('kw', kw);
  const data = await api(`${conf.url}?${params}`);
  const tbody = $(`${conf.table} tbody`);
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无数据</td></tr>';
  } else {
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
  renderPager('#trainers-pager', data.page, data.page_size, data.total, (p) => loadTrainers(p));
}

async function loadTrainees(page) {
  if (page) listState.trainees.page = page;
  const conf = PERSON_CONF.trainees;
  const kw = $(conf.kw).value.trim();
  const status = $('#trainee-status-filter').value;
  const params = new URLSearchParams({ page: listState.trainees.page });
  if (kw) params.set('kw', kw);
  if (status) params.set('status', status);
  const data = await api(`${conf.url}?${params}`);
  const tbody = $(`${conf.table} tbody`);
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无数据</td></tr>';
  } else {
    tbody.innerHTML = data.items.map((t) => `
      <tr>
        <td>${esc(t.uid)}</td>
        <td>${esc(t.nickname)}</td>
        <td>${esc(t.hall_name || '')}</td>
        <td><span class="tag ${t.status}">${conf.statuses[t.status] || t.status}</span></td>
        <td>${t.trainer_nickname ? `${esc(t.trainer_nickname)}（${esc(t.trainer_uid)}）` : '<span class="muted">—</span>'}</td>
        <td>${t.sister_nickname ? `${esc(t.sister_nickname)}（${esc(t.sister_uid)}）` : '<span class="muted">—</span>'}</td>
        <td>${esc(t.note || '')}</td>
        <td>
          <button class="btn small" onclick="gotoUidQuery('${esc(t.uid)}')">速查</button>
          <button class="btn small" onclick='openPersonModal("trainees", ${JSON.stringify(t)})'>编辑</button>
          <button class="btn small danger" onclick="delPerson('trainees', ${t.id})">删除</button>
        </td>
      </tr>`).join('');
  }
  renderPager('#trainees-pager', data.page, data.page_size, data.total, (p) => loadTrainees(p));
}

async function loadBindingsTab() {
  await Promise.all([loadBindings(1), refreshTotals()]);
  // 已打开的档案弹窗同步刷新
  if (!$('#trainers-modal').classList.contains('hidden')) loadTrainers();
  if (!$('#trainees-modal').classList.contains('hidden')) loadTrainees();
}

let searchTimer = null;
$('#trainer-kw').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadTrainers(1), 300);
});
$('#trainee-kw').addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadTrainees(1), 300);
});
$('#trainee-status-filter').addEventListener('change', () => loadTrainees(1));

async function delPerson(kind, id) {
  if (!confirm('确认删除？历史绑定记录会保留。')) return;
  try {
    await api(`${PERSON_CONF[kind].url}/${id}`, { method: 'DELETE' });
    toast('已删除');
    kind === 'trainers' ? loadTrainers() : loadTrainees();
    refreshTotals();
  } catch (e) {
    toast(e.message, true);
  }
}

// 从绑定列表直接编辑：按 UID 取档案后打开弹窗
async function editPersonByUid(kind, uid) {
  try {
    const url = kind === 'trainers'
      ? `/api/trainers?role=all&kw=${encodeURIComponent(uid)}`
      : `/api/trainees?kw=${encodeURIComponent(uid)}`;
    const r = await api(url);
    const p = r.items.find((x) => x.uid === uid);
    if (!p) return toast('档案不存在', true);
    openPersonModal(kind, p);
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
    loadBindings();   // 昵称/大厅可能变了，绑定列表同步
    refreshTotals();
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
    refreshTotals();
  } catch (e) {
    toast(e.message, true);
  }
});

// ────────────── 周奖励导出 ──────────────
$('#exp-date').value = new Date().toLocaleDateString('sv-SE');  // 本地 YYYY-MM-DD

async function exportRewards(bindType, btn) {
  const date = $('#exp-date').value;
  if (!date) return toast('请选择开始时间', true);
  btn.disabled = true;
  const oldText = btn.textContent;
  btn.textContent = '生成中…';
  $('#exp-status').textContent = '正在逐人实时查询（每人约 2 次请求），请稍候…';
  try {
    const resp = await fetch('/api/export/rewards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bind_type: bindType, date }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.msg || `导出失败 (${resp.status})`);
    }
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const filename = m ? decodeURIComponent(m[1]) : `${date.replaceAll('-', '')}奖励.xlsx`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
    const warn = resp.headers.get('X-Export-Errors');
    $('#exp-status').textContent = warn ? `已生成，但部分学员查询失败：${warn}` : `已生成：${filename}`;
    toast('导出成功');
  } catch (e) {
    $('#exp-status').textContent = '';
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

$('#exp-trainer').addEventListener('click', (e) => exportRewards('trainer', e.target));
$('#exp-sister').addEventListener('click', (e) => exportRewards('sister', e.target));

// ────────────── 数据看板 ──────────────
const PIE_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#6b7280'];

async function loadDashboard() {
  try {
    const d = await api('/api/dashboard/summary');
    renderDashCards(d);
    renderLineChart(d.weekly);
    renderPieChart(d.dissolve_reasons);
  } catch (e) {
    toast(e.message, true);
  }
}

function renderDashCards(d) {
  const cards = [
    { label: `本周新绑定（${d.this_week.label}）`, value: d.this_week.bound, color: '#3b82f6' },
    { label: '本周解散', value: d.this_week.unbound, color: '#ef4444' },
    { label: '当前生效绑定（培训师/姐妹团）', value: `${d.active.total}（${d.active.trainer}/${d.active.sister}）`, color: '#10b981' },
    { label: '奖励待发放 / 已发放（档）', value: `${d.rewards.pending} / ${d.rewards.granted}`, color: '#f59e0b' },
  ];
  $('#dash-cards').innerHTML = cards.map((c) => `
    <div class="dash-card" style="border-top-color:${c.color}">
      <div class="dash-card-label">${esc(c.label)}</div>
      <div class="dash-card-value" style="color:${c.color}">${esc(c.value)}</div>
    </div>`).join('');
}

function renderLineChart(weekly) {
  const W = 640, H = 240, padL = 40, padB = 28, padT = 14, padR = 10;
  const max = Math.max(1, ...weekly.map((w) => Math.max(w.bound, w.unbound)));
  const stepX = (W - padL - padR) / (weekly.length - 1);
  const y = (v) => padT + (H - padB - padT) * (1 - v / max);
  const series = (key) => weekly.map((w, i) =>
    `${(padL + i * stepX).toFixed(1)},${y(w[key]).toFixed(1)}`).join(' ');
  const dots = (key, color) => weekly.map((w, i) =>
    `<circle cx="${padL + i * stepX}" cy="${y(w[key])}" r="3.5" fill="${color}"><title>${w.label} ${w[key]}</title></circle>`).join('');
  const xlabels = weekly.map((w, i) =>
    `<text x="${padL + i * stepX}" y="${H - 8}" font-size="10" fill="#9ca3af" text-anchor="middle">${w.week_start}</text>`).join('');
  const gridlines = [0, 0.5, 1].map((f) => {
    const gy = padT + (H - padB - padT) * (1 - f);
    const gv = Math.round(max * f);
    return `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="#e5e7eb" stroke-dasharray="3"/>
            <text x="${padL - 6}" y="${gy + 3}" font-size="10" fill="#9ca3af" text-anchor="end">${gv}</text>`;
  }).join('');
  $('#dash-line').innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    ${gridlines}
    <polyline points="${series('bound')}" fill="none" stroke="#3b82f6" stroke-width="2"/>
    <polyline points="${series('unbound')}" fill="none" stroke="#ef4444" stroke-width="2"/>
    ${dots('bound', '#3b82f6')}${dots('unbound', '#ef4444')}
    ${xlabels}
  </svg>`;
}

function renderPieChart(reasons) {
  const total = reasons.reduce((s, r) => s + r.count, 0);
  if (!total) {
    $('#dash-pie').innerHTML = '<div class="empty">暂无解散记录</div>';
    $('#dash-pie-legend').innerHTML = '';
    return;
  }
  const R = 80, CX = 100, CY = 100, CIRC = 2 * Math.PI * R;
  let offset = 0;
  const arcs = reasons.map((r, i) => {
    const frac = r.count / total;
    const dash = `${(frac * CIRC).toFixed(2)} ${(CIRC - frac * CIRC).toFixed(2)}`;
    const el = `<circle cx="${CX}" cy="${CY}" r="${R}" fill="none"
      stroke="${PIE_COLORS[i % PIE_COLORS.length]}" stroke-width="36"
      stroke-dasharray="${dash}" stroke-dashoffset="${(-offset * CIRC).toFixed(2)}"
      transform="rotate(-90 ${CX} ${CY})"><title>${r.reason}: ${r.count}</title></circle>`;
    offset += frac;
    return el;
  }).join('');
  $('#dash-pie').innerHTML = `<svg viewBox="0 0 200 200" style="max-width:220px">${arcs}
    <text x="${CX}" y="${CY - 4}" text-anchor="middle" font-size="20" font-weight="600">${total}</text>
    <text x="${CX}" y="${CY + 16}" text-anchor="middle" font-size="11" fill="#6b7280">总解散</text></svg>`;
  $('#dash-pie-legend').innerHTML = reasons.map((r, i) => `
    <div class="pie-legend-item">
      <i class="dot" style="background:${PIE_COLORS[i % PIE_COLORS.length]}"></i>
      ${esc(r.reason)} <b>${r.count}</b>（${(r.count / total * 100).toFixed(1)}%）
    </div>`).join('');
}

// ────────────── 启动（默认首页 = 绑定关系） ──────────────
initUidQuery();
loadBindingsTab();
