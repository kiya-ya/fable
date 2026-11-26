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
    // 课程考试页签铺满页面，隐藏页脚
    document.querySelector('.app-footer').classList.toggle('hidden', btn.dataset.tab === 'courses');
    if (btn.dataset.tab === 'bindings') loadBindingsTab();
    if (btn.dataset.tab === 'dashboard') loadDashboard();
    if (btn.dataset.tab === 'ecology') loadEcologyMembers();
    if (btn.dataset.tab === 'quals') loadQuals();
    if (btn.dataset.tab === 'banners') loadAdminBanners();
    if (btn.dataset.tab === 'courses') {
      const frame = $('#luna-admin-frame');
      if (frame && !frame.src) frame.src = '/admin-bridge';
    }
  });
});

// ────────────── 资质审核（考试系统申请） ──────────────
const QUAL_STATUS = { pending: '待审核', approved: '已通过', rejected: '已驳回' };
const QUAL_ROLE = { sister: '姐妹团姐姐', trainer: '培训师' };
const ROLE_LABEL = { new: '新人', sister: '姐姐', trainer: '培训师' };

async function loadQuals() {
  const tbody = $('#quals-tbody');
  tbody.innerHTML = '<tr><td colspan="8" class="empty">加载中…</td></tr>';
  try {
    const r = await api('/api/admin/qualifications');
    const items = r.items || [];
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无申请</td></tr>';
      return;
    }
    tbody.innerHTML = items.map((a) => {
      const local = a.local ? `${ROLE_LABEL[a.local.role] || a.local.role}` : '<span class="muted">未建档</span>';
      const stCls = a.status === 'pending' ? 'plus' : a.status === 'approved' ? 'active' : 'over';
      const stTag = `<span class="tag ${stCls}">${QUAL_STATUS[a.status] || a.status}</span>` +
        (a.status === 'rejected' && a.reason ? `<div class="muted" style="font-size:12px">${esc(a.reason)}</div>` : '');
      const actions = a.status === 'pending'
        ? `<button class="btn small" onclick="qualApprove(${a.id}, '${esc(a.uid)}')">通过</button>
           <button class="btn small danger" onclick="qualReject(${a.id})">驳回</button>`
        : '<span class="muted">—</span>';
      return `<tr>
        <td>${esc(a.uid)}</td>
        <td>${esc(a.nickname || '-')}</td>
        <td>${QUAL_ROLE[a.package_key] || a.package_key}</td>
        <td><b>${a.percentage}</b> 分</td>
        <td>${esc(a.created_at || '-')}</td>
        <td>${stTag}</td>
        <td>${local}</td>
        <td>${actions}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">${esc(e.message)}</td></tr>`;
  }
}

async function qualApprove(id, uid) {
  if (!confirm(`确认通过 UID ${uid} 的资质申请？\n将自动建档/激活并回写考试系统`)) return;
  try {
    await api(`/api/admin/qualifications/${id}/approve`, { method: 'POST', body: {} });
    toast('已通过并激活');
    loadQuals();
  } catch (e) {
    toast(e.message, true);
  }
}

async function qualReject(id) {
  const reason = prompt('请输入驳回原因（用户端可见）：');
  if (reason === null) return;
  if (!reason.trim()) return toast('驳回需填写原因', true);
  try {
    await api(`/api/admin/qualifications/${id}/reject`, { method: 'POST', body: { reason: reason.trim() } });
    toast('已驳回');
    loadQuals();
  } catch (e) {
    toast(e.message, true);
  }
}

let qualLookupData = null;

function qualLocalText(local) {
  if (!local) return '未建档（首次登录将按当前身份进入）';
  const labels = [];
  if (local.sister_qualified || local.role === 'sister') labels.push('姐妹团');
  if (local.trainer_qualified || local.role === 'trainer') labels.push('培训师');
  return labels.length ? `已开通：${labels.join('、')}` : `当前身份：${ROLE_LABEL[local.role] || local.role || '新人'}`;
}

function qualPlatformText(item) {
  if (!item) return '未查询';
  const status = item.status || (item.approved ? '审核通过' : '未通过');
  return item.approved ? `${status}${item.passed_at ? ' · ' + item.passed_at : ''}` : status;
}

async function lookupQualificationUid() {
  const uid = $('#qual-lookup-uid').value.trim();
  if (!uid) return toast('请输入 UID', true);
  const btn = $('#qual-lookup-btn');
  btn.disabled = true;
  $('#qual-lookup-result').classList.remove('hidden');
  $('#qual-user-summary').textContent = '正在查询 UID 和平台资质…';
  $('#qual-platform-summary').textContent = '';
  try {
    const r = await api('/api/admin/qualifications/lookup?uid=' + encodeURIComponent(uid));
    qualLookupData = r;
    const info = r.info || {};
    const platform = r.platform || {};
    $('#qual-user-summary').innerHTML = `
      <div><b>UID ${esc(r.uid)}${info.nickname ? ' · ' + esc(info.nickname) : ''}</b></div>
      <div class="muted">${esc(info.hall_name || '未查询到大厅')}　｜　${esc(qualLocalText(r.local))}</div>
      <div style="margin-top:8px">点点姐妹团：<b>${esc(qualPlatformText(platform.sister))}</b>　｜　培训师：<b>${esc(qualPlatformText(platform.trainer))}</b></div>`;
    const notices = [r.uid_error, r.platform_error].filter(Boolean);
    $('#qual-platform-summary').textContent = notices.length
      ? `${notices.join('；')}。可人工核对后继续开通。`
      : '已读取平台资质，仅显示点点姐妹团和培训师。';
    $('#qual-grant-sister').checked = Boolean(platform.sister?.approved || r.local?.sister_qualified || r.local?.role === 'sister');
    $('#qual-grant-trainer').checked = Boolean(platform.trainer?.approved || r.local?.trainer_qualified || r.local?.role === 'trainer');
  } catch (e) {
    qualLookupData = null;
    $('#qual-user-summary').textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

$('#qual-lookup-btn').addEventListener('click', lookupQualificationUid);
$('#qual-lookup-uid').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') lookupQualificationUid();
});
$('#qual-grant-submit').addEventListener('click', async () => {
  if (!qualLookupData) return toast('请先查询 UID', true);
  const sister = $('#qual-grant-sister').checked;
  const trainer = $('#qual-grant-trainer').checked;
  if (!sister && !trainer) return toast('请至少选择一项资质', true);
  const btn = $('#qual-grant-submit');
  btn.disabled = true;
  try {
    const info = qualLookupData.info || {};
    const r = await api('/api/admin/qualifications/manual', {
      method: 'POST',
      body: { uid: qualLookupData.uid, nickname: info.nickname || '', hall_name: info.hall_name || '', sister, trainer },
    });
    qualLookupData.local = r;
    $('#qual-user-summary').innerHTML += '<div class="tag active" style="margin-top:8px">已保存，本次开通为累加操作，不会移除另一项资质。</div>';
    toast('资质已开通');
    loadQuals();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

$('#quals-refresh').addEventListener('click', loadQuals);

// ────────────── 首页海报管理 ──────────────
let adminBanners = [];
let editingBannerId = null;
let bannerPreviewObjectUrl = null;

async function loadAdminBanners() {
  const tbody = $('#banners-tbody');
  tbody.innerHTML = '<tr><td colspan="6" class="empty">加载中…</td></tr>';
  try {
    const r = await api('/api/admin/banners');
    adminBanners = r.items || [];
    renderAdminBanners();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">${esc(e.message)}</td></tr>`;
  }
}

function renderAdminBanners() {
  const tbody = $('#banners-tbody');
  if (!adminBanners.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无海报</td></tr>';
    return;
  }
  tbody.innerHTML = adminBanners.map((b, index) => `<tr>
    <td><img src="${esc(b.image_path)}" alt="${esc(b.title)}" style="width:100px;height:56px;object-fit:cover"></td>
    <td><b>${esc(b.title)}</b><div class="muted" style="white-space:pre-line">${esc(b.subtitle || '')}</div></td>
    <td>${b.action === 'modal' ? '点击查看大图' : '仅展示'}</td>
    <td>${b.enabled ? '展示中' : '已停用'}</td>
    <td><button class="btn small" onclick="moveBanner(${b.id}, -1)" ${index === 0 ? 'disabled' : ''}>上移</button>
        <button class="btn small" onclick="moveBanner(${b.id}, 1)" ${index === adminBanners.length - 1 ? 'disabled' : ''}>下移</button></td>
    <td><button class="btn small" onclick="editBanner(${b.id})">编辑</button>
        <button class="btn small" onclick="toggleBanner(${b.id})">${b.enabled ? '停用' : '启用'}</button>
        <button class="btn small danger" onclick="removeBanner(${b.id})">删除</button></td>
  </tr>`).join('');
}

function resetBannerEditor() {
  editingBannerId = null;
  $('#banner-title').value = '';
  $('#banner-subtitle').value = '';
  $('#banner-action').value = 'none';
  $('#banner-file').value = '';
  $('#banner-preview').classList.add('hidden');
  if (bannerPreviewObjectUrl) URL.revokeObjectURL(bannerPreviewObjectUrl);
  bannerPreviewObjectUrl = null;
  $('#banner-editor').classList.add('hidden');
}

function editBanner(id) {
  const b = adminBanners.find(x => x.id === id);
  if (!b) return;
  resetBannerEditor();
  editingBannerId = id;
  $('#banner-title').value = b.title;
  $('#banner-subtitle').value = b.subtitle || '';
  $('#banner-action').value = b.action;
  $('#banner-preview').src = b.image_path;
  $('#banner-preview').classList.remove('hidden');
  $('#banner-editor').classList.remove('hidden');
  $('#banner-editor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function uploadBannerFile(file) {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch('/api/admin/banners/upload', { method: 'POST', body: form });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.msg || '图片上传失败');
  return data.path;
}

async function saveBanner() {
  const title = $('#banner-title').value.trim();
  const file = $('#banner-file').files[0] || null;
  if (!title) return toast('请填写海报标题', true);
  if (!editingBannerId && !file) return toast('请选择海报图片', true);
  const btn = $('#banner-save');
  btn.disabled = true;
  try {
    const existing = adminBanners.find(x => x.id === editingBannerId);
    const image_path = file ? await uploadBannerFile(file) : existing?.image_path;
    const body = { title, subtitle: $('#banner-subtitle').value.trim(),
      action: $('#banner-action').value, image_path };
    if (editingBannerId) {
      await api(`/api/admin/banners/${editingBannerId}`, { method: 'PUT', body });
    } else {
      await api('/api/admin/banners', { method: 'POST', body });
    }
    toast('海报已保存');
    resetBannerEditor();
    loadAdminBanners();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function moveBanner(id, direction) {
  const index = adminBanners.findIndex(x => x.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= adminBanners.length) return;
  [adminBanners[index], adminBanners[target]] = [adminBanners[target], adminBanners[index]];
  try {
    await api('/api/admin/banners/reorder', { method: 'PUT', body: { ids: adminBanners.map(x => x.id) } });
    toast('顺序已保存');
  } catch (e) {
    toast(e.message, true);
  }
  loadAdminBanners();
}

async function toggleBanner(id) {
  const b = adminBanners.find(x => x.id === id);
  if (!b) return;
  try {
    await api(`/api/admin/banners/${id}`, { method: 'PUT', body: { enabled: !b.enabled } });
    toast(b.enabled ? '已停用' : '已启用');
    loadAdminBanners();
  } catch (e) {
    toast(e.message, true);
  }
}

async function removeBanner(id) {
  const b = adminBanners.find(x => x.id === id);
  if (!b || !confirm(`确认删除海报「${b.title}」？此操作只删除展示配置，不删除原图片。`)) return;
  try {
    await api(`/api/admin/banners/${id}`, { method: 'DELETE' });
    toast('海报已删除');
    loadAdminBanners();
  } catch (e) {
    toast(e.message, true);
  }
}

$('#banner-new').addEventListener('click', () => { resetBannerEditor(); $('#banner-editor').classList.remove('hidden'); });
$('#banner-cancel').addEventListener('click', resetBannerEditor);
$('#banner-save').addEventListener('click', saveBanner);
$('#banner-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (bannerPreviewObjectUrl) URL.revokeObjectURL(bannerPreviewObjectUrl);
  bannerPreviewObjectUrl = URL.createObjectURL(file);
  $('#banner-preview').src = bannerPreviewObjectUrl;
  $('#banner-preview').classList.remove('hidden');
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
        ? `<div class="retention-banner ok">${esc(r.retention.msg)}</div>`
        : `<div class="retention-banner bad">${esc(r.retention.msg)}</div>`;
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
  const LEVEL_KEYS = new Set(['week_level', 'best_4week_level']);  // 等级类卡片只显示牌子
  const cards = Object.entries(COMPARE_LABELS).map(([key, label]) => {
    const c = res.compare[key];
    if (!c) return '';
    if (LEVEL_KEYS.has(key)) {
      return `<div class="uq-item">
        <div class="k">${label}</div>
        <div class="v">${esc(c.this)}</div>
      </div>`;
    }
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
    ${overTag}
    <span class="slot-chip">总名额扩充截至 <b>${esc(s.extra_valid_until)}</b></span>
    <div class="muted" style="width:100%;font-size:12px">
      时间口径：额外名额按学员「当月排档周最高等级」实时计算（初银+1/银牌+1/金牌+1，需当周排档天数&gt;0）；
      当月达标当月生效，次月 1 号按新月实际等级重算（月初无新数据时暂用上月等级兜底）——即本月扩充有效期至月底
    </div>`;
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
    bindState[kind] = { uid, nickname: r.info.nickname, hall: r.info.hall_name, protection_end: r.info.protection_end || '', is_elite: r.info.is_elite || '', existing: !!existing };
    let protTag = '';
    if (kind === 'trainee' && r.info.is_elite === '是') {
      protTag = ' ｜ <span class="tag over">精英队长·不可绑定</span>';
    } else if (kind === 'trainee') {
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
  // 精英队长不能绑定为妹妹（服务端仍会再校验一次）
  if (bindState.trainee.is_elite === '是') return toast('该 UID 是精英队长，不能绑定为妹妹', true);
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
let bindingsView = 'active';  // active / history / ops

let bindingsKw = '';

async function loadBindings(page) {
  if (page) bindingsPage = page;
  $('#bindings-export').style.display = bindingsView === 'ops' ? 'none' : '';
  if (bindingsView === 'ops') {
    const data = await api('/api/operations?limit=50');
    $('#bindings-table thead').innerHTML = '<tr><th>时间</th><th>操作者</th><th>动作</th><th>类型</th><th>培训师/姐姐UID</th><th>妹妹UID</th><th>备注</th></tr>';
    const tbody = $('#bindings-table tbody');
    if (!data.items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无操作日志</td></tr>';
    } else {
      tbody.innerHTML = data.items.map((o) => `
        <tr>
          <td>${esc(o.created_at)}</td>
          <td>${o.actor_type === 'portal' ? `用户(${esc(o.actor_uid)})` : o.actor_type === 'admin' ? '管理员' : '系统'}</td>
          <td>${esc(o.action)}</td>
          <td>${esc(o.bind_type === 'sister' ? '姐妹团' : '培训师')}</td>
          <td>${esc(o.trainer_uid)}</td>
          <td>${esc(o.trainee_uid)}</td>
          <td>${esc(o.detail || '')}</td>
        </tr>`).join('');
    }
    $('#bindings-pager').innerHTML = '';
    return;
  }
  $('#bindings-table thead').innerHTML = `<tr>
    <th>类型</th><th>培训师/姐姐</th><th>UID</th><th>妹妹</th><th>UID</th><th>大厅</th><th>保护期结束</th><th>留存</th>
    <th>绑定时间</th><th>结束日期</th><th>剩余奖励</th><th class="col-unbound">解绑时间</th><th>备注</th><th>操作</th>
  </tr>`;
  const params = new URLSearchParams({
    active: bindingsActiveView ? 1 : 0,
    page: bindingsPage,
  });
  if (bindingsTypeFilter) params.set('bind_type', bindingsTypeFilter);
  if (bindingsKw) params.set('kw', bindingsKw);
  const data = await api(`/api/bindings?${params}`);
  const tbody = $('#bindings-table tbody');
  $$('.col-unbound').forEach((el) => (el.style.display = bindingsActiveView ? 'none' : ''));
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="14" class="empty">暂无${bindingsActiveView ? '生效绑定' : '历史记录'}</td></tr>`;
  } else {
    tbody.innerHTML = data.items.map((b) => {
      const weeksTag = b.window_status === 'in_window'
        ? `<span class="tag plus">剩 ${b.weeks_left}/4 周</span><button class="btn small" style="margin-left:4px;padding:1px 6px" onclick="editWeeks(${b.id}, ${b.weeks_left})" title="修改剩余周数">修改</button>`
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
  bindingsView = 'active';
  bindingsPage = 1;
  $('#seg-active').classList.add('active');
  $('#seg-history').classList.remove('active');
  $('#seg-ops').classList.remove('active');
  loadBindings();
});
$('#seg-history').addEventListener('click', () => {
  bindingsActiveView = false;
  bindingsView = 'history';
  bindingsPage = 1;
  $('#seg-history').classList.add('active');
  $('#seg-active').classList.remove('active');
  $('#seg-ops').classList.remove('active');
  loadBindings();
});
$('#seg-ops').addEventListener('click', () => {
  bindingsView = 'ops';
  $('#seg-ops').classList.add('active');
  $('#seg-active').classList.remove('active');
  $('#seg-history').classList.remove('active');
  loadBindings();
});
let bindingsKwTimer = null;
$('#bindings-kw').addEventListener('input', (e) => {
  clearTimeout(bindingsKwTimer);
  bindingsKwTimer = setTimeout(() => {
    bindingsKw = e.target.value.trim();
    loadBindings(1);
  }, 300);
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

// 修改剩余奖励周数
async function editWeeks(id, current) {
  const input = prompt(`修改剩余奖励周数（当前 ${current} 周，可填 0~4）`, String(current));
  if (input === null) return;
  const remaining = parseInt(input, 10);
  if (isNaN(remaining) || remaining < 0 || remaining > 4) return toast('请输入 0~4 的整数', true);
  try {
    await api(`/api/bindings/${id}/set-remaining`, { method: 'POST', body: { remaining } });
    toast(`剩余周数已改为 ${remaining}`);
    loadBindings();
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
          <button class="btn small" onclick="refreshTrainerInfo(${t.id})">刷新</button>
          <button class="btn small" onclick='openPersonModal("trainers", ${JSON.stringify(t)})'>编辑</button>
          <button class="btn small" onclick="previewPortal(${t.id}, '${esc(t.nickname)}')">预览</button>
          <button class="btn small danger" onclick="delPerson('trainers', ${t.id})">删除</button>
        </td>
      </tr>`).join('');
  }
  renderPager('#trainers-pager', data.page, data.page_size, data.total, (p) => loadTrainers(p));
}

// 管理员以该培训师身份预览用户端（新标签页打开）
async function previewPortal(trainerId, nickname) {
  try {
    await api('/api/admin/preview-portal', { method: 'POST', body: { trainer_id: trainerId } });
    window.open('/portal', '_blank');
    toast(`正以「${nickname}」的身份预览用户端`);
  } catch (e) {
    toast(e.message, true);
  }
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
  $('#pm-resetpwd').style.display = kind === 'trainers' && person ? '' : 'none';
  $('#pm-slots').value = person && person.base_slots != null ? person.base_slots : 2;
  $('#pm-status').innerHTML = Object.entries(conf.statuses)
    .map(([k, v]) => `<option value="${k}" ${person && person.status === k ? 'selected' : ''}>${v}</option>`)
    .join('');
  $('#person-modal').classList.remove('hidden');
}

$('#trainer-add').addEventListener('click', () => openPersonModal('trainers', null));

// 管理员重置密码：生成一次性随机密码，仅显示一次
$('#pm-resetpwd').addEventListener('click', async () => {
  const id = $('#pm-id').value;
  if (!id) return;
  if (!confirm('将为该培训师生成新的随机密码，旧密码立即失效。继续？')) return;
  try {
    const r = await api(`/api/trainers/${id}/reset-password`, { method: 'POST' });
    prompt('新密码（仅显示一次，请复制发给该培训师）', r.password);
  } catch (e) {
    toast(e.message, true);
  }
});

// 刷新单个培训师信息（昵称/大厅）
async function refreshTrainerInfo(id) {
  try {
    const r = await api(`/api/trainers/${id}/refresh`, { method: 'POST' });
    toast(r.updated ? `已同步：${r.info.nickname}（${r.info.hall_name || '无大厅'}）` : '未查到可同步的信息');
    loadTrainers();
  } catch (e) {
    toast(e.message, true);
  }
}

// 批量补全昵称/大厅（只处理昵称为 UID 的记录）
$('#trainer-refresh-all').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  btn.textContent = '补全中…';
  try {
    const r = await api('/api/trainers/refresh-all', { method: 'POST' });
    toast(r.total ? `已补全 ${r.updated}/${r.total} 人${r.failed ? `，${r.failed} 人失败` : ''}` : '没有需要补全的记录');
    loadTrainers();
  } catch (e2) {
    toast(e2.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '批量补全信息';
  }
});
$('#trainee-add').addEventListener('click', () => openPersonModal('trainees', null));

// 培训师批量导入
$('#trainer-bulk').addEventListener('click', () => {
  $('#bulk-uids').value = '';
  $('#bulk-modal').classList.remove('hidden');
});
$('#bulk-cancel').addEventListener('click', () => $('#bulk-modal').classList.add('hidden'));
$('#bulk-submit').addEventListener('click', async () => {
  const raw = $('#bulk-uids').value.trim();
  if (!raw) return toast('请输入 UID', true);
  try {
    const r = await api('/api/trainers/bulk-import', { method: 'POST', body: { uids: raw } });
    toast(`导入 ${r.created_count} 人${r.skipped.length ? `，跳过已存在 ${r.skipped.length} 人` : ''}`);
    $('#bulk-modal').classList.add('hidden');
    loadTrainers();
    refreshTotals();
  } catch (e) {
    toast(e.message, true);
  }
});
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
    let r;
    if (id) {
      r = await api(`${PERSON_CONF[kind].url}/${id}`, { method: 'PUT', body });
    } else {
      r = await api(PERSON_CONF[kind].url, { method: 'POST', body });
    }
    toast(r && r.converted ? '已转换为培训师（原为姐姐角色）' : '已保存');
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

// ────────────── 档案与绑定列表导出 ──────────────
async function exportListXlsx(kind, btn) {
  const params = new URLSearchParams();
  if (kind === 'trainers') {
    const kw = $('#trainer-kw').value.trim();
    if (kw) params.set('kw', kw);
  } else if (kind === 'trainees') {
    const kw = $('#trainee-kw').value.trim();
    const status = $('#trainee-status-filter').value;
    if (kw) params.set('kw', kw);
    if (status) params.set('status', status);
  } else {
    params.set('active', bindingsActiveView ? '1' : '0');
    if (bindingsTypeFilter) params.set('bind_type', bindingsTypeFilter);
    if (bindingsKw) params.set('kw', bindingsKw);
  }
  btn.disabled = true;
  const oldText = btn.textContent;
  btn.textContent = '生成中…';
  try {
    const resp = await fetch(`/api/export/${kind}?${params}`);
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.msg || `导出失败 (${resp.status})`);
    }
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const fallback = { trainers: '培训师档案.xlsx', trainees: '妹妹档案.xlsx', bindings: '绑定列表.xlsx', ecology: '生态分四周进步.xlsx' }[kind];
    const filename = m ? decodeURIComponent(m[1]) : fallback;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    toast('导出成功');
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

$('#trainer-export').addEventListener('click', (e) => exportListXlsx('trainers', e.currentTarget));
$('#trainee-export').addEventListener('click', (e) => exportListXlsx('trainees', e.currentTarget));
$('#bindings-export').addEventListener('click', (e) => exportListXlsx('bindings', e.currentTarget));
$('#eco-export').addEventListener('click', (e) => exportListXlsx('ecology', e.currentTarget));

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

// 「奖励已发放」：窗口内绑定剩余周数-1，待发放奖励全部标记已发（未开始的不动）
$('#exp-grant-week').addEventListener('click', async (e) => {
  if (!confirm('确认本周奖励已全部发放？\n所有窗口内绑定的剩余周数将 -1，待发放奖励全部标记为已发。')) return;
  const btn = e.target;
  btn.disabled = true;
  try {
    const r = await api('/api/rewards/grant-week', { method: 'POST' });
    toast(`已处理：${r.bindings} 条绑定周数-1，${r.granted} 档奖励标记已发`);
  } catch (e2) {
    toast(e2.message, true);
  } finally {
    btn.disabled = false;
  }
});

// ────────────── 数据看板 ──────────────
const PIE_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#6b7280'];

async function loadDashboard() {
  try {
    const week = $('#dash-week').value;
    const d = await api('/api/dashboard/summary' + (week ? `?week=${week}` : ''));
    renderDashCards(d);
    renderDashEcology(d.ecology);
    renderLineChart(d.weekly);
    renderPieChart(d.dissolve_reasons);
    renderPieChart(d.dissolve_reasons_week, '#dash-pie-week', '#dash-pie-week-legend');
    renderDissolved(d);
    renderRetentionLine(d.retention_4w_weekly);
    const pg = d.post_graduation || {};
    $('#dash-grad-data-note').textContent = `当前完成完整带教窗口 ${pg.total || 0} 人；已有周追踪数据 ${pg.tracked_total || 0} 人；最近培训师毕业周数据：${pg.latest_week || '暂无'}。毕业后第1周从毕业当天所在自然周开始计算，包含本周进行中的数据；有排档天数即计留存，未同步记录不进入分母。每周一同步本周和上周，历史周可按需回填。`;
  } catch (e) {
    toast(e.message, true);
  }
}

$('#dash-week').addEventListener('change', loadDashboard);

function graduateMetric(metric) {
  if (!metric) return { value: '—', sample: '暂无样本' };
  const value = metric.rate !== null
    ? `${metric.rate}%`
    : metric.cohort > 0 ? '待同步' : '待形成样本';
  return { value, sample: `已同步 ${metric.tracked}/${metric.cohort}` };
}

function renderDashCards(d) {
  const r4 = d.retention_4w;
  const pg = d.post_graduation || {};
  const gw1 = graduateMetric(pg.week1);
  const gw4 = graduateMetric(pg.week4);
  const gp1 = graduateMetric(pg.production_week1);
  const cards = [
    { label: `选中周新绑定（${d.this_week.label}）`, value: d.this_week.bound, color: '#3b82f6' },
    { label: '选中周解散', value: d.this_week.unbound, color: '#ef4444' },
    { label: '当前生效绑定（培训师/姐妹团）', value: `${d.active.total}（${d.active.trainer}/${d.active.sister}）`, color: '#10b981' },
    { label: '奖励待发放 / 已发放（档）', value: `${d.rewards.pending} / ${d.rewards.granted}`, color: '#f59e0b' },
    { label: `解绑后仍在平台（共解绑 ${d.unbound_retention.total} 人）`, value: `${d.unbound_retention.retained} 人 · ${d.unbound_retention.rate}%`, color: '#8E6BC8' },
    { label: `4周留存率·仅培训师（样本 ${r4.cohort}）`, value: `${r4.retention_rate}%`, color: '#10b981' },
    { label: '4周解散率·仅培训师', value: `${r4.dissolution_rate}%`, color: '#ef4444' },
    { label: '完成4周带教（首次毕业）', value: `${pg.total || 0} 人`, color: '#3b82f6' },
    { label: `毕业后第1周留存率（${gw1.sample}）`, value: gw1.value, color: '#10b981' },
    { label: `毕业后第4周留存率（${gw4.sample}）`, value: gw4.value, color: '#8E6BC8' },
    { label: `毕业后第1周产出达标率（${gp1.sample}，≥1344元）`, value: gp1.value, color: '#f59e0b' },
  ];
  $('#dash-cards').innerHTML = cards.map((c) => `
    <div class="dash-card" style="border-top-color:${c.color}">
      <div class="dash-card-label">${esc(c.label)}</div>
      <div class="dash-card-value" style="color:${c.color}">${esc(c.value)}</div>
    </div>`).join('');
}

function renderDissolved(d) {
  const el = $('#dash-dissolved');
  const r4 = d.retention_4w;
  if (!r4.cohort || !r4.dissolved) {
    el.innerHTML = '<span class="muted">暂无 4 周解散样本</span>';
    return;
  }
  const dr = r4.dissolved_retention;
  el.innerHTML = `
    <div style="margin-bottom:12px">
      <div style="font-size:12px;margin-bottom:6px;color:#7a3e12;font-weight:700">解散后是否留存（${r4.dissolved} 条）</div>
      <div style="display:flex;gap:16px">
        <span>解散但留存 <b style="color:#10b981">${dr.retained} 人（${dr.rate}%）</b></span>
        <span>解散未留存 <b style="color:#ef4444">${dr.left} 人（${(100 - dr.rate).toFixed(1)}%）</b></span>
      </div>
    </div>
    <div style="font-size:12px;margin-bottom:4px;color:#7a3e12;font-weight:700">按解散原因</div>
    ${r4.dissolved_reasons.map((r) => `
      <div style="display:flex;justify-content:space-between;padding:4px 0;border-top:1px dashed rgba(122,62,18,.1)">
        <span>${esc(r.reason)}</span><b style="color:#5b2a06">${r.count} 条</b>
      </div>`).join('') || '<span class="muted">暂无</span>'}`;
}

function renderRetentionLine(series) {
  const el = $('#dash-retention-line');
  const data = (series || []).filter((w) => w.rate !== null);
  if (!data.length) {
    el.innerHTML = '<div class="empty">暂无足够样本（绑定满 4 周后才有数据）</div>';
    return;
  }
  const W = 640, H = 240, padL = 40, padB = 28, padT = 14, padR = 10;
  const stepX = data.length > 1 ? (W - padL - padR) / (data.length - 1) : 0;
  const y = (v) => padT + (H - padB - padT) * (1 - v / 100);
  const pts = data.map((w, i) => `${(padL + i * stepX).toFixed(1)},${y(w.rate).toFixed(1)}`).join(' ');
  const dots = data.map((w, i) =>
    `<circle cx="${padL + i * stepX}" cy="${y(w.rate)}" r="4" fill="#8E6BC8" stroke="transparent" stroke-width="12"><title>${w.label} · 留存率 ${w.rate}%（样本 ${w.cohort}）</title></circle>`).join('');
  const labels = data.map((w, i) =>
    `<text x="${padL + i * stepX}" y="${H - 8}" font-size="10" fill="#9ca3af" text-anchor="middle">${w.week_start}</text>`).join('');
  const gridlines = [0, 25, 50, 75, 100].map((v) => {
    const gy = y(v);
    return `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="#e5e7eb" stroke-dasharray="3"/>
            <text x="${padL - 6}" y="${gy + 3}" font-size="10" fill="#9ca3af" text-anchor="end">${v}%</text>`;
  }).join('');
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    ${gridlines}
    <polyline points="${pts}" fill="none" stroke="#8E6BC8" stroke-width="2.5"/>
    ${dots}${labels}
  </svg>`;

  // 悬浮数据卡：周 / 留存率 / 样本 / 留存 / 解散
  el.style.position = 'relative';
  const tip = document.createElement('div');
  tip.className = 'chart-tip hidden';
  el.appendChild(tip);
  const rectW = 640, rectH = 240;
  el.querySelectorAll('circle').forEach((c, i) => {
    const w = data[i];
    c.style.cursor = 'pointer';
    c.addEventListener('mouseenter', () => {
      tip.innerHTML = `<b>${w.label}</b><br>留存率 <b>${w.rate}%</b><br>样本 ${w.cohort} 条：留存 ${w.retained} / 解散 ${w.dissolved}`;
      const scaleX = el.clientWidth / rectW;
      const scaleY = el.clientHeight / rectH;
      tip.style.left = (parseFloat(c.getAttribute('cx')) * scaleX) + 'px';
      tip.style.top = (parseFloat(c.getAttribute('cy')) * scaleY - 8) + 'px';
      tip.classList.remove('hidden');
    });
    c.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

function renderLineChart(weekly) {
  // 裁掉开头连续的全零周（系统上线前的空周），从第一个有数据的周开始显示
  const data = [...weekly];
  while (data.length > 2 && data[0].bound === 0 && data[0].unbound === 0) data.shift();
  const W = 640, H = 240, padL = 40, padB = 28, padT = 14, padR = 10;
  const max = Math.max(1, ...data.map((w) => Math.max(w.bound, w.unbound)));
  const stepX = (W - padL - padR) / (data.length - 1);
  const y = (v) => padT + (H - padB - padT) * (1 - v / max);
  const series = (key) => data.map((w, i) =>
    `${(padL + i * stepX).toFixed(1)},${y(w[key]).toFixed(1)}`).join(' ');
  const dots = (key, color) => data.map((w, i) =>
    `<circle cx="${padL + i * stepX}" cy="${y(w[key])}" r="3.5" fill="${color}" stroke="transparent" stroke-width="12"><title>${w.label} ${w[key]}</title></circle>`).join('');
  const xlabels = data.map((w, i) =>
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

  // 悬浮数据卡：周 / 新绑定 / 解散（circle 顺序：先全部 bound 点，再全部 unbound 点）
  const box = $('#dash-line');
  box.style.position = 'relative';
  const tip = document.createElement('div');
  tip.className = 'chart-tip hidden';
  box.appendChild(tip);
  box.querySelectorAll('circle').forEach((c, i) => {
    const w = data[i % data.length];
    c.style.cursor = 'pointer';
    c.addEventListener('mouseenter', () => {
      tip.innerHTML = `<b>${w.label}</b><br>新绑定 <b>${w.bound}</b> 条 ｜ 解散 <b>${w.unbound}</b> 条`;
      tip.style.left = (parseFloat(c.getAttribute('cx')) * (box.clientWidth / 640)) + 'px';
      tip.style.top = (parseFloat(c.getAttribute('cy')) * (box.clientHeight / 240) - 8) + 'px';
      tip.classList.remove('hidden');
    });
    c.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

function renderPieChart(reasons, pieSel = '#dash-pie', legendSel = '#dash-pie-legend') {
  const total = reasons.reduce((s, r) => s + r.count, 0);
  if (!total) {
    $(pieSel).innerHTML = '<div class="empty">暂无解散记录</div>';
    $(legendSel).innerHTML = '';
    return;
  }
  const CX = 100, CY = 100, R = 90;
  let angle = -Math.PI / 2;  // 从 12 点方向开始
  const slices = reasons.map((r, i) => {
    const frac = r.count / total;
    const a0 = angle;
    const a1 = angle + frac * Math.PI * 2;
    angle = a1;
    const large = frac > 0.5 ? 1 : 0;
    const [x0, y0] = [CX + R * Math.cos(a0), CY + R * Math.sin(a0)];
    const [x1, y1] = [CX + R * Math.cos(a1), CY + R * Math.sin(a1)];
    // 整块（100%）时退化为整圆
    const path = frac >= 0.999
      ? `<circle cx="${CX}" cy="${CY}" r="${R}" fill="${PIE_COLORS[i % PIE_COLORS.length]}"/>`
      : `<path d="M${CX},${CY} L${x0.toFixed(2)},${y0.toFixed(2)} A${R},${R} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z"
          fill="${PIE_COLORS[i % PIE_COLORS.length]}" stroke="#fff" stroke-width="1.5">
          <title>${r.reason}: ${r.count}（${(frac * 100).toFixed(1)}%）</title></path>`;
    return path;
  }).join('');
  $(pieSel).innerHTML = `<svg viewBox="0 0 200 200" style="width:200px;height:200px;max-width:100%">${slices}
    <circle cx="${CX}" cy="${CY}" r="34" fill="#fff"/>
    <text x="${CX}" y="${CY - 2}" text-anchor="middle" font-size="20" font-weight="600">${total}</text>
    <text x="${CX}" y="${CY + 16}" text-anchor="middle" font-size="11" fill="#6b7280">总解散</text></svg>`;
  $(legendSel).innerHTML = reasons.map((r, i) => `
    <div class="pie-legend-item">
      <i class="dot" style="background:${PIE_COLORS[i % PIE_COLORS.length]}"></i>
      ${esc(r.reason)} <b>${r.count}</b>（${(r.count / total * 100).toFixed(1)}%）
    </div>`).join('');
}

// ────────────── 启动（默认首页 = 绑定关系） ──────────────
$('#dash-week').value = new Date().toLocaleDateString('sv-SE');
initUidQuery();
loadBindingsTab();

// ────────────── 生态分 ──────────────
let ecoPage = 1;
let ecoJobId = null;
let ecoPollTimer = null;
let ecoDetailUid = null;
const ECO_ROLE_LABEL = { trainer: '培训师', sister: '姐妹团姐姐', new: '新人（未获资质）', trainee: '妹妹' };
const ECO_DIM_LABEL = {
  bonusAtmos: '活跃大厅', bonusEvent: '参加活动', bonusBoard: '板块游戏', bonusAcquire: '获客',
  bonusArpu: 'ARPU 值提升', bonusMaintain: '维护老板', bonusBack: '用户挽回', bonusHome: '发帖和相册',
  bonusHall: '大厅活跃明细', bonusKeep: '留存维护', bonusPost: '社区内容', bonusManual: '运营调整',
  bonusInvite: '邀请码', bonusFleet: '新老板车队',
};

function ecoNum(value) {
  if (value === null || value === undefined || value === '') return '--';
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) : '--';
}

function ecoChange(value) {
  const number = Number(value || 0);
  if (!number) return '';
  return `<small class="${number > 0 ? 'eco-delta-up' : 'eco-delta-down'}">${number > 0 ? '↑' : '↓'}${Math.abs(number)}</small>`;
}

function ecoGrade(latest) {
  if (!latest || !latest.eco_grade) return '<span class="muted">未评分</span>';
  const cls = latest.eco_grade === 'S+' ? 'splus' : latest.eco_grade.toLowerCase();
  return `<span class="eco-grade ${cls}">${esc(latest.eco_grade)}</span>${ecoChange(latest.eco_grade_change)}`;
}

async function loadEcologyMembers(page = ecoPage) {
  ecoPage = page;
  const tbody = $('#eco-tbody');
  tbody.innerHTML = '<tr><td colspan="14" class="empty">加载中…</td></tr>';
  const params = new URLSearchParams({ page, page_size: 20, kw: $('#eco-kw').value.trim(), role: $('#eco-role').value, grade: $('#eco-grade').value });
  try {
    const data = await api('/api/ecology/members?' + params);
    const stats = data.stats || {};
    $('#eco-total').textContent = data.total;
    $('#eco-scored').textContent = stats.scored || 0;
    $('#eco-average').textContent = stats.average === null || stats.average === undefined ? '--' : stats.average;
    $('#eco-excellent').textContent = stats.excellent || 0;
    if (!data.items.length) {
      tbody.innerHTML = '<tr><td colspan="14" class="empty">没有匹配的人员或生态分记录</td></tr>';
    } else {
      tbody.innerHTML = data.items.map(person => {
        const latest = person.latest;
        const values = ['active_hall', 'event_score', 'board_score', 'acquire_score', 'arpu_score', 'maintain_score', 'back_score', 'home_score']
          .map(key => `<td>${latest ? ecoNum(latest[key]) : '--'}</td>`).join('');
        return `<tr>
          <td class="eco-person"><b>${esc(person.nickname || '-')}</b><small>${esc(person.uid)}</small></td>
          <td>${ECO_ROLE_LABEL[person.role] || esc(person.role)}<small class="eco-week">${esc((latest && latest.hall_name) || person.hall_name || '-')}</small></td>
          <td>${ecoGrade(latest)}</td>
          <td>${latest && latest.score !== null && latest.score !== undefined ? `<span class="eco-score">${ecoNum(latest.score)}</span><small class="eco-week">${esc(latest.week_start)}</small>` : '<span class="muted">未评分</span>'}</td>
          ${values}
          <td class="eco-hints">${latest && latest.hints && latest.hints.length ? esc(latest.hints.join('、')) : '—'}</td>
          <td><button class="btn small" type="button" onclick="openEcologyDetail('${esc(person.uid)}')">详情</button></td>
        </tr>`;
      }).join('');
    }
    renderPager('#eco-pager', data.page, data.page_size, data.total, loadEcologyMembers);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="14" class="empty">${esc(e.message)}</td></tr>`;
  }
}

function ecoRenderItems(items, depth = 0) {
  if (!Array.isArray(items) || !items.length) return '';
  return items.map(item => `<div class="eco-dim-row" style="padding-left:${depth * 12}px"><span>${esc(item.label)}</span><span>${ecoNum(item.value)}</span></div>${ecoRenderItems(item.children, depth + 1)}`).join('');
}

function ecoDetailHtml(data) {
  const people = data.people || [];
  const history = data.history || [];
  const latest = history[0];
  const names = people.map(p => p.nickname).filter(Boolean);
  const roles = people.map(p => ECO_ROLE_LABEL[p.role] || p.role).filter((v, i, a) => a.indexOf(v) === i);
  const dims = latest && latest.eco_items ? Object.entries(latest.eco_items).filter(([, items]) => Array.isArray(items) && items.length) : [];
  const scoreDelta = (index) => {
    const current = history[index];
    const previous = history[index + 1];
    if (!current || !previous || current.score === null || current.score === undefined || previous.score === null || previous.score === undefined) return '--';
    const delta = current.score - previous.score;
    return `<span class="${delta > 0 ? 'eco-delta-up' : delta < 0 ? 'eco-delta-down' : ''}">${delta > 0 ? '+' : ''}${ecoNum(delta)}</span>`;
  };
  return `<div class="eco-detail-summary">
    <div><b>${esc(names.join(' / ') || (latest && latest.nickname) || '未知')}</b><div class="muted">${esc(roles.join(' + ') || '平台用户')} · ${esc((latest && latest.hall_name) || (people[0] && people[0].hall_name) || '-')}</div></div>
    ${latest ? `<div>${ecoGrade(latest)}</div><div class="eco-score">${ecoNum(latest.score)}</div><div class="muted">${esc(latest.week_start)}</div>` : '<span class="muted">暂无生态分记录</span>'}
  </div>
  ${latest ? `<div class="muted" style="margin-bottom:12px">队长牌子：${esc(latest.level || '--')} · 流水：${ecoNum(latest.flow)}${latest.hints && latest.hints.length ? ` · 生态提示：<b>${esc(latest.hints.join('、'))}</b>` : ''}</div>` : ''}
  <section class="eco-detail-section"><h3>最近 ${history.length} 周趋势</h3><div style="overflow-x:auto"><table class="eco-history"><thead><tr><th>周起始</th><th>等级</th><th>生态分</th><th>分数周变化</th><th>活跃大厅</th><th>维护老板</th><th>生态提示</th></tr></thead><tbody>
    ${history.map((row, index) => `<tr><td>${esc(row.week_start)}</td><td>${ecoGrade(row)}</td><td><b>${ecoNum(row.score)}</b></td><td>${scoreDelta(index)}</td><td>${ecoNum(row.active_hall)}</td><td>${ecoNum(row.maintain_score)}</td><td class="eco-hints">${row.hints && row.hints.length ? esc(row.hints.join('、')) : '—'}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">暂无历史记录</td></tr>'}
  </tbody></table></div></section>
  ${dims.length ? `<section class="eco-detail-section"><h3>分项加减分（点击展开）</h3><div class="eco-dim-grid">${dims.map(([key, items]) => {
    const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0);
    return `<details class="eco-dim"><summary><b>${ECO_DIM_LABEL[key] || esc(key)}</b><span>${ecoNum(total)}</span></summary><div class="eco-dim-body">${ecoRenderItems(items)}</div></details>`;
  }).join('')}</div></section>` : ''}`;
}

async function openEcologyDetail(uid) {
  ecoDetailUid = uid;
  $('#eco-detail-title').textContent = `生态分详情 · UID ${uid}`;
  $('#eco-detail-content').innerHTML = '<div class="empty">加载中…</div>';
  $('#eco-detail-modal').classList.remove('hidden');
  try {
    const data = await api(`/api/ecology/members/${encodeURIComponent(uid)}`);
    $('#eco-detail-content').innerHTML = ecoDetailHtml(data);
  } catch (e) {
    $('#eco-detail-content').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  }
}

async function startEcologyRefresh(uids) {
  try {
    const data = await api('/api/ecology/refresh', {
      method: 'POST',
      body: { uids: uids || [], weeks: Number($('#eco-weeks').value) },
    });
    ecoJobId = data.job.id;
    $('#eco-job').classList.remove('hidden');
    $('#eco-refresh').disabled = true;
    if (ecoPollTimer) clearInterval(ecoPollTimer);
    pollEcologyJob();
    ecoPollTimer = setInterval(pollEcologyJob, 1000);
    if (data.already_running) toast('已加入正在进行的刷新任务');
  } catch (e) {
    toast(e.message, true);
  }
}

async function pollEcologyJob() {
  if (!ecoJobId) return;
  try {
    const job = await api(`/api/ecology/refresh/${ecoJobId}`);
    const completed = job.completed || 0;
    const total = job.total || 0;
    const pct = total ? Math.round(completed / total * 100) : 0;
    $('#eco-job-text').textContent = job.running
      ? `正在刷新 ${completed}/${total} 人 · 成功 ${job.success} · 失败 ${job.failed}`
      : `刷新完成 · 成功 ${job.success} · 失败 ${job.failed} · 保存 ${job.saved} 条周记录${job.errors && job.errors.length ? ` · ${job.errors[0].msg}` : ''}`;
    $('#eco-job-bar').style.width = `${job.running ? pct : 100}%`;
    if (!job.running) {
      clearInterval(ecoPollTimer);
      ecoPollTimer = null;
      ecoJobId = null;
      $('#eco-refresh').disabled = false;
      toast(`生态分刷新完成：成功 ${job.success} 人，失败 ${job.failed} 人`, job.failed > 0);
      loadEcologyMembers();
      if (ecoDetailUid && !$('#eco-detail-modal').classList.contains('hidden')) openEcologyDetail(ecoDetailUid);
    }
  } catch (e) {
    clearInterval(ecoPollTimer);
    ecoPollTimer = null;
    ecoJobId = null;
    $('#eco-refresh').disabled = false;
    toast(e.message, true);
  }
}

async function loadEcologyConfig() {
  try {
    const data = await api('/api/ecology/config');
    $('#eco-token-status').textContent = data.configured
      ? `已配置登录态 · ${data.updated_at || '时间未知'} · 保存新 Token 只会覆盖本机配置，不会在页面回显`
      : '尚未配置 Admin-Token';
  } catch (e) {
    $('#eco-token-status').textContent = e.message;
  }
}

$('#eco-search').addEventListener('click', () => loadEcologyMembers(1));
$('#eco-kw').addEventListener('keydown', event => { if (event.key === 'Enter') loadEcologyMembers(1); });
$('#eco-role').addEventListener('change', () => loadEcologyMembers(1));
$('#eco-grade').addEventListener('change', () => loadEcologyMembers(1));
$('#eco-refresh').addEventListener('click', () => startEcologyRefresh());
$('#eco-detail-refresh').addEventListener('click', () => { if (ecoDetailUid) startEcologyRefresh([ecoDetailUid]); });
$('#eco-token-toggle').addEventListener('click', () => {
  $('#eco-token-panel').classList.toggle('hidden');
  loadEcologyConfig();
});
$('#eco-token-save').addEventListener('click', async () => {
  const token = $('#eco-token').value.trim();
  if (!token) return toast('请输入 Admin-Token', true);
  try {
    await api('/api/ecology/config', { method: 'POST', body: { admin_token: token } });
    $('#eco-token').value = '';
    $('#eco-token-panel').classList.add('hidden');
    toast('生态分接口登录态已更新');
  } catch (e) {
    toast(e.message, true);
  }
});

function renderDashEcology(eco) {
  if (!eco) return;
  $('#dash-eco-week').textContent = eco.latest_week ? `仅当前生效培训师绑定的妹妹 · 最新归档周 ${eco.latest_week}` : '暂无妹妹生态分数据';
  const cards = [
    { label: '已评分妹妹 / 未评分妹妹', value: `${eco.scored} / ${eco.unscored}`, color: '#3b82f6' },
    { label: '妹妹平均生态分', value: eco.average === null ? '--' : eco.average, color: '#8E6BC8' },
    { label: 'S / S+ 妹妹人数', value: eco.excellent, color: '#10b981' },
    { label: '本周上升 / 下降妹妹人数', value: `${eco.improving} / ${eco.declining}`, color: '#f59e0b' },
  ];
  $('#dash-eco-cards').innerHTML = cards.map(card => `<div class="dash-card" style="border-top-color:${card.color}"><div class="dash-card-label">${card.label}</div><div class="dash-card-value" style="color:${card.color}">${card.value}</div></div>`).join('');
  const gradeOrder = ['S+', 'S', 'A', 'B', 'C', 'D', '未评分'];
  const grades = eco.grades || {};
  const maxGrade = Math.max(1, ...Object.values(grades));
  $('#dash-eco-grades').innerHTML = gradeOrder.filter(grade => grades[grade]).map(grade => `<div class="dash-eco-grade-row"><span>${grade}</span><div class="dash-eco-grade-track"><i style="width:${grades[grade] / maxGrade * 100}%"></i></div><b>${grades[grade]}</b></div>`).join('') || '<span class="muted">暂无等级数据</span>';
  const personRows = (items, mode) => items.length ? items.map(person => `<button type="button" class="dash-eco-person" onclick="openEcologyDetail('${esc(person.uid)}')"><span>${esc(person.nickname || person.uid)}<small>${esc(person.hall_name || '-')} · ${esc(person.eco_grade || '未评分')}</small></span><b class="${mode === 'down' ? 'eco-delta-down' : ''}">${mode === 'down' ? ecoNum(person.delta) : ecoNum(person.score)}</b></button>`).join('') : '<span class="muted">暂无数据</span>';
  $('#dash-eco-top').innerHTML = personRows(eco.top || [], 'top');
  $('#dash-eco-declines').innerHTML = personRows(eco.declines || [], 'down');
}
