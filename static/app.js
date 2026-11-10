const state = { documents: [], renewals: [], searchResults: null, selectedWindow: 7, editingId: null, renewingId: null };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const today = new Date();
today.setHours(0, 0, 0, 0);

function dateText(value, options = { day: 'numeric', month: 'short', year: 'numeric' }) {
  if (!value) return '—';
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, options);
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
function remainingLabel(days) {
  if (days < 0) return `${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'} ago`;
  if (days === 0) return 'Today';
  return `${days} day${days === 1 ? '' : 's'} left`;
}
function statusClass(status) {
  return status === 'Expired' ? 'status-expired' : status === 'Expiring Soon' ? 'status-soon' : 'status-active';
}
function iconFor(type) {
  const lower = type.toLowerCase();
  if (lower.includes('insurance')) return '◇';
  if (lower.includes('passport')) return '▣';
  if (lower.includes('licence') || lower.includes('license')) return '▱';
  if (lower.includes('software') || lower.includes('certification')) return '⌘';
  if (lower.includes('education')) return '⌑';
  return '▤';
}
async function request(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.error || 'Something went wrong. Please try again.');
  return payload;
}
async function loadData() {
  try {
    const [docs, renewals] = await Promise.all([request('/api/documents'), request('/api/renewals')]);
    state.documents = docs;
    state.renewals = renewals;
    state.searchResults = null;
    render();
  } catch (err) {
    toast(err.message, true);
  }
}
function rowHtml(doc) {
  const remainingClass = doc.days_remaining < 0 ? 'danger' : doc.days_remaining <= 7 ? 'warning' : '';
  return `<tr>
    <td><div class="doc-cell"><span class="doc-icon">${iconFor(doc.doc_type)}</span><span class="doc-name">${escapeHtml(doc.name)}<span class="doc-type">${escapeHtml(doc.doc_type)}</span></span></div></td>
    <td class="date-cell">${dateText(doc.issue_date)}</td><td class="date-cell">${dateText(doc.expiry_date)}</td>
    <td><span class="status-badge ${statusClass(doc.status)}">${escapeHtml(doc.status)}</span></td>
    <td><span class="remaining ${remainingClass}">${remainingLabel(doc.days_remaining)}</span></td>
    <td class="row-actions"><div class="row-menu-wrap"><button class="row-menu" data-menu="${doc.id}" aria-label="Actions for ${escapeHtml(doc.name)}">···</button><div class="row-popover hidden" id="menu-${doc.id}"><button data-edit="${doc.id}">Edit details</button><button data-renew="${doc.id}">Renew document</button><button class="delete-action" data-delete="${doc.id}">Delete</button></div></div></td>
  </tr>`;
}
function renderTable(tbody, empty, count, search, filter, limit = Infinity) {
  const term = search.trim().toLowerCase();
  const source = tbody.id === 'all-document-rows' && state.searchResults !== null ? state.searchResults : state.documents;
  const filtered = source.filter(doc => (filter === 'all' || doc.status === filter) && (!term || `${doc.name} ${doc.doc_type}`.toLowerCase().includes(term)));
  const shown = filtered.slice(0, limit);
  tbody.innerHTML = shown.map(rowHtml).join('');
  empty.classList.toggle('hidden', shown.length !== 0);
  count.textContent = `Showing ${shown.length}${filtered.length !== shown.length ? ` of ${filtered.length}` : ''} document${filtered.length === 1 ? '' : 's'}`;
  return filtered;
}
function reportRows() {
  const filter = state.reportFilter || 'all';
  return state.documents.filter(doc => {
    if (filter === 'all') return true;
    if (filter === 'active') return doc.status === 'Active';
    if (filter === 'expired') return doc.status === 'Expired';
    const days = Number(filter);
    return doc.days_remaining >= 0 && doc.days_remaining <= days;
  });
}
async function loadSelectedReport() {
  const filter = state.reportFilter || 'all';
  try {
    const result = await request(`/api/reports/${encodeURIComponent(filter)}`);
    $('#report-count').textContent = `${result.count} record${result.count === 1 ? '' : 's'}`;
    if (filter === 'renewals') {
      $('#report-title').textContent = 'Renewal history';
      $('#report-description').textContent = 'Previous and renewed validity dates for every recorded renewal.';
      $('#status-report-table').classList.add('hidden');
      $('#renewal-report-table').classList.toggle('hidden', result.items.length === 0);
      $('#report-renewal-rows').innerHTML = result.items.map(item => `<tr><td><strong class="report-name">${escapeHtml(item.document_name || 'Removed document')}</strong></td><td>${dateText(item.previous_issue_date)}</td><td>${dateText(item.previous_expiry_date)}</td><td>${dateText(item.new_issue_date)}</td><td>${dateText(item.new_expiry_date)}</td><td>${new Date(`${item.renewed_at.replace(' ', 'T')}Z`).toLocaleDateString()}</td></tr>`).join('');
      $('#report-empty-title').textContent = 'No renewals recorded yet';
      $('#report-empty-copy').textContent = 'Renewed documents will appear here with their previous and new validity dates.';
      $('#export-report').href = '/api/renewals.csv';
      $('#export-xlsx').href = '/api/renewals.xlsx';
    } else {
      const names = { all: 'All documents', active: 'Active documents', expired: 'Expired documents', 7: 'Documents expiring within 7 days', 15: 'Documents expiring within 15 days', 30: 'Documents expiring within 30 days' };
      $('#report-title').textContent = names[filter];
      $('#report-description').textContent = filter === 'active' ? 'Documents with more than 30 days of validity remaining.' : filter === 'expired' ? 'Documents whose expiry date has passed.' : filter === 'all' ? 'Current status and remaining validity for every saved document.' : `Documents expiring from today through the next ${filter} days.`;
      $('#status-report-table').classList.toggle('hidden', result.items.length === 0);
      $('#renewal-report-table').classList.add('hidden');
      $('#report-rows').innerHTML = result.items.map(doc => `<tr><td class="report-id">DOC${String(doc.id).padStart(3, '0')}</td><td><strong class="report-name">${escapeHtml(doc.name)}</strong></td><td>${escapeHtml(doc.doc_type)}</td><td>${dateText(doc.issue_date)}</td><td>${dateText(doc.expiry_date)}</td><td><strong>${remainingLabel(doc.days_remaining)}</strong></td><td><span class="status-badge ${statusClass(doc.status)}">${escapeHtml(doc.status)}</span></td></tr>`).join('');
      $('#report-empty-title').textContent = 'No matching documents';
      $('#report-empty-copy').textContent = 'There are no records for this report yet.';
      $('#export-report').href = `/api/report.csv?type=${encodeURIComponent(filter)}`;
      $('#export-xlsx').href = `/api/report.xlsx?type=${encodeURIComponent(filter)}`;
    }
    $('#report-empty').classList.toggle('hidden', result.items.length !== 0);
    $$('.report-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.report === filter));
  } catch (err) { toast(err.message, true); }
}
function renderReport() {
  const names = { all: 'All documents', active: 'Active documents', expired: 'Expired documents', 7: 'Documents expiring within 7 days', 15: 'Documents expiring within 15 days', 30: 'Documents expiring within 30 days', renewals: 'Renewal history' };
  if (state.reportFilter === 'renewals') { loadSelectedReport(); return; }
  const items = reportRows();
  $('#status-report-table').classList.remove('hidden');
  $('#renewal-report-table').classList.add('hidden');
  $('#report-title').textContent = names[state.reportFilter || 'all'];
  $('#report-description').textContent = state.reportFilter === 'active' ? 'Documents with more than 30 days of validity remaining.' : state.reportFilter === 'expired' ? 'Documents whose expiry date has passed.' : state.reportFilter === 'all' ? 'Current status and remaining validity for every saved document.' : 'Documents expiring between today and the selected date range.';
  $('#report-count').textContent = `${items.length} record${items.length === 1 ? '' : 's'}`;
  $('#report-rows').innerHTML = items.map(doc => `<tr><td class="report-id">DOC${String(doc.id).padStart(3, '0')}</td><td><strong class="report-name">${escapeHtml(doc.name)}</strong></td><td>${escapeHtml(doc.doc_type)}</td><td>${dateText(doc.issue_date)}</td><td>${dateText(doc.expiry_date)}</td><td><strong>${remainingLabel(doc.days_remaining)}</strong></td><td><span class="status-badge ${statusClass(doc.status)}">${escapeHtml(doc.status)}</span></td></tr>`).join('');
  $('#report-empty').classList.toggle('hidden', items.length !== 0);
  $('#report-rows').closest('.table-scroll').classList.toggle('hidden', items.length === 0);
  $('#report-empty-title').textContent = 'No matching documents';
  $('#report-empty-copy').textContent = 'There are no records for this report yet.';
  $('#export-report').href = '/api/report.csv';
  $('#export-xlsx').href = '/api/report.xlsx';
  $$('.report-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.report === String(state.reportFilter || 'all')));
  if (document.querySelector('#reports-view:not(.hidden)')) loadSelectedReport();
}
function renderOverview() {
  const total = state.documents.length;
  const active = state.documents.filter(d => d.status === 'Active').length;
  const soon = state.documents.filter(d => d.status === 'Expiring Soon').length;
  const expired = state.documents.filter(d => d.status === 'Expired').length;
  const percentage = value => total ? Math.round(value * 100 / total) : 0;
  $('#donut-total').textContent = total;
  $('#legend-active').textContent = active; $('#percent-active').textContent = percentage(active);
  $('#legend-soon').textContent = soon; $('#percent-soon').textContent = percentage(soon);
  $('#legend-expired').textContent = expired; $('#percent-expired').textContent = percentage(expired);
  const activeAngle = percentage(active) * 3.6;
  const soonAngle = activeAngle + percentage(soon) * 3.6;
  $('#status-donut').style.background = total
    ? `conic-gradient(#2476d2 0deg ${activeAngle}deg,#f5a623 ${activeAngle}deg ${soonAngle}deg,#e64b4b ${soonAngle}deg 360deg)`
    : 'conic-gradient(#dce3ef 0deg 360deg)';
  const upcoming = state.documents.filter(d => d.days_remaining >= 0 && d.days_remaining <= 30).sort((a,b) => a.days_remaining-b.days_remaining).slice(0, 5);
  $('#alert-list').innerHTML = upcoming.map(doc => `<div class="alert-row"><span class="alert-days ${doc.days_remaining <= 7 ? 'alert-urgent' : ''}">In ${doc.days_remaining} day${doc.days_remaining === 1 ? '' : 's'}</span><strong>${escapeHtml(doc.name)}</strong><span>Expiry: ${dateText(doc.expiry_date, { day: '2-digit', month: '2-digit', year: 'numeric' })}</span></div>`).join('');
  $('#alert-empty').classList.toggle('hidden', upcoming.length !== 0);
}
function renderUpcoming() {
  const list = $('#upcoming-list');
  if (!list) return;
  const cutoff = state.selectedWindow;
  const items = state.documents.filter(doc => doc.days_remaining >= 0 && doc.days_remaining <= cutoff).sort((a, b) => a.days_remaining - b.days_remaining);
  list.innerHTML = items.map(doc => {
    const exp = new Date(`${doc.expiry_date}T00:00:00`);
    return `<div class="upcoming-item"><div class="upcoming-date"><strong>${exp.getDate()}</strong><span>${exp.toLocaleDateString(undefined, { month: 'short' })}</span></div><div class="upcoming-copy"><strong>${escapeHtml(doc.name)}</strong><small>${escapeHtml(doc.doc_type)} · ${doc.days_remaining === 0 ? 'Expires today' : `Expires in ${doc.days_remaining} day${doc.days_remaining === 1 ? '' : 's'}`}</small></div><span class="days-pill">${doc.days_remaining === 0 ? 'Today' : `${doc.days_remaining}d`}</span></div>`;
  }).join('');
  $('#upcoming-empty').classList.toggle('hidden', items.length !== 0);
  list.classList.toggle('hidden', items.length === 0);
  $('#window-label').textContent = `${cutoff} days`;
}
function renderRenewals() {
  const tbody = $('#renewal-rows');
  tbody.innerHTML = state.renewals.map(item => `<tr><td><div class="doc-cell"><span class="doc-icon">${iconFor(item.document_name || 'Document')}</span><span class="doc-name">${escapeHtml(item.document_name || 'Removed document')}</span></div></td><td class="date-cell">${dateText(item.previous_issue_date)}</td><td class="date-cell">${dateText(item.previous_expiry_date)}</td><td class="date-cell">${dateText(item.new_issue_date)}</td><td class="date-cell">${dateText(item.new_expiry_date)}</td><td class="date-cell">${new Date(`${item.renewed_at.replace(' ', 'T')}Z`).toLocaleDateString()}</td></tr>`).join('');
  $('#renewal-count').textContent = `${state.renewals.length} record${state.renewals.length === 1 ? '' : 's'}`;
  $('#renewal-empty').classList.toggle('hidden', state.renewals.length !== 0);
  tbody.closest('.table-scroll').classList.toggle('hidden', state.renewals.length === 0);
}
function render() {
  const total = state.documents.length;
  $('#nav-count').textContent = total;
  $('#stat-total').textContent = total;
  $('#stat-active').textContent = state.documents.filter(d => d.status === 'Active').length;
  $('#stat-soon').textContent = state.documents.filter(d => d.status === 'Expiring Soon').length;
  $('#stat-expired').textContent = state.documents.filter(d => d.status === 'Expired').length;
  const active = state.documents.filter(d => d.status === 'Active').length;
  const soon = state.documents.filter(d => d.status === 'Expiring Soon').length;
  $('#stat-donut');
  renderOverview();
  const recentRows = state.documents.slice(0, 8).map(doc => `<tr><td class="report-id">DOC${String(doc.id).padStart(3, '0')}</td><td><strong class="report-name">${escapeHtml(doc.name)}</strong></td><td>${escapeHtml(doc.doc_type)}</td><td>${dateText(doc.issue_date, {day:'2-digit',month:'2-digit',year:'numeric'})}</td><td>${dateText(doc.expiry_date, {day:'2-digit',month:'2-digit',year:'numeric'})}</td><td><strong>${remainingLabel(doc.days_remaining)}</strong></td><td><span class="status-badge ${statusClass(doc.status)}">${escapeHtml(doc.status)}</span></td><td><button class="button button-primary button-small" data-renew="${doc.id}">Renew</button></td></tr>`).join('');
  $('#document-rows').innerHTML = recentRows;
  $('#table-empty').classList.toggle('hidden', total !== 0);
  $('#document-rows').closest('.table-scroll').classList.toggle('hidden', total === 0);
  $('#row-count').textContent = `Showing ${Math.min(total, 8)} of ${total} document${total === 1 ? '' : 's'}`;
  renderTable($('#all-document-rows'), $('#all-table-empty'), $('#all-row-count'), $('#search-all').value, $('#status-filter-all').value);
  $('#all-docs-subtitle').textContent = `${total} document${total === 1 ? '' : 's'} saved to this workspace.`;
  renderUpcoming();
  renderRenewals();
  renderReport();
}
function toast(message, isError = false) {
  const node = $('#toast'); node.textContent = message; node.classList.toggle('toast-error', isError); node.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 2800);
}
function setView(name, activeAction = '') {
  const viewName = ['dashboard', 'documents', 'renewals', 'reports'].includes(name) ? name : 'dashboard';
  $$('.view').forEach(view => view.classList.toggle('hidden', view.id !== `${viewName}-view`));
  $$('.nav-link').forEach(link => {
    const active = activeAction
      ? link.dataset.navAction === activeAction
      : link.dataset.view === viewName;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const crumb = $('#crumb');
  if (crumb) crumb.textContent = viewName === 'dashboard' ? 'Overview' : viewName === 'documents' ? 'All documents' : viewName === 'renewals' ? 'Renewal history' : 'Status reports';
  if (location.hash !== `#${viewName}`) history.replaceState(null, '', `#${viewName}`);
}
function openDocumentForm(doc = null) {
  state.editingId = doc?.id ?? null;
  const form = $('#document-form'); form.reset(); $('#form-error').classList.add('hidden');
  $('#form-title').textContent = doc ? 'Edit document' : 'Add a document';
  $('#form-eyebrow').textContent = doc ? 'UPDATE RECORD' : 'NEW RECORD';
  $('#save-button').innerHTML = doc ? 'Save changes <span>→</span>' : 'Save document <span>→</span>';
  if (doc) {
    $('#doc-name').value = doc.name;
    const knownType = [...$('#doc-type').options].some(o => o.value === doc.doc_type);
    if (!knownType) { const option = new Option(doc.doc_type, doc.doc_type); $('#doc-type').add(option); }
    $('#doc-type').value = doc.doc_type;
    $('#issue-date').value = doc.issue_date;
    $('#expiry-date').value = doc.expiry_date;
  }
  $('#document-dialog').showModal();
}
function openRenewForm(doc = null) {
  if (!state.documents.length) { toast('Add or load a fictional document before renewing.'); return; }
  const selected = doc || state.documents.find(item => item.status === 'Expiring Soon') || state.documents[0];
  state.renewingId = selected.id;
  $('#renew-form').reset(); $('#renew-error').classList.add('hidden');
  $('#renew-document-select').innerHTML = state.documents.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${escapeHtml(item.status)}</option>`).join('');
  $('#renew-document-select').value = String(selected.id);
  $('#renew-document-name').textContent = `${selected.name} · Current expiry ${dateText(selected.expiry_date)}. The current dates will be saved in history.`;
  $('#renew-dialog').showModal();
}

document.addEventListener('click', async event => {
  const samples = event.target.closest('#load-samples');
  if (samples) {
    try {
      const result = await request('/api/demo-data', { method: 'POST' });
      await loadData();
      const summary = [result.added ? `${result.added} fictional documents added` : '', result.renewals_added ? `${result.renewals_added} renewal history entries added` : ''].filter(Boolean).join(' · ');
      toast(summary || 'Fictional examples and renewal history are already present.');
    } catch (err) { toast(err.message, true); }
    return;
  }
  const add = event.target.closest('[data-open-add]');
  if (add) return openDocumentForm();
  const close = event.target.closest('[data-close-dialog]'); if (close) return $('#document-dialog').close();
  const closeRenew = event.target.closest('[data-close-renew]'); if (closeRenew) return $('#renew-dialog').close();
  const nav = event.target.closest('[data-view]'); if (nav) { event.preventDefault(); setView(nav.dataset.view); return; }
  const reportShortcut = event.target.closest('[data-report-link]');
  if (reportShortcut) {
    event.preventDefault();
    state.reportFilter = reportShortcut.dataset.reportLink;
    const action = reportShortcut.dataset.navAction || '';
    setView('reports', action);
    loadSelectedReport();
    return;
  }
  if (event.target.closest('[data-focus-search]')) {
    event.preventDefault();
    state.searchResults = null;
    setView('documents', 'search');
    renderTable($('#all-document-rows'), $('#all-table-empty'), $('#all-row-count'), $('#search-all').value, $('#status-filter-all').value);
    setTimeout(() => $('#search-all').focus(), 0);
    return;
  }
  if (event.target.closest('[data-focus-renew]')) {
    openRenewForm();
    return;
  }
  if (event.target.closest('#view-all-link')) { event.preventDefault(); setView('documents'); return; }
  if (event.target.closest('#history-shortcut')) return setView('renewals');
  const reportTab = event.target.closest('[data-report]');
  if (reportTab) { state.reportFilter = reportTab.dataset.report; return loadSelectedReport(); }
  const range = event.target.closest('[data-days]');
  if (range) { state.selectedWindow = Number(range.dataset.days); $$('.range-tab').forEach(tab => tab.classList.toggle('active', tab === range)); return renderUpcoming(); }
  const menu = event.target.closest('[data-menu]');
  if (menu) { const target = $(`#menu-${menu.dataset.menu}`); $$('.row-popover').forEach(pop => { if (pop !== target) pop.classList.add('hidden'); }); target.classList.toggle('hidden'); return; }
  const edit = event.target.closest('[data-edit]'); if (edit) { const doc = state.documents.find(d => d.id === Number(edit.dataset.edit)); if (doc) openDocumentForm(doc); return; }
  const renew = event.target.closest('[data-renew]'); if (renew) { const doc = state.documents.find(d => d.id === Number(renew.dataset.renew)); if (doc) openRenewForm(doc); return; }
  const del = event.target.closest('[data-delete]');
  if (del) {
    const doc = state.documents.find(d => d.id === Number(del.dataset.delete));
    if (doc && window.confirm(`Delete “${doc.name}”? Renewal history will remain saved.`)) {
      try { await request(`/api/documents/${doc.id}`, { method: 'DELETE' }); await loadData(); toast('Document deleted.'); }
      catch (err) { toast(err.message, true); }
    }
    return;
  }
  if (!event.target.closest('.row-menu-wrap')) $$('.row-popover').forEach(pop => pop.classList.add('hidden'));
});
$('#document-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = new FormData(event.currentTarget); const data = Object.fromEntries(form.entries());
  const issue = new Date(`${data.issue_date}T00:00:00`), expiry = new Date(`${data.expiry_date}T00:00:00`);
  if (expiry < issue) { $('#form-error').textContent = 'Expiry date cannot be earlier than issue date.'; $('#form-error').classList.remove('hidden'); return; }
  try {
    const isEdit = state.editingId !== null;
    await request(isEdit ? `/api/documents/${state.editingId}` : '/api/documents', { method: isEdit ? 'PUT' : 'POST', body: JSON.stringify(data) });
    $('#document-dialog').close(); await loadData(); toast(isEdit ? 'Document updated.' : 'Document added.');
  } catch (err) { $('#form-error').textContent = err.message; $('#form-error').classList.remove('hidden'); }
});
$('#renew-form').addEventListener('submit', async event => {
  event.preventDefault(); const issue = $('#renew-issue').value, expiry = $('#renew-expiry').value;
  if (expiry < issue) { $('#renew-error').textContent = 'Expiry date cannot be earlier than issue date.'; $('#renew-error').classList.remove('hidden'); return; }
  try {
    await request(`/api/documents/${state.renewingId}/renew`, { method: 'POST', body: JSON.stringify({ issue_date: issue, expiry_date: expiry }) });
    $('#renew-dialog').close(); await loadData(); toast('Renewal saved to history.');
  } catch (err) { $('#renew-error').textContent = err.message; $('#renew-error').classList.remove('hidden'); }
});
$('#renew-document-select').addEventListener('change', event => {
  const selected = state.documents.find(doc => doc.id === Number(event.target.value));
  if (!selected) return;
  state.renewingId = selected.id;
  $('#renew-document-name').textContent = `${selected.name} · Current expiry ${dateText(selected.expiry_date)}. The current dates will be saved in history.`;
});
let searchTimer;
$('#search-all').addEventListener('input', () => {
  clearTimeout(searchTimer);
  const term = $('#search-all').value.trim();
  if (!term) { state.searchResults = null; render(); return; }
  searchTimer = setTimeout(async () => {
    try {
      const result = await request(`/api/documents/search?q=${encodeURIComponent(term)}`);
      state.searchResults = result.items;
      render();
    } catch (err) { toast(err.message, true); }
  }, 180);
});
$('#status-filter-all').addEventListener('change', render);
$('#expiry-date').addEventListener('change', () => { $('#expiry-date').setCustomValidity($('#expiry-date').value && $('#issue-date').value && $('#expiry-date').value < $('#issue-date').value ? 'Expiry date cannot be earlier than issue date.' : ''); });
$('#issue-date').addEventListener('change', () => $('#expiry-date').dispatchEvent(new Event('change')));
$('#today-label').textContent = today.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
setView(location.hash.slice(1) || 'dashboard');
window.addEventListener('hashchange', () => setView(location.hash.slice(1) || 'dashboard'));
loadData();
