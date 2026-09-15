/* ──────────────────────────────────────────────────────────────────────────
   LinkedIn Prospector — Dashboard JS
   ────────────────────────────────────────────────────────────────────────── */

// ── State ────────────────────────────────────────────────────────────────────
let allProspects = [];
let currentFilter = 'all';
let currentModal = null;

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  document.getElementById('search-query').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runSearch();
  });
});

async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    const badge = document.getElementById('mode-badge');

    if (data.mock_mode && !data.llm_enabled) {
      badge.textContent = 'MOCK + Rules';
      badge.className = 'mode-badge mock';
    } else if (data.mock_mode && data.llm_enabled) {
      badge.textContent = 'MOCK + Gemini';
      badge.className = 'mode-badge mock';
    } else if (!data.mock_mode && data.llm_enabled) {
      badge.textContent = 'LIVE + Gemini';
      badge.className = 'mode-badge live';
    } else {
      badge.textContent = 'LIVE + Rules';
      badge.className = 'mode-badge live';
    }
  } catch (e) {
    document.getElementById('mode-badge').textContent = 'API Offline';
  }
}

// ── Search / Pipeline ─────────────────────────────────────────────────────────
async function runSearch() {
  const query = document.getElementById('search-query').value.trim();
  if (!query) {
    shakeElement(document.getElementById('search-query'));
    return;
  }

  const maxResults = parseInt(document.getElementById('max-results').value);
  const country = document.getElementById('country').value;

  // Reset UI
  setLoading(true);
  clearResults();
  resetPipelineSteps();
  document.getElementById('search-btn').disabled = true;

  // Animate pipeline steps
  await animatePipelineStep('step-discover', 'Discovering profiles...');
  await animatePipelineStep('step-enrich', 'Enriching profiles...');
  await animatePipelineStep('step-qualify', 'Qualifying against ICP...');
  await animatePipelineStep('step-personalise', 'Generating outreach copy...');

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, max_results: maxResults, country }),
    });

    markAllPipelineDone();

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Pipeline failed');
    }

    const data = await res.json();
    allProspects = data.prospects || [];
    renderResults(allProspects);
    updateStats(allProspects);
    setLoading(false);
    showFilterBar();

  } catch (err) {
    setLoading(false);
    showError(err.message);
  } finally {
    document.getElementById('search-btn').disabled = false;
  }
}

// ── Pipeline step animation ───────────────────────────────────────────────────
function resetPipelineSteps() {
  ['step-discover', 'step-enrich', 'step-qualify', 'step-personalise'].forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove('active', 'done');
  });
}

async function animatePipelineStep(stepId, loadingText) {
  const el = document.getElementById(stepId);
  el.classList.add('active');
  document.getElementById('loading-text').textContent = loadingText;
  await sleep(320);
}

function markAllPipelineDone() {
  ['step-discover', 'step-enrich', 'step-qualify', 'step-personalise'].forEach(id => {
    const el = document.getElementById(id);
    el.classList.remove('active');
    el.classList.add('done');
  });
  document.getElementById('loading-text').textContent = 'Pipeline complete!';
}

// ── Render results ────────────────────────────────────────────────────────────
function renderResults(prospects) {
  const grid = document.getElementById('results-grid');
  grid.innerHTML = '';

  if (!prospects || prospects.length === 0) {
    document.getElementById('empty-state').classList.remove('hidden');
    return;
  }

  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('stats-bar').classList.remove('hidden');

  prospects.forEach((p, i) => {
    const card = buildProspectCard(p, i);
    grid.appendChild(card);
  });
}

function buildProspectCard(p, index) {
  const draft = p.outreach_draft || {};
  const label = p.fit_label || 'weak';
  const score = p.fit_score || 0;
  const initials = getInitials(p.full_name || '?');
  const avatarColor = getAvatarGradient(index);

  const card = document.createElement('div');
  card.className = `prospect-card ${label}`;
  card.style.animationDelay = `${index * 0.05}s`;
  card.setAttribute('data-fit-label', label);
  card.setAttribute('data-role-change', p.role_change_detected ? 'true' : 'false');
  card.onclick = () => openModal(p, draft);

  const scoreClass = label;
  const scorePct = Math.round(score * 100);

  const labelEmoji = { strong: '🟢', possible: '🟡', weak: '🔴' }[label] || '⚪';
  const fitText = { strong: 'Strong Fit', possible: 'Possible Fit', weak: 'Weak Fit' }[label] || label;

  card.innerHTML = `
    <div class="card-header">
      <div class="card-avatar" style="background: ${avatarColor}">${initials}</div>
      <div style="flex:1;min-width:0">
        <div class="card-name">${escHtml(p.full_name || 'Unknown')}</div>
        <div class="card-title-company">
          ${escHtml(p.current_title || '')}${p.current_company ? ` · ${escHtml(p.current_company)}` : ''}
        </div>
      </div>
    </div>
    <div class="card-badges">
      <span class="badge badge-${label}">${labelEmoji} ${fitText}</span>
      ${p.role_change_detected ? '<span class="badge badge-role-change">🔄 New Role</span>' : ''}
      ${p.industry ? `<span class="badge badge-industry">${escHtml(p.industry)}</span>` : ''}
      ${p.location ? `<span class="badge badge-location">📍 ${escHtml(p.location.split(',')[0])}</span>` : ''}
    </div>
    <div class="card-score-bar">
      <div class="score-row">
        <span class="score-label">ICP Fit Score</span>
        <span class="score-num ${scoreClass}">${scorePct}%</span>
      </div>
      <div class="score-bar-track">
        <div class="score-bar-fill ${scoreClass}" style="width:${scorePct}%"></div>
      </div>
    </div>
    ${p.recent_post_snippet ? `
    <div class="card-post-snippet">
      "${escHtml(p.recent_post_snippet.substring(0, 80))}${p.recent_post_snippet.length > 80 ? '...' : ''}"
    </div>` : ''}
    <div class="card-footer">
      <span class="card-cta">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        View Outreach Copy
      </span>
      <div style="display:flex;align-items:center;gap:6px">
        <div class="status-dot ${p.status || 'new'}"></div>
        <span style="font-size:11px;color:var(--text-muted)">${p.status || 'new'}</span>
      </div>
    </div>
  `;
  return card;
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openModal(prospect, draft) {
  currentModal = { prospect, draft };

  document.getElementById('modal-avatar').textContent = getInitials(prospect.full_name || '?');
  document.getElementById('modal-name').textContent = prospect.full_name || 'Unknown';
  document.getElementById('modal-title').textContent =
    `${prospect.current_title || ''}${prospect.current_company ? ' at ' + prospect.current_company : ''}`;

  // Connection note
  const note = draft.connection_note || '(No outreach draft available)';
  document.getElementById('connection-text').textContent = note;
  document.getElementById('connection-char-count').textContent = `${note.length}/300`;
  document.getElementById('connection-char-count').style.color =
    note.length > 280 ? 'var(--yellow)' : 'var(--text-muted)';

  // Follow-up DM
  document.getElementById('followup-text').textContent = draft.followup_dm || '(No follow-up draft available)';

  // Reasoning
  const score = prospect.fit_score || 0;
  const label = prospect.fit_label || 'weak';
  const reasoningScoreEl = document.getElementById('reasoning-score');
  reasoningScoreEl.textContent = `${Math.round(score * 100)}%`;
  reasoningScoreEl.style.color = { strong: 'var(--green)', possible: 'var(--yellow)', weak: 'var(--red)' }[label] || 'var(--text-secondary)';
  document.getElementById('reasoning-label').textContent = label;
  document.getElementById('reasoning-label').className = `fit-badge-large ${label}`;
  document.getElementById('reasoning-text').textContent = prospect.fit_reasoning || 'No reasoning available.';

  switchTab('connection');
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.add('hidden');
  document.body.style.overflow = '';
}

function switchTab(tab) {
  ['connection', 'followup', 'reasoning'].forEach(t => {
    document.getElementById(`tab-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`tab-${t}-content`).classList.toggle('hidden', t !== tab);
  });
}

function copyText(elementId) {
  const text = document.getElementById(elementId).textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✓ Copied!';
    btn.style.color = 'var(--green)';
    setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
  });
}

// ── Filter ────────────────────────────────────────────────────────────────────
function filterProspects(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  document.querySelectorAll('.prospect-card').forEach(card => {
    const label = card.getAttribute('data-fit-label');
    const roleChange = card.getAttribute('data-role-change') === 'true';
    let show = true;
    if (filter === 'all') show = true;
    else if (filter === 'role_change') show = roleChange;
    else show = label === filter;
    card.style.display = show ? '' : 'none';
  });
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function updateStats(prospects) {
  document.getElementById('stat-total').textContent = prospects.length;
  document.getElementById('stat-strong').textContent = prospects.filter(p => p.fit_label === 'strong').length;
  document.getElementById('stat-possible').textContent = prospects.filter(p => p.fit_label === 'possible').length;
  document.getElementById('stat-weak').textContent = prospects.filter(p => p.fit_label === 'weak').length;
  document.getElementById('stat-role-change').textContent = prospects.filter(p => p.role_change_detected).length;
}

// ── Export ────────────────────────────────────────────────────────────────────
async function exportCSV() {
  const url = '/api/export/csv';
  const a = document.createElement('a');
  a.href = url;
  a.download = 'linkedin_prospects.csv';
  a.click();
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function setLoading(show) {
  document.getElementById('loading').classList.toggle('hidden', !show);
  if (show) {
    document.getElementById('results-grid').innerHTML = '';
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('stats-bar').classList.add('hidden');
    document.getElementById('filter-bar').classList.add('hidden');
  }
}

function clearResults() {
  document.getElementById('results-grid').innerHTML = '';
  allProspects = [];
}

function showFilterBar() {
  document.getElementById('filter-bar').classList.remove('hidden');
}

function showError(message) {
  const grid = document.getElementById('results-grid');
  grid.innerHTML = `
    <div style="grid-column:1/-1;padding:40px;text-align:center;color:var(--red)">
      <div style="font-size:24px;margin-bottom:8px">⚠️</div>
      <div style="font-weight:600;margin-bottom:4px">Pipeline Error</div>
      <div style="font-size:13px;color:var(--text-muted)">${escHtml(message)}</div>
    </div>
  `;
  document.getElementById('empty-state').classList.add('hidden');
}

function shakeElement(el) {
  el.style.animation = 'none';
  el.offsetHeight;
  el.style.animation = 'shake 0.3s ease';
  el.addEventListener('animationend', () => { el.style.animation = ''; }, { once: true });
}

function getInitials(name) {
  return name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
}

function getAvatarGradient(index) {
  const gradients = [
    'linear-gradient(135deg, #6394ff, #a78bfa)',
    'linear-gradient(135deg, #22c55e, #16a34a)',
    'linear-gradient(135deg, #f59e0b, #d97706)',
    'linear-gradient(135deg, #ef4444, #dc2626)',
    'linear-gradient(135deg, #06b6d4, #0891b2)',
    'linear-gradient(135deg, #ec4899, #db2777)',
    'linear-gradient(135deg, #84cc16, #65a30d)',
    'linear-gradient(135deg, #f97316, #ea580c)',
  ];
  return gradients[index % gradients.length];
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.body.style.overflow = '';
  }
});
