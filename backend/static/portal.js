/* 培训师用户端 */
const $ = (s) => document.querySelector(s);

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = isError ? 'error' : '';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

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

// ────────────── 登录 ──────────────
// 顶栏「三条横线」→ 系统说明抽屉
const drawer = $('#menu-drawer');
function openDrawer() {
  drawer.classList.remove('hidden');
  requestAnimationFrame(() => drawer.classList.add('open'));
}
function closeDrawer() {
  drawer.classList.remove('open');
  setTimeout(() => drawer.classList.add('hidden'), 250);
}
$('#menu-btn').addEventListener('click', openDrawer);
$('#menu-close').addEventListener('click', closeDrawer);
$('#menu-mask').addEventListener('click', closeDrawer);

// 带教经验分享滚动栏：渲染两份实现首尾无缝循环，点击卡片看全文
function shareMeta(s) {
  return [s.author, s.hall, s.uid ? `UID ${s.uid}` : ''].filter(Boolean).join(' · ');
}
function openShare(s) {
  $('#share-title').textContent = s.title;
  $('#share-author').textContent = shareMeta(s);
  $('#share-body').textContent = s.body;
  $('#share-modal').classList.remove('hidden');
}
$('#share-close').addEventListener('click', () => $('#share-modal').classList.add('hidden'));
$('#share-modal').addEventListener('click', (e) => {
  if (e.target.id === 'share-modal') $('#share-modal').classList.add('hidden');
});
(function renderShares() {
  const track = $('#share-track');
  if (!track || typeof PORTAL_SHARES === 'undefined' || !PORTAL_SHARES.length) return;
  for (let round = 0; round < 2; round++) {
    for (const s of PORTAL_SHARES) {
      const card = document.createElement('div');
      card.className = 'share-card';
      card.innerHTML = `<div class="sc-title">${esc(s.title)}</div>`
        + `<div class="sc-meta">小队长 · ${esc(s.author)}</div>`
        + `<div class="sc-brief">${esc(s.brief)}</div>`
        + `<div class="sc-more">查看全文 →</div>`;
      card.addEventListener('click', () => openShare(s));
      track.appendChild(card);
    }
  }
})();

async function doLogin() {
  const uid = $('#p-uid').value.trim();
  const password = $('#p-password').value;
  if (!uid) return toast('请输入 UID', true);
  if (!password) return toast('请输入密码', true);
  try {
    await api('/api/portal/login', { method: 'POST', body: { uid, password } });
    $('#portal-login').classList.add('hidden');
    document.body.classList.add('logged-in');
    $('#portal-main').classList.remove('hidden');
    loadMe();
    loadGranted();
  } catch (e) {
    toast(e.message, true);
  }
}
$('#p-login').addEventListener('click', doLogin);
$('#p-password').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });

// ────────────── 我的数据 ──────────────
async function loadMe() {
  try {
    const r = await api('/api/portal/me');
    $('#p-welcome').textContent = `${r.trainer.nickname}（${r.trainer.uid}）`;
    $('#preview-banner').classList.toggle('hidden', !r.preview);
    renderSlots(r.slots);
  } catch (e) {
    if (e.status === 401) {
      $('#portal-main').classList.add('hidden');
      $('#portal-login').classList.remove('hidden');
      document.body.classList.remove('logged-in');
    } else {
      toast(e.message, true);
    }
  }
}

function levelBadge(level) {
  const cls = level.includes('王牌') || level.includes('大神') ? 'lv-ace'
    : level.includes('初级') ? 'lv-junior'
    : level.includes('金') ? 'lv-gold'
    : level.includes('银') ? 'lv-silver'
    : level.includes('铜') ? 'lv-bronze' : 'lv-none';
  return `<span class="lv-badge ${cls}">${esc(level || '未评级')}</span>`;
}

function renderSlots(s) {
  $('#p-slots-summary').innerHTML = `
    <span class="slot-chip">基础 <b>${s.base_slots}</b></span> +
    <span class="slot-chip">额外 <b>${s.extra_slots}</b></span> =
    <span class="slot-chip total">总名额 <b>${s.total_slots}</b>（上限 ${s.slot_cap}）</span>
    <span class="slot-chip ${s.over ? 'warn' : ''}">已绑定 <b>${s.used_slots}</b> / ${s.total_slots}</span>
    <span class="slot-chip">扩充截至 <b>${esc(s.extra_valid_until)}</b></span>`;
  $('#p-trainees').innerHTML = s.trainees.length ? s.trainees.map((t) => `
    <div class="p-trainee-card">
      <div class="p-trainee-head">
        <div>
          <b>${esc(t.nickname)}</b>
          <span class="muted" style="margin-left:8px">${esc(t.uid)}</span>
        </div>
        <div class="p-trainee-actions">
          <button class="btn small" onclick="toggleTraineeData('${esc(t.uid)}', '${esc(t.nickname)}', ${t.binding_id}, this, '${esc(t.bound_at)}', '${esc(t.last_queried_at || '')}', '${esc(t.window_status)}', ${t.weeks_left})" title="展开数据">▸</button>
        </div>
      </div>
      <div class="p-trainee-meta">
        当月最高等级 ${levelBadge(t.best_level)}
        ｜ 贡献 ${t.slot_plus > 0 ? `<span class="tag plus">+${t.slot_plus}</span>` : '+0'}
      </div>
      <div class="p-trainee-meta">
        剩余奖励 ${t.window_status === 'in_window'
          ? `<span class="tag plus">剩 ${t.weeks_left}/4 周</span>`
          : t.window_status === 'not_started' ? '<span class="tag graduated">未开始</span>'
          : '<span class="tag inactive">已结束</span>'}
      </div>
      <div id="td-${esc(t.uid)}" class="trainee-data hidden"></div>
    </div>`).join('') : '<div class="empty">还没有绑定妹妹，去下方绑定吧</div>';
  // 学员超过 1 人时默认折叠成抽屉
  const n = s.trainees.length;
  const box = $('#p-trainees');
  const toggle = $('#p-trainees-toggle');
  if (n > 1) {
    box.classList.add('hidden');
    toggle.classList.remove('hidden');
    toggle.innerHTML = `学员列表（${n} 人） <span id="p-trainees-arrow">▸</span>`;
  } else {
    box.classList.remove('hidden');
    toggle.classList.add('hidden');
  }
}

$('#p-trainees-toggle').addEventListener('click', () => {
  const box = $('#p-trainees');
  const collapsed = box.classList.toggle('hidden');
  $('#p-trainees-arrow').textContent = collapsed ? '▸' : '▾';
});

// ────────────── 自助绑定 ──────────────
let lookedUp = null;

$('#p-lookup').addEventListener('click', async () => {
  const uid = $('#p-bind-uid').value.trim();
  if (!uid) return toast('请输入妹妹 UID', true);
  lookedUp = null;
  $('#p-bind-info').innerHTML = '';
  const btn = $('#p-lookup');
  btn.disabled = true;
  try {
    const r = await api(`/api/uid-lookup?uid=${encodeURIComponent(uid)}`);
    if (!r.found) return toast(r.msg || '未找到该 UID', true);
    lookedUp = { uid, nickname: r.info.nickname, hall: r.info.hall_name, protection_end: r.info.protection_end || '' };
    const pe = lookedUp.protection_end;
    $('#p-bind-info').innerHTML =
      `<b>${esc(r.info.nickname)}</b>（${esc(uid)}）` +
      `${r.info.hall_name ? ` ｜ ${esc(r.info.hall_name)}` : ''}` +
      `${r.info.week_level ? ` ｜ ${esc(r.info.week_level)}` : ''}` +
      `${pe ? ` ｜ 保护期至 ${esc(pe)}` : ' ｜ 无保护期记录'}`;
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

$('#p-bind').addEventListener('click', async () => {
  if (!lookedUp) return toast('请先查询妹妹 UID', true);
  try {
    const r = await api('/api/portal/bind', {
      method: 'POST',
      body: {
        trainee_uid: lookedUp.uid,
        trainee_nickname: lookedUp.nickname,
        trainee_hall: lookedUp.hall,
      },
    });
    toast(r.rebound ? '绑定成功（已替换原绑定）' : '绑定成功');
    lookedUp = null;
    $('#p-bind-uid').value = '';
    $('#p-bind-info').innerHTML = '';
    loadMe();
  } catch (e) {
    toast(e.message, true);
  }
});

$('#p-logout').addEventListener('click', async (e) => {
  e.preventDefault();
  await api('/api/portal/logout', { method: 'POST' });
  location.reload();
});
// 管理员预览模式：退出预览 = 退出当前身份，回到登录页
$('#preview-exit').addEventListener('click', async () => {
  await api('/api/portal/logout', { method: 'POST' });
  location.reload();
});

// 修改密码
$('#p-change-pwd').addEventListener('click', () => {
  $('#pwd-old').value = '';
  $('#pwd-new').value = '';
  $('#pwd-modal').classList.remove('hidden');
});
$('#pwd-cancel').addEventListener('click', () => $('#pwd-modal').classList.add('hidden'));
$('#pwd-save').addEventListener('click', async () => {
  const old = $('#pwd-old').value, newPwd = $('#pwd-new').value;
  try {
    await api('/api/portal/change-password', {
      method: 'POST', body: { old_password: old, new_password: newPwd },
    });
    toast('密码已修改');
    $('#pwd-modal').classList.add('hidden');
  } catch (e) {
    toast(e.message, true);
  }
});

// 刷新自己学员数据
$('#p-refresh').addEventListener('click', async () => {
  const btn = $('#p-refresh');
  btn.disabled = true;
  btn.textContent = '刷新中…';
  try {
    const r = await api('/api/portal/refresh', { method: 'POST' });
    toast(`已刷新 ${r.queried.length} 人${r.errors.length ? `，${r.errors.length} 人失败` : ''}`);
    loadMe();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '刷新数据';
  }
});

const PORTAL_COMPARE_LABELS = {
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

// 名额说明抽屉
$('#p-slots-help-toggle').addEventListener('click', () => {
  const box = $('#p-slots-help');
  const open = box.classList.toggle('hidden');
  $('#p-help-arrow').textContent = open ? '▸' : '▾';
});

// 妹妹数据：卡片内箭头展开，解散按钮在展开区底部
async function toggleTraineeData(uid, nickname, bindingId, btn, boundAt, lastQuery, windowStatus, weeksLeft) {
  const box = document.getElementById(`td-${uid}`);
  if (!box.classList.contains('hidden')) {
    box.classList.add('hidden');
    btn.textContent = '▸';
    return;
  }
  box.classList.remove('hidden');
  btn.textContent = '▾';
  if (box.dataset.loaded) return;
  box.dataset.loaded = '1';
  box.innerHTML = '<div class="muted">查询中…</div>';
  try {
    const r = await api(`/api/portal/trainee-data?uid=${encodeURIComponent(uid)}`);
    const res = r.result;
    const cards = Object.entries(PORTAL_COMPARE_LABELS).map(([key, label]) => {
      const c = res.compare[key];
      if (!c) return '';
      return `<div class="uq-item">
        <div class="k">${label}</div>
        <div class="v">本周 ${esc(c.this)} ｜ 上周 ${esc(c.last)}</div>
        <div class="c ${c.trend || 'flat'}">${esc(c.change || '')}</div>
      </div>`;
    }).join('');
    box.innerHTML = `
      <div class="muted" style="margin:8px 0">
        绑定 ${esc(boundAt)} ｜ 最后查询 ${esc(lastQuery || '本月未查询')}<br>
        剩余奖励 <b>${windowStatus === 'in_window' ? `剩 ${weeksLeft}/4 周` : windowStatus === 'not_started' ? '未开始' : '已结束'}</b><br>
        本周 ${esc(res.this_week.period)} ｜ 上周 ${esc(res.last_week.period)}
      </div>
      <div class="uq-grid">${cards}</div>
      <div style="margin-top:10px;text-align:right">
        <button class="btn small danger" onclick="unbindTrainee(${bindingId}, '${esc(nickname)}')">解散</button>
      </div>`;
  } catch (e) {
    box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

// 用户自行解散（名额贡献随绑定结束自动减除）
async function unbindTrainee(bindingId, nickname) {
  if (!confirm(`确认解散与「${nickname}」的绑定？\n其名额扩充贡献会同时减除。`)) return;
  try {
    await api('/api/portal/unbind', { method: 'POST', body: { binding_id: bindingId } });
    toast(`已解散与「${nickname}」的绑定，其名额贡献已减除`);
    loadMe();
  } catch (e) {
    toast(e.message, true);
  }
}

// 已发放奖励（按妹妹分组，卡片式上下排布；超过 1 组时首组直出，其余折叠）
async function loadGranted() {
  try {
    const r = await api('/api/portal/granted-rewards');
    const groups = new Map();
    r.items.forEach((g) => {
      if (!groups.has(g.trainee_uid)) groups.set(g.trainee_uid, []);
      groups.get(g.trainee_uid).push(g);
    });
    const cardList = [...groups.values()].map((items) => {
      const g0 = items[0];
      return `<div class="p-trainee-card">
        <div class="p-trainee-head">
          <div>
            <b>${esc(g0.trainee_nickname)}</b>
            <span class="muted" style="margin-left:8px">${esc(g0.trainee_uid)}</span>
          </div>
          <span class="muted">${esc(g0.hall_name || '-')}</span>
        </div>
        <div class="granted-rows">
          ${items.map((g) => `
            <div class="granted-row">
              <span>${esc(g.reward_label)}</span>
              <b>${g.amount} × 2</b>
              <span class="muted">${esc(g.granted_at || '-')}</span>
            </div>`).join('')}
        </div>
      </div>`;
    });
    const n = cardList.length;
    $('#p-granted-first').innerHTML = n ? cardList[0] : '<div class="empty">还没有已发放的奖励</div>';
    $('#p-granted').innerHTML = cardList.slice(1).join('');
    const toggle = $('#p-granted-toggle');
    if (n > 1) {
      toggle.classList.remove('hidden');
      toggle.innerHTML = `展开全部（共 ${n} 组） <span id="p-granted-arrow">▸</span>`;
      $('#p-granted').classList.add('hidden');
    } else {
      toggle.classList.add('hidden');
      $('#p-granted').classList.remove('hidden');
    }
  } catch (e) {
    toast(e.message, true);
  }
}
$('#p-granted-toggle').addEventListener('click', () => {
  const box = $('#p-granted');
  const collapsed = box.classList.toggle('hidden');
  $('#p-granted-arrow').textContent = collapsed ? '▸' : '▾';
});
$('#p-granted-refresh').addEventListener('click', loadGranted);

// 一键回到顶部
$('#back-top').addEventListener('click', () => {
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

// 已登录则直接进主界面
(async function init() {
  try {
    const r = await api('/api/portal/me');
    $('#portal-login').classList.add('hidden');
    document.body.classList.add('logged-in');
    $('#portal-main').classList.remove('hidden');
    $('#p-welcome').textContent = `${r.trainer.nickname}（${r.trainer.uid}）`;
    $('#preview-banner').classList.toggle('hidden', !r.preview);
    renderSlots(r.slots);
    loadGranted();
  } catch (e) {
    // 未登录则停留在登录页
  }
})();
