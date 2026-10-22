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
async function refreshCaptcha() {
  try {
    const r = await api('/api/portal/captcha');
    $('#p-captcha').textContent = r.code;
    $('#p-code').value = '';
  } catch (e) {
    toast(e.message, true);
  }
}
$('#p-captcha').addEventListener('click', refreshCaptcha);

async function doLogin() {
  const uid = $('#p-uid').value.trim();
  const code = $('#p-code').value.trim();
  if (!uid || !code) return toast('请输入 UID 和验证码', true);
  try {
    await api('/api/portal/login', { method: 'POST', body: { uid, code } });
    $('#portal-login').classList.add('hidden');
    $('#portal-main').classList.remove('hidden');
    loadMe();
  } catch (e) {
    toast(e.message, true);
    refreshCaptcha();
  }
}
$('#p-login').addEventListener('click', doLogin);
$('#p-code').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });

// ────────────── 我的数据 ──────────────
async function loadMe() {
  try {
    const r = await api('/api/portal/me');
    $('#p-welcome').textContent = `${r.trainer.nickname}（${r.trainer.uid}）`;
    renderSlots(r.slots);
  } catch (e) {
    if (e.status === 401) {
      $('#portal-main').classList.add('hidden');
      $('#portal-login').classList.remove('hidden');
      refreshCaptcha();
    } else {
      toast(e.message, true);
    }
  }
}

function renderSlots(s) {
  $('#p-slots-summary').innerHTML = `
    <span class="slot-chip">基础 <b>${s.base_slots}</b></span> +
    <span class="slot-chip">额外 <b>${s.extra_slots}</b></span> =
    <span class="slot-chip total">总名额 <b>${s.total_slots}</b>（上限 ${s.slot_cap}）</span>
    <span class="slot-chip ${s.over ? 'warn' : ''}">已绑定 <b>${s.used_slots}</b> / ${s.total_slots}</span>
    <span class="slot-chip">扩充截至 <b>${esc(s.extra_valid_until)}</b></span>`;
  $('#p-trainees').innerHTML = s.trainees.length ? s.trainees.map((t) => `
    <tr>
      <td>${esc(t.nickname)}</td>
      <td>${esc(t.uid)}</td>
      <td>${esc(t.bound_at)}</td>
      <td>${esc(t.best_level)}</td>
      <td>${t.slot_plus > 0 ? `<span class="tag plus">+${t.slot_plus}</span>` : '<span class="muted">+0</span>'}</td>
      <td class="muted">${esc(t.last_queried_at || '本月未查询')}</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="showTraineeData('${esc(t.uid)}', '${esc(t.nickname)}')">数据</button>
        <button class="btn small danger" onclick="unbindTrainee(${t.binding_id}, '${esc(t.nickname)}')">解散</button>
      </td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">还没有绑定妹妹，去下方绑定吧</td></tr>';
}

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

// 查看妹妹本周/上周数据
async function showTraineeData(uid, nickname) {
  const card = $('#p-data-card');
  card.classList.remove('hidden');
  $('#p-data-title').textContent = `妹妹数据：${nickname}（${uid}）`;
  $('#p-data-body').innerHTML = '<div class="muted">查询中…</div>';
  try {
    const r = await api(`/api/portal/trainee-data?uid=${encodeURIComponent(uid)}`);
    const res = r.result;
    const tw = res.this_week.data, lw = res.last_week.data;
    const rows = [
      ['牌子', tw.week_level || '-', lw.week_level || '-'],
      ['礼物流水', tw.week_revenue ?? '-', lw.week_revenue ?? '-'],
      ['每日任务完成次数', tw.daily_task_count ?? '-', lw.daily_task_count ?? '-'],
      ['排档天数', tw.week_schedule_days ?? '-', lw.week_schedule_days ?? '-'],
      ['排档所属大厅', tw.schedule_hall || '-', lw.schedule_hall || '-'],
      ['保护期结束', tw.protection_end || '-', lw.protection_end || '-'],
    ];
    $('#p-data-body').innerHTML = `
      <div class="muted" style="margin-bottom:8px">本周 ${esc(res.this_week.period)} ｜ 上周 ${esc(res.last_week.period)}</div>
      <table>
        <thead><tr><th>项目</th><th>本周</th><th>上周</th></tr></thead>
        <tbody>${rows.map(([k, a, b]) => `<tr><td>${k}</td><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join('')}</tbody>
      </table>`;
  } catch (e) {
    $('#p-data-body').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

$('#p-data-close').addEventListener('click', () => $('#p-data-card').classList.add('hidden'));

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

// 已登录则直接进主界面
(async function init() {
  try {
    const r = await api('/api/portal/me');
    $('#portal-login').classList.add('hidden');
    $('#portal-main').classList.remove('hidden');
    $('#p-welcome').textContent = `${r.trainer.nickname}（${r.trainer.uid}）`;
    renderSlots(r.slots);
  } catch (e) {
    refreshCaptcha();
  }
})();
