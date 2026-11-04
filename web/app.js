/**
 * Google Maps Scraper Pro & MongoDB Pipeline - Frontend Application
 * Vanilla JS logic for scraping jobs, live console, leads explorer, and CSV import.
 */

// Application State
const state = {
  activeTab: 'view-scrape',
  activeJobId: null,
  pollInterval: null,
  selectedProject: '',
  projects: [],
  leads: [],
  leadsTotal: 0,
  leadsSkip: 0,
  leadsLimit: 50,
  searchQuery: '',
  activeFilter: 'all',
  searchDebounceTimer: null,
  keywords: ['recruitment agency', 'staffing agency'],
  cities: ['Udaipur', 'Jaipur', 'Dubai, UAE'],
  ws: null,
  wsConnected: false,
  wsReconnectTimer: null,
  liveLeadCount: 0,
};

// DOM Elements
const elements = {
  // Navigation
  tabs: document.querySelectorAll('.nav-tab'),
  views: document.querySelectorAll('.view-panel'),
  headerTotalLeads: document.getElementById('header-total-leads'),

  // Status
  wsPill: document.getElementById('ws-status-pill'),
  wsText: document.getElementById('ws-status-text'),
  mongoPill: document.getElementById('mongo-status-pill'),
  mongoText: document.getElementById('mongo-status-text'),
  scraperPill: document.getElementById('scraper-status-pill'),
  scraperText: document.getElementById('scraper-status-text'),
  refreshStatusBtn: document.getElementById('refresh-status-btn'),

  // Scrape Form
  scrapeForm: document.getElementById('scrape-form'),
  inputProject: document.getElementById('input-project'),
  keywordsTagsList: document.getElementById('keywords-tags-list'),
  inputKeywordTag: document.getElementById('input-keyword-tag'),
  btnAddKeyword: document.getElementById('btn-add-keyword'),
  keywordsCountPill: document.getElementById('keywords-count-pill'),

  citiesTagsList: document.getElementById('cities-tags-list'),
  inputCityTag: document.getElementById('input-city-tag'),
  btnAddCity: document.getElementById('btn-add-city'),
  citiesCountPill: document.getElementById('cities-count-pill'),

  presetBtns: document.querySelectorAll('.preset-tag-btn'),
  inputDepth: document.getElementById('input-depth'),
  depthVal: document.getElementById('depth-val'),
  depthEst: document.getElementById('depth-est'),
  toggleFastmode: document.getElementById('toggle-fastmode'),
  queueCalcBadge: document.getElementById('queue-calc-badge'),
  queueCalcText: document.getElementById('queue-calc-text'),
  toggleEmails: document.getElementById('toggle-emails'),
  toggleSocials: document.getElementById('toggle-socials'),
  toggleSummary: document.getElementById('toggle-summary'),
  togglePeople: document.getElementById('toggle-people'),
  toggleCsv: document.getElementById('toggle-csv'),
  inputDb: document.getElementById('input-db'),
  inputCollection: document.getElementById('input-collection'),
  startScrapeBtn: document.getElementById('start-scrape-btn'),

  // Pipeline Monitor
  monitorSubtitle: document.getElementById('monitor-subtitle'),
  jobStatusBadge: document.getElementById('job-status-badge'),
  btnSkipQuery: document.getElementById('btn-skip-query'),
  btnStopScrape: document.getElementById('btn-stop-scrape'),
  batchStatusBar: document.getElementById('batch-status-bar'),
  batchCurrentQuery: document.getElementById('batch-current-query'),
  batchQueueProgress: document.getElementById('batch-queue-progress'),
  batchCumulativeLeads: document.getElementById('batch-cumulative-leads'),
  progressStepText: document.getElementById('progress-step-text'),
  progressPercentText: document.getElementById('progress-percent-text'),
  progressFill: document.getElementById('progress-fill'),
  terminalBody: document.getElementById('terminal-body'),
  clearLogsBtn: document.getElementById('clear-logs-btn'),
  jobSummaryCard: document.getElementById('job-summary-card'),
  metricTotalScraped: document.getElementById('metric-total-scraped'),
  metricNewInserted: document.getElementById('metric-new-inserted'),
  metricUpdated: document.getElementById('metric-updated'),
  metricTotalProject: document.getElementById('metric-total-project'),
  btnJumpToLeads: document.getElementById('btn-jump-to-leads'),

  // Live Streaming Feed
  liveLeadFeedCard: document.getElementById('live-lead-feed-card'),
  liveFeedBadge: document.getElementById('live-feed-badge'),
  liveFeedTotal: document.getElementById('live-feed-total'),
  liveFeedNew: document.getElementById('live-feed-new'),
  liveFeedMerged: document.getElementById('live-feed-merged'),
  liveFeedTbody: document.getElementById('live-feed-tbody'),

  // Stepper Items
  stepGeocode: document.getElementById('step-geocode'),
  stepEngine: document.getElementById('step-engine'),
  stepExtract: document.getElementById('step-extract'),
  stepEnrich: document.getElementById('step-enrich'),
  stepMongo: document.getElementById('step-mongo'),

  // Leads Explorer
  projectSelect: document.getElementById('project-select'),
  exportCsvBtn: document.getElementById('export-csv-btn'),
  leadSearchInput: document.getElementById('lead-search-input'),
  clearSearchBtn: document.getElementById('clear-search-btn'),
  filterPills: document.getElementById('filter-pills'),
  leadsTbody: document.getElementById('leads-tbody'),
  pageStart: document.getElementById('page-start'),
  pageEnd: document.getElementById('page-end'),
  pageTotal: document.getElementById('page-total'),
  currentPageDisplay: document.getElementById('current-page-display'),
  prevPageBtn: document.getElementById('prev-page-btn'),
  nextPageBtn: document.getElementById('next-page-btn'),

  // Stats Ribbon
  statTotalLeads: document.getElementById('stat-total-leads'),
  statEmailsCount: document.getElementById('stat-emails-count'),
  statEmailsPct: document.getElementById('stat-emails-pct'),
  statPhonesCount: document.getElementById('stat-phones-count'),
  statSocialsCount: document.getElementById('stat-socials-count'),

  // CSV Importer
  importCsvForm: document.getElementById('import-csv-form'),
  importProjectName: document.getElementById('import-project-name'),
  importFileSelect: document.getElementById('import-file-select'),
  btnRunImport: document.getElementById('btn-run-import'),
  importResultBanner: document.getElementById('import-result-banner'),

  // Modal & Toast
  leadModal: document.getElementById('lead-modal'),
  modalProjectBadge: document.getElementById('modal-project-badge'),
  modalLeadTitle: document.getElementById('modal-lead-title'),
  modalLeadBody: document.getElementById('modal-lead-body'),
  closeModalBtn: document.getElementById('close-modal-btn'),
  toastContainer: document.getElementById('toast-container'),
};

// ============================================================================
// Initialization
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
  renderKeywordsTags();
  renderCitiesTags();
  initEventListeners();
  checkSystemStatus();
  connectWebSocket();
  loadProjects();
  loadCsvFiles();
  updateQueueCalculation();
});

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function parseInputList(str) {
  if (!str) return [];
  // Split on commas, semicolons, newlines, or pipes
  return str
    .split(/[\n,;|\r]+/)
    .map(s => s.trim())
    .filter(s => s.length > 0);
}

// ----------------------------------------------------------------------------
// Tag / Chip Management for Keywords & Locations
// ----------------------------------------------------------------------------
function renderKeywordsTags() {
  if (!elements.keywordsTagsList) return;
  elements.keywordsTagsList.innerHTML = '';
  if (state.keywords.length === 0) {
    elements.keywordsTagsList.innerHTML = '<span class="tag-empty-hint">No keywords added yet (at least 1 required)</span>';
  } else {
    state.keywords.forEach((kw, idx) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip tag-chip-kw';
      chip.innerHTML = `
        <span class="tag-text">${escapeHtml(kw)}</span>
        <button type="button" class="tag-remove-btn" data-idx="${idx}" title="Remove keyword">&times;</button>
      `;
      chip.querySelector('.tag-remove-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        removeKeywordTag(idx);
      });
      elements.keywordsTagsList.appendChild(chip);
    });
  }
  if (elements.keywordsCountPill) {
    elements.keywordsCountPill.textContent = `${state.keywords.length} keyword${state.keywords.length === 1 ? '' : 's'}`;
  }
  updateQueueCalculation();
}

function renderCitiesTags() {
  if (!elements.citiesTagsList) return;
  elements.citiesTagsList.innerHTML = '';
  if (state.cities.length === 0) {
    elements.citiesTagsList.innerHTML = '<span class="tag-empty-hint">Global search (add cities to target specific locations)</span>';
  } else {
    state.cities.forEach((city, idx) => {
      const chip = document.createElement('span');
      chip.className = 'tag-chip tag-chip-city';
      chip.innerHTML = `
        <span class="tag-text">${escapeHtml(city)}</span>
        <button type="button" class="tag-remove-btn" data-idx="${idx}" title="Remove location">&times;</button>
      `;
      chip.querySelector('.tag-remove-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        removeCityTag(idx);
      });
      elements.citiesTagsList.appendChild(chip);
    });
  }
  if (elements.citiesCountPill) {
    elements.citiesCountPill.textContent = `${state.cities.length} location${state.cities.length === 1 ? '' : 's'}`;
  }
  updateQueueCalculation();
}

function addKeywordTag(rawText) {
  if (!rawText) return;
  const items = parseInputList(rawText);
  items.forEach(item => {
    if (!state.keywords.some(k => k.toLowerCase() === item.toLowerCase())) {
      state.keywords.push(item);
    }
  });
  if (elements.inputKeywordTag) elements.inputKeywordTag.value = '';
  renderKeywordsTags();
}

function removeKeywordTag(idx) {
  state.keywords.splice(idx, 1);
  renderKeywordsTags();
}

function addCityTag(rawText) {
  if (!rawText) return;
  const items = parseInputList(rawText);
  items.forEach(item => {
    if (!state.cities.some(c => c.toLowerCase() === item.toLowerCase())) {
      state.cities.push(item);
    }
  });
  if (elements.inputCityTag) elements.inputCityTag.value = '';
  renderCitiesTags();
}

function removeCityTag(idx) {
  state.cities.splice(idx, 1);
  renderCitiesTags();
}

function updateQueueCalculation() {
  if (!elements.queueCalcText) return;
  const numKws = state.keywords.length;
  const numLocs = state.cities.length > 0 ? state.cities.length : 1;
  const total = numKws * numLocs;
  if (numKws === 0) {
    elements.queueCalcText.textContent = `Batch Queue: Add at least 1 keyword to start`;
  } else {
    const locText = state.cities.length > 0 ? `${state.cities.length} location(s)` : `1 global search`;
    elements.queueCalcText.textContent = `Batch Queue: ${numKws} keyword(s) × ${locText} = ${total} total search queries to scrape`;
  }
}

function initEventListeners() {
  // Navigation Tabs
  elements.tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.target;
      switchTab(targetId);
    });
  });

  // Status Refresh
  elements.refreshStatusBtn.addEventListener('click', () => {
    checkSystemStatus();
    loadProjects();
  });

  // Tag Input: Keywords
  if (elements.inputKeywordTag) {
    elements.inputKeywordTag.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        addKeywordTag(elements.inputKeywordTag.value);
      }
    });
    elements.inputKeywordTag.addEventListener('paste', (e) => {
      setTimeout(() => {
        addKeywordTag(elements.inputKeywordTag.value);
      }, 50);
    });
    elements.inputKeywordTag.addEventListener('blur', () => {
      if (elements.inputKeywordTag.value.trim()) {
        addKeywordTag(elements.inputKeywordTag.value);
      }
    });
  }

  if (elements.btnAddKeyword) {
    elements.btnAddKeyword.addEventListener('click', () => {
      addKeywordTag(elements.inputKeywordTag.value);
    });
  }

  // Tag Input: Cities
  if (elements.inputCityTag) {
    elements.inputCityTag.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        addCityTag(elements.inputCityTag.value);
      }
    });
    elements.inputCityTag.addEventListener('paste', (e) => {
      setTimeout(() => {
        addCityTag(elements.inputCityTag.value);
      }, 50);
    });
    elements.inputCityTag.addEventListener('blur', () => {
      if (elements.inputCityTag.value.trim()) {
        addCityTag(elements.inputCityTag.value);
      }
    });
  }

  if (elements.btnAddCity) {
    elements.btnAddCity.addEventListener('click', () => {
      addCityTag(elements.inputCityTag.value);
    });
  }

  // Quick Preset Buttons
  if (elements.presetBtns) {
    elements.presetBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        const val = btn.dataset.val;
        if (type === 'kw') {
          addKeywordTag(val);
        } else {
          addCityTag(val);
        }
      });
    });
  }

  // Depth Slider
  elements.inputDepth.addEventListener('input', (e) => {
    const val = parseInt(e.target.value, 10);
    elements.depthVal.textContent = val;
    elements.depthEst.textContent = val * 20;
  });

  // Scrape Form Submit
  elements.scrapeForm.addEventListener('submit', handleStartScrape);

  // Skip Current Query
  if (elements.btnSkipQuery) {
    elements.btnSkipQuery.addEventListener('click', async () => {
      if (!state.activeJobId) return;
      elements.btnSkipQuery.disabled = true;
      showToast('Advancing to next search query in queue...', 'info');
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ action: 'skip_query', job_id: state.activeJobId }));
      }
      try {
        await fetch('/api/scrape/skip-query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: state.activeJobId }),
        });
      } catch (err) {
        console.error(err);
      } finally {
        setTimeout(() => { elements.btnSkipQuery.disabled = false; }, 2000);
      }
    });
  }

  // Stop Scrape
  if (elements.btnStopScrape) {
    elements.btnStopScrape.addEventListener('click', async () => {
      if (!state.activeJobId) return;
      elements.btnStopScrape.disabled = true;
      showToast('Stopping pipeline and preserving all scraped leads...', 'warn');
      if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ action: 'stop_scrape', job_id: state.activeJobId }));
      }
      try {
        await fetch('/api/scrape/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: state.activeJobId }),
        });
      } catch (err) {
        console.error(err);
      }
    });
  }

  // Clear Logs
  elements.clearLogsBtn.addEventListener('click', () => {
    elements.terminalBody.innerHTML = '';
  });

  // Jump to Leads button
  elements.btnJumpToLeads.addEventListener('click', () => {
    switchTab('view-leads');
    if (elements.inputProject.value.trim()) {
      elements.projectSelect.value = elements.inputProject.value.trim();
      state.selectedProject = elements.inputProject.value.trim();
      loadLeads();
    }
  });

  // Project Selector Change
  elements.projectSelect.addEventListener('change', (e) => {
    state.selectedProject = e.target.value;
    state.leadsSkip = 0;
    updateProjectStatsRibbon();
    loadLeads();
  });

  // Search Input with Debounce
  elements.leadSearchInput.addEventListener('input', (e) => {
    const query = e.target.value.trim();
    state.searchQuery = query;
    elements.clearSearchBtn.classList.toggle('hidden', query.length === 0);

    clearTimeout(state.searchDebounceTimer);
    state.searchDebounceTimer = setTimeout(() => {
      state.leadsSkip = 0;
      loadLeads();
    }, 300);
  });

  elements.clearSearchBtn.addEventListener('click', () => {
    elements.leadSearchInput.value = '';
    state.searchQuery = '';
    elements.clearSearchBtn.classList.add('hidden');
    state.leadsSkip = 0;
    loadLeads();
  });

  // Filter Pills
  elements.filterPills.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      elements.filterPills.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.activeFilter = pill.dataset.filter;
      state.leadsSkip = 0;
      loadLeads();
    });
  });

  // Pagination
  elements.prevPageBtn.addEventListener('click', () => {
    if (state.leadsSkip >= state.leadsLimit) {
      state.leadsSkip -= state.leadsLimit;
      loadLeads();
    }
  });

  elements.nextPageBtn.addEventListener('click', () => {
    if (state.leadsSkip + state.leadsLimit < state.leadsTotal) {
      state.leadsSkip += state.leadsLimit;
      loadLeads();
    }
  });

  // Export to CSV
  elements.exportCsvBtn.addEventListener('click', () => {
    if (!state.selectedProject) {
      showToast('Select a project first to export leads.', 'warn');
      return;
    }
    const exportUrl = `/api/export-csv?project=${encodeURIComponent(state.selectedProject)}`;
    window.open(exportUrl, '_blank');
    showToast(`Downloading CSV for '${state.selectedProject}'...`, 'success');
  });

  // CSV Importer Form
  elements.importCsvForm.addEventListener('submit', handleImportCsv);

  // Modal Close
  elements.closeModalBtn.addEventListener('click', closeModal);
  elements.leadModal.addEventListener('click', (e) => {
    if (e.target === elements.leadModal) closeModal();
  });
}

// ============================================================================
// Tab Management
// ============================================================================
function switchTab(viewId) {
  elements.tabs.forEach(tab => {
    tab.classList.toggle('active', tab.dataset.target === viewId);
  });
  elements.views.forEach(view => {
    view.classList.toggle('active', view.id === viewId);
  });
  state.activeTab = viewId;

  if (viewId === 'view-leads') {
    loadProjects();
    loadLeads();
  } else if (viewId === 'view-import') {
    loadCsvFiles();
  }
}

// ============================================================================
// System Status Checker
// ============================================================================
async function checkSystemStatus() {
  elements.mongoPill.className = 'status-pill status-loading';
  elements.mongoText.textContent = 'Connecting...';
  elements.scraperPill.className = 'status-pill status-loading';
  elements.scraperText.textContent = 'Checking...';

  try {
    const res = await fetch('/api/status');
    const data = await res.json();

    // MongoDB
    if (data.mongo_connected) {
      elements.mongoPill.className = 'status-pill status-online';
      elements.mongoText.textContent = 'Atlas Connected';
      elements.mongoPill.title = data.mongo_message || 'MongoDB Atlas Connected';
    } else {
      elements.mongoPill.className = 'status-pill status-offline';
      elements.mongoText.textContent = 'Disconnected';
      elements.mongoPill.title = data.mongo_message || 'Could not connect to MongoDB';
    }

    // Scraper Engine
    if (data.scraper_connected) {
      elements.scraperPill.className = 'status-pill status-online';
      elements.scraperText.textContent = 'Docker Active';
      elements.scraperPill.title = `Scraper engine ready at ${data.scraper_url}`;
    } else {
      elements.scraperPill.className = 'status-pill status-offline';
      elements.scraperText.textContent = 'Engine Offline';
      elements.scraperPill.title = `Scraper at ${data.scraper_url} not responding. Start with 'docker compose up -d'`;
    }
  } catch (err) {
    elements.mongoPill.className = 'status-pill status-offline';
    elements.mongoText.textContent = 'Error';
    elements.scraperPill.className = 'status-pill status-offline';
    elements.scraperText.textContent = 'Error';
  }
}

// ============================================================================
// Real-Time WebSocket Streaming Client (Port 5051)
// ============================================================================
function connectWebSocket() {
  if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const host = window.location.hostname || 'localhost';
  const wsUrl = `ws://${host}:5051`;

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      state.wsConnected = true;
      if (elements.wsPill) {
        elements.wsPill.className = 'status-pill status-online';
        elements.wsText.textContent = 'Active (5051)';
        elements.wsPill.title = 'Real-time WebSocket streaming connected on port 5051';
      }
      console.log('⚡ WebSocket connected to', wsUrl);
      if (state.activeJobId) {
        state.ws.send(JSON.stringify({ action: 'subscribe', job_id: state.activeJobId }));
      }
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWsMessage(msg);
      } catch (e) {
        console.error('WS message error:', e);
      }
    };

    state.ws.onerror = (err) => {
      // Handled via onclose
    };

    state.ws.onclose = () => {
      state.wsConnected = false;
      if (elements.wsPill) {
        elements.wsPill.className = 'status-pill status-offline';
        elements.wsText.textContent = 'Disconnected';
        elements.wsPill.title = 'WebSocket disconnected. Auto-reconnecting...';
      }
      if (state.wsReconnectTimer) clearTimeout(state.wsReconnectTimer);
      state.wsReconnectTimer = setTimeout(connectWebSocket, 2500);
    };
  } catch (err) {
    state.wsConnected = false;
    if (elements.wsPill) {
      elements.wsPill.className = 'status-pill status-offline';
      elements.wsText.textContent = 'Offline';
    }
    if (state.wsReconnectTimer) clearTimeout(state.wsReconnectTimer);
    state.wsReconnectTimer = setTimeout(connectWebSocket, 3000);
  }
}

function handleWsMessage(msg) {
  if (!msg || !msg.type) return;

  switch (msg.type) {
    case 'connected':
      console.log('⚡ WebSocket server online:', msg.msg);
      break;

    case 'progress':
      updateJobProgress(msg);
      break;

    case 'log':
      appendTerminalLine(`[${msg.time}] ${msg.msg}`, msg.level || 'info');
      break;

    case 'leads_batch':
      appendLeadsToLiveFeed(msg.leads, msg.new_count || 0, msg.merged_count || 0, msg.cumulative_unique || 0);
      break;

    case 'query_complete':
      if (msg.query_info) {
        appendTerminalLine(`[${msg.query_info.timestamp}] Batch: Query '${msg.query_info.keyword}' in '${msg.query_info.city}' done (+${msg.query_info.new_unique} new, ${msg.query_info.merged} merged | ${msg.cumulative_leads} total)`, 'success');
      }
      break;

    case 'job_complete':
      onJobFinished(msg);
      break;
  }
}

function appendLeadsToLiveFeed(leads, newCount = 0, mergedCount = 0, cumulativeTotal = 0) {
  if (!leads || !Array.isArray(leads) || leads.length === 0) return;

  if (elements.liveLeadFeedCard) {
    elements.liveLeadFeedCard.classList.remove('hidden');
  }

  if (elements.liveFeedTotal && cumulativeTotal) {
    elements.liveFeedTotal.textContent = cumulativeTotal;
  }
  if (elements.liveFeedNew) {
    const cur = parseInt(elements.liveFeedNew.textContent || '0', 10);
    elements.liveFeedNew.textContent = cur + newCount;
  }
  if (elements.liveFeedMerged) {
    const cur = parseInt(elements.liveFeedMerged.textContent || '0', 10);
    elements.liveFeedMerged.textContent = cur + mergedCount;
  }

  leads.forEach((lead) => {
    state.liveLeadCount++;
    const row = createLiveFeedRow(lead, state.liveLeadCount);
    row.classList.add('lead-row-animate');
    elements.liveFeedTbody.appendChild(row);
  });

  // Auto-scroll to show latest streaming leads
  if (elements.liveFeedTbody && elements.liveFeedTbody.parentElement) {
    elements.liveFeedTbody.parentElement.scrollTop = elements.liveFeedTbody.parentElement.scrollHeight;
  }
}

function createLiveFeedRow(lead, idx) {
  const row = document.createElement('tr');
  const title = lead.title || lead.name || 'Untitled';
  const website = lead.website || lead.site || lead.link || '';
  const phone = lead.phone || lead.phone_number || '';
  const emails = lead.emails || '';
  const category = lead.category || lead.type || '—';
  const address = lead.address || lead.city || '—';
  const kw = lead.search_keyword || '';
  const city = lead.search_city || '';
  const source = kw ? (city ? `${kw} (${city})` : kw) : 'Maps';
  const isMerged = (Array.isArray(lead.matched_keywords) && lead.matched_keywords.length > 1);

  const phoneHtml = phone ? `<div><a href="tel:${escapeHtml(phone)}" class="contact-link" style="font-size:0.75rem;">📞 ${escapeHtml(phone)}</a></div>` : '';
  const emailHtml = emails ? `<span class="email-pill" style="font-size:0.7rem; padding:1px 5px;">✉ ${escapeHtml(emails.split(',')[0].trim())}</span>` : '';
  const contactHtml = (phoneHtml || emailHtml) ? `${phoneHtml}${emailHtml}` : '<span style="color:var(--text-dim)">—</span>';

  const statusHtml = isMerged
    ? `<span class="lead-status-pill merged">🔄 MERGED</span>`
    : `<span class="lead-status-pill new">🟢 NEW</span>`;

  row.innerHTML = `
    <td style="color:var(--text-dim); font-size:0.72rem; font-family:var(--font-mono);">${idx}</td>
    <td>
      <div style="font-weight:600; color:var(--text-main); font-size:0.82rem;">${escapeHtml(truncate(title, 32))}</div>
      ${website ? `<a href="${website}" target="_blank" style="font-size:0.7rem; color:var(--accent-cyan); display:inline-flex; align-items:center; gap:3px;">${escapeHtml(truncate(website, 28))} <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg></a>` : ''}
    </td>
    <td>${contactHtml}</td>
    <td>
      <div style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(truncate(category, 24))}</div>
      <div style="font-size:0.72rem; color:var(--text-dim);">${escapeHtml(truncate(address, 28))}</div>
    </td>
    <td>
      <span class="badge badge-secondary" style="font-size:0.68rem; padding:2px 6px;">${escapeHtml(truncate(source, 22))}</span>
    </td>
    <td>${statusHtml}</td>
  `;
  return row;
}

// ============================================================================
// Scraper Pipeline Execution
// ============================================================================
async function handleStartScrape(e) {
  e.preventDefault();

  const projectName = elements.inputProject.value.trim();

  // If user left untagged text in the inputs, add them before starting
  if (elements.inputKeywordTag && elements.inputKeywordTag.value.trim()) {
    addKeywordTag(elements.inputKeywordTag.value);
  }
  if (elements.inputCityTag && elements.inputCityTag.value.trim()) {
    addCityTag(elements.inputCityTag.value);
  }

  if (!projectName) {
    showToast('Project Name is required so all leads are properly categorized!', 'error');
    elements.inputProject.focus();
    return;
  }
  if (state.keywords.length === 0) {
    showToast('Please add at least one Search Title / Keyword tag!', 'error');
    if (elements.inputKeywordTag) elements.inputKeywordTag.focus();
    return;
  }

  const payload = {
    project_name: projectName,
    keywords: state.keywords,
    cities: state.cities,
    depth: parseInt(elements.inputDepth.value, 10),
    fast_mode: elements.toggleFastmode ? elements.toggleFastmode.checked : true,
    extract_emails: elements.toggleEmails.checked,
    extract_socials: elements.toggleSocials.checked,
    extract_summary: elements.toggleSummary.checked,
    extract_people: elements.togglePeople ? elements.togglePeople.checked : true,
    save_csv: elements.toggleCsv.checked,
    db_name: elements.inputDb.value.trim() || 'scraper',
    collection_name: elements.inputCollection.value.trim() || 'leads',
  };

  // Reset Monitor
  resetPipelineUI(projectName);
  elements.startScrapeBtn.disabled = true;
  elements.startScrapeBtn.innerHTML = '<div class="spinner" style="width:16px;height:16px;"></div> <span>Launching Batch...</span>';

  try {
    const res = await fetch('/api/scrape/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to start scrape pipeline');
    }

    state.activeJobId = data.job_id;
    showToast(`Batch scraper launched (${data.total_queries || 1} queries) for project '${projectName}'!`, 'success');
    elements.jobStatusBadge.className = 'badge badge-running';
    elements.jobStatusBadge.textContent = 'Running';

    // Subscribe immediately via WebSocket if open
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ action: 'subscribe', job_id: data.job_id }));
    }

    // Start live polling as resilient background fallback
    startPollingJob(data.job_id);

  } catch (err) {
    showToast(err.message, 'error');
    appendTerminalLine(`[Error] ${err.message}`, 'error');
    elements.startScrapeBtn.disabled = false;
    elements.startScrapeBtn.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> <span>Launch Scraping Pipeline</span>';
  }
}

function resetPipelineUI(project) {
  const kws = state.keywords;
  const locs = state.cities;
  const total = kws.length * Math.max(1, locs.length);
  elements.monitorSubtitle.textContent = `Project: ${project} • Batch Queue: ${total} queries (${kws.length} KWs × ${locs.length || 1} Locs)`;
  elements.progressFill.style.width = '0%';
  elements.progressStepText.textContent = 'Initializing batch queue...';
  elements.progressPercentText.textContent = '0%';
  elements.terminalBody.innerHTML = '';
  elements.jobSummaryCard.classList.add('hidden');

  // Reset Live Feed UI
  if (elements.liveLeadFeedCard) elements.liveLeadFeedCard.classList.add('hidden');
  if (elements.liveFeedTbody) elements.liveFeedTbody.innerHTML = '';
  if (elements.liveFeedTotal) elements.liveFeedTotal.textContent = '0';
  if (elements.liveFeedNew) elements.liveFeedNew.textContent = '0';
  if (elements.liveFeedMerged) elements.liveFeedMerged.textContent = '0';
  state.liveLeadCount = 0;

  if (elements.btnSkipQuery) elements.btnSkipQuery.classList.remove('hidden');
  if (elements.btnStopScrape) elements.btnStopScrape.classList.remove('hidden');
  if (elements.batchStatusBar) elements.batchStatusBar.classList.remove('hidden');
  if (elements.batchCurrentQuery) elements.batchCurrentQuery.textContent = 'Starting...';
  if (elements.batchQueueProgress) elements.batchQueueProgress.textContent = `0 of ${total} queries`;
  if (elements.batchCumulativeLeads) elements.batchCumulativeLeads.textContent = '0';

  [elements.stepGeocode, elements.stepEngine, elements.stepExtract, elements.stepEnrich, elements.stepMongo].forEach(step => {
    step.className = 'step-item';
  });
}

function startPollingJob(jobId) {
  if (state.pollInterval) clearInterval(state.pollInterval);

  state.pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/scrape/status?job_id=${encodeURIComponent(jobId)}`);
      if (!res.ok) return;

      const job = await res.json();
      updateJobProgress(job);

      if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        onJobFinished(job);
      }
    } catch (err) {
      console.error('Poll error:', err);
    }
  }, 2000);
}

function updateJobProgress(job) {
  elements.progressFill.style.width = `${job.progress || 0}%`;
  elements.progressPercentText.textContent = `${job.progress || 0}%`;
  elements.progressStepText.textContent = job.step || 'Processing...';

  // Update Batch Status Bar
  if (job.current_query_label && elements.batchCurrentQuery) {
    elements.batchCurrentQuery.textContent = job.current_query_label;
  }
  if (job.total_queries && elements.batchQueueProgress) {
    elements.batchQueueProgress.textContent = `Query ${job.current_query_index || 1} of ${job.total_queries}`;
    elements.jobStatusBadge.className = 'badge badge-running';
    elements.jobStatusBadge.textContent = job.total_queries > 1 ? `Running (${job.current_query_index || 1}/${job.total_queries})` : 'Running';
  }
  if (job.cumulative_leads !== undefined && elements.batchCumulativeLeads) {
    elements.batchCumulativeLeads.textContent = job.cumulative_leads;
  }

  // Update Stepper
  const pct = job.progress || 0;
  setStepState(elements.stepGeocode, pct >= 10, pct > 20);
  setStepState(elements.stepEngine, pct >= 25, pct > 35);
  setStepState(elements.stepExtract, pct >= 35, pct > 75);
  setStepState(elements.stepEnrich, pct >= 80, pct > 88);
  setStepState(elements.stepMongo, pct >= 90, pct >= 100);

  // Update Terminal Logs (fallback to bulk log array only if WebSocket is not connected)
  if (job.logs && job.logs.length > 0 && (!state.wsConnected || elements.terminalBody.children.length === 0)) {
    elements.terminalBody.innerHTML = '';
    job.logs.forEach(log => {
      appendTerminalLine(`[${log.time}] ${log.msg}`, log.level || 'info');
    });
  }
}

function setStepState(element, active, done) {
  if (done) {
    element.className = 'step-item done';
  } else if (active) {
    element.className = 'step-item active';
  } else {
    element.className = 'step-item';
  }
}

function appendTerminalLine(text, level = 'info') {
  const line = document.createElement('div');
  line.className = `term-line ${level}`;
  line.textContent = text;
  elements.terminalBody.appendChild(line);
  elements.terminalBody.scrollTop = elements.terminalBody.scrollHeight;
}

function onJobFinished(job) {
  elements.startScrapeBtn.disabled = false;
  elements.startScrapeBtn.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="5 3 19 12 5 21 5 3"/>
    </svg>
    <span>Launch Scraping Pipeline</span>
  `;

  if (elements.btnSkipQuery) elements.btnSkipQuery.classList.add('hidden');
  if (elements.btnStopScrape) elements.btnStopScrape.classList.add('hidden');

  if (job.status === 'completed') {
    elements.jobStatusBadge.className = 'badge badge-completed';
    elements.jobStatusBadge.textContent = 'Completed';
    showToast(`Batch completed! All leads successfully saved into MongoDB Atlas.`, 'success');

    // Show summary card
    if (job.results_summary) {
      elements.metricTotalScraped.textContent = job.results_summary.total_scraped || 0;
      elements.metricNewInserted.textContent = job.results_summary.inserted || 0;
      elements.metricUpdated.textContent = job.results_summary.updated || 0;
      elements.metricTotalProject.textContent = job.results_summary.total_in_project || 0;
      elements.jobSummaryCard.classList.remove('hidden');
    }
    loadProjects();
    updateProjectStatsRibbon();
  } else if (job.status === 'cancelled') {
    elements.jobStatusBadge.className = 'badge badge-warn';
    elements.jobStatusBadge.textContent = 'Stopped';
    showToast(`Scraper stopped. Preserved ${job.cumulative_leads || 0} leads in MongoDB Atlas.`, 'info');
    if (job.results_summary) {
      elements.metricTotalScraped.textContent = job.results_summary.total_scraped || 0;
      elements.metricNewInserted.textContent = job.results_summary.inserted || 0;
      elements.metricUpdated.textContent = job.results_summary.updated || 0;
      elements.metricTotalProject.textContent = job.results_summary.total_in_project || 0;
      elements.jobSummaryCard.classList.remove('hidden');
    }
    loadProjects();
    updateProjectStatsRibbon();
  } else {
    elements.jobStatusBadge.className = 'badge badge-failed';
    elements.jobStatusBadge.textContent = 'Failed';
    showToast(job.error || 'Scrape pipeline encountered an issue. See execution log.', 'error');
  }
}

// ============================================================================
// MongoDB Projects & Leads Explorer
// ============================================================================
async function loadProjects() {
  try {
    const res = await fetch('/api/projects');
    const data = await res.json();
    state.projects = data.projects || [];

    // Header counter
    const totalAcross = state.projects.reduce((acc, p) => acc + (p.lead_count || 0), 0);
    elements.headerTotalLeads.textContent = totalAcross;

    // Populate dropdown
    const currentVal = elements.projectSelect.value || state.selectedProject;
    elements.projectSelect.innerHTML = '';

    if (state.projects.length === 0) {
      elements.projectSelect.innerHTML = '<option value="">No projects in database yet</option>';
      return;
    }

    state.projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.project_name;
      opt.textContent = `${p.project_name} (${p.lead_count} leads)`;
      elements.projectSelect.appendChild(opt);
    });

    if (currentVal && state.projects.some(p => p.project_name === currentVal)) {
      elements.projectSelect.value = currentVal;
      state.selectedProject = currentVal;
    } else {
      elements.projectSelect.value = state.projects[0].project_name;
      state.selectedProject = state.projects[0].project_name;
    }

    updateProjectStatsRibbon();
    loadLeads();
  } catch (err) {
    console.error('Failed to load projects:', err);
  }
}

function updateProjectStatsRibbon() {
  const proj = state.projects.find(p => p.project_name === state.selectedProject);
  if (!proj) {
    elements.statTotalLeads.textContent = '0';
    elements.statEmailsCount.textContent = '0';
    elements.statEmailsPct.textContent = '0%';
    elements.statPhonesCount.textContent = '0';
    elements.statSocialsCount.textContent = '0';
    return;
  }

  const total = proj.lead_count || 0;
  const emails = proj.has_emails || 0;
  const phones = proj.has_phone || 0;
  const socials = proj.has_socials || 0;
  const pct = total > 0 ? Math.round((emails / total) * 100) : 0;

  elements.statTotalLeads.textContent = total;
  elements.statEmailsCount.textContent = emails;
  elements.statEmailsPct.textContent = `${pct}%`;
  elements.statPhonesCount.textContent = phones;
  elements.statSocialsCount.textContent = socials;
}

async function loadLeads() {
  if (!state.selectedProject) {
    renderEmptyState('Please select or create a project first.');
    return;
  }

  elements.leadsTbody.innerHTML = `
    <tr>
      <td colspan="9" class="empty-state">
        <div class="empty-state-inner">
          <div class="spinner"></div>
          <span>Loading leads for '${escapeHtml(state.selectedProject)}'...</span>
        </div>
      </td>
    </tr>
  `;

  try {
    const params = new URLSearchParams({
      project: state.selectedProject,
      search: state.searchQuery,
      limit: state.leadsLimit,
      skip: state.leadsSkip,
    });

    if (state.activeFilter === 'has_email') {
      params.append('has_email', 'true');
    } else if (state.activeFilter === 'has_socials') {
      params.append('has_socials', 'true');
    } else if (state.activeFilter === 'high_rating') {
      params.append('min_rating', '4.0');
    }

    const res = await fetch(`/api/leads?${params.toString()}`);
    const data = await res.json();

    state.leads = data.leads || [];
    state.leadsTotal = data.total || 0;

    renderLeadsTable();
    updatePaginationUI();
  } catch (err) {
    renderEmptyState(`Failed to load leads: ${err.message}`);
  }
}

function renderLeadsTable() {
  if (state.leads.length === 0) {
    renderEmptyState('No leads match the current filters.');
    return;
  }

  elements.leadsTbody.innerHTML = '';
  state.leads.forEach((lead, idx) => {
    const row = document.createElement('tr');
    const rowNum = state.leadsSkip + idx + 1;

    const title = lead.title || lead.name || 'Untitled';
    const website = lead.website || lead.site || lead.link || '';
    const category = lead.category || lead.type || '—';
    const rating = lead.review_rating || lead.rating || '';
    const reviews = lead.review_count || lead.reviews || '';
    const phone = lead.phone || lead.phone_number || '';
    const emails = lead.emails || '';
    const address = lead.address || '';
    const project = lead.project_name || state.selectedProject;
    const scrapedAt = lead.scraped_at || lead.created_at || '';
    const scrapedAtDisplay = scrapedAt ? `<span class="scraped-time-badge" title="${escapeHtml(String(scrapedAt))}">🕒 ${escapeHtml(String(scrapedAt).replace(' UTC', ''))}</span>` : '<span style="color:var(--text-dim)">—</span>';

    // Rating element
    let ratingHtml = '<span style="color:var(--text-dim)">—</span>';
    if (rating) {
      ratingHtml = `
        <span class="rating-pill">★ ${parseFloat(rating).toFixed(1)}</span>
        ${reviews ? `<span class="reviews-count">(${reviews})</span>` : ''}
      `;
    }

    // Title & Website
    const kws = Array.isArray(lead.matched_keywords) ? lead.matched_keywords : (lead.matched_keywords ? String(lead.matched_keywords).split(',').map(s=>s.trim()) : []);
    const kwBadge = kws.length > 1 ? `<span class="badge badge-secondary" style="font-size:0.68rem; padding:2px 6px; margin-top:3px; display:inline-block;" title="Matched across intents: ${escapeHtml(kws.join(', '))}">🎯 ${kws.length} matched topics</span>` : '';

    let dmBadge = '';
    if (lead.decision_makers && Array.isArray(lead.decision_makers) && lead.decision_makers.length > 0) {
      const dmNames = lead.decision_makers.map(d => `${d.name} (${d.role})`).join(' • ');
      dmBadge = `<span class="badge" style="background:rgba(52,211,153,0.15); color:#34d399; border:1px solid rgba(52,211,153,0.3); font-size:0.68rem; padding:2px 6px; margin-top:3px; display:inline-block;" title="${escapeHtml(dmNames)}">👔 ${lead.decision_makers.length} Verified Leader${lead.decision_makers.length > 1 ? 's' : ''}</span>`;
    }

    const titleHtml = `
      <div class="lead-title-cell">
        <a href="${website || '#'}" target="_blank" class="lead-title-link" title="${escapeHtml(title)}">
          ${escapeHtml(title)}
          ${website ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>` : ''}
        </a>
        ${website ? `<span class="lead-website-text">${truncate(website, 30)}</span>` : ''}
        ${kwBadge}
        ${dmBadge}
      </div>
    `;

    // Contact info
    const phoneHtml = phone ? `<a href="tel:${escapeHtml(phone)}" class="contact-link">📞 ${escapeHtml(phone)}</a>` : '';
    const emailHtml = emails ? `<span class="email-pill" title="${escapeHtml(emails)}">✉ ${escapeHtml(emails.split(',')[0].trim())}</span>` : '';
    const contactHtml = (phoneHtml || emailHtml) ? `<div class="contact-cell">${phoneHtml}${emailHtml}</div>` : '<span style="color:var(--text-dim)">—</span>';

    // Social Media Links
    const socialIcons = [];
    if (lead.instagram) socialIcons.push(`<a href="${escapeHtml(lead.instagram)}" target="_blank" class="social-icon-btn ig" title="Instagram">IG</a>`);
    if (lead.facebook) socialIcons.push(`<a href="${escapeHtml(lead.facebook)}" target="_blank" class="social-icon-btn fb" title="Facebook">FB</a>`);
    if (lead.linkedin) socialIcons.push(`<a href="${escapeHtml(lead.linkedin)}" target="_blank" class="social-icon-btn in" title="LinkedIn">IN</a>`);
    const socialsHtml = socialIcons.length > 0 ? `<div class="socials-cell">${socialIcons.join('')}</div>` : '<span style="color:var(--text-dim)">—</span>';

    row.innerHTML = `
      <td style="color:var(--text-dim); font-size:0.75rem;">${rowNum}</td>
      <td>${titleHtml}</td>
      <td><span class="badge badge-project">${escapeHtml(project)}</span></td>
      <td>${scrapedAtDisplay}</td>
      <td>${ratingHtml}</td>
      <td><span style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(truncate(category, 25))}</span></td>
      <td>${contactHtml}</td>
      <td>${socialsHtml}</td>
      <td><span style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(truncate(address, 35))}</span></td>
      <td style="text-align: right;">
        <button class="btn btn-sm btn-secondary view-lead-btn">Details</button>
      </td>
    `;

    row.querySelector('.view-lead-btn').addEventListener('click', () => {
      openLeadModal(lead);
    });

    elements.leadsTbody.appendChild(row);
  });
}

function renderEmptyState(message) {
  elements.leadsTbody.innerHTML = `
    <tr>
      <td colspan="9" class="empty-state">
        <div class="empty-state-inner">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="color:var(--text-dim);">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
            <line x1="12" y1="22.08" x2="12" y2="12"/>
          </svg>
          <span>${escapeHtml(message)}</span>
        </div>
      </td>
    </tr>
  `;
}

function updatePaginationUI() {
  const start = state.leadsTotal > 0 ? state.leadsSkip + 1 : 0;
  const end = Math.min(state.leadsSkip + state.leadsLimit, state.leadsTotal);
  elements.pageStart.textContent = start;
  elements.pageEnd.textContent = end;
  elements.pageTotal.textContent = state.leadsTotal;

  const currentPage = Math.floor(state.leadsSkip / state.leadsLimit) + 1;
  const totalPages = Math.ceil(state.leadsTotal / state.leadsLimit) || 1;
  elements.currentPageDisplay.textContent = `Page ${currentPage} of ${totalPages}`;

  elements.prevPageBtn.disabled = state.leadsSkip === 0;
  elements.nextPageBtn.disabled = state.leadsSkip + state.leadsLimit >= state.leadsTotal;
}

// ============================================================================
// CSV Importer
// ============================================================================
async function loadCsvFiles() {
  try {
    const res = await fetch('/api/csv-files');
    const data = await res.json();
    const files = data.files || [];

    elements.importFileSelect.innerHTML = '';
    if (files.length === 0) {
      elements.importFileSelect.innerHTML = '<option value="">No CSV files detected</option>';
      return;
    }

    files.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.filename;
      opt.textContent = `${f.filename} (${f.size_kb} KB)`;
      elements.importFileSelect.appendChild(opt);
    });
  } catch (err) {
    console.error('Failed to load CSV files:', err);
  }
}

async function handleImportCsv(e) {
  e.preventDefault();

  const projectName = elements.importProjectName.value.trim();
  const filename = elements.importFileSelect.value;

  if (!projectName) {
    showToast('Target Project Name is required!', 'error');
    elements.importProjectName.focus();
    return;
  }
  if (!filename) {
    showToast('Select a CSV file to import!', 'error');
    return;
  }

  elements.btnRunImport.disabled = true;
  elements.btnRunImport.innerHTML = '<div class="spinner" style="width:16px;height:16px;"></div> <span>Importing...</span>';
  elements.importResultBanner.className = 'import-result-banner hidden';

  try {
    const res = await fetch('/api/import-csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_name: projectName, filename: filename }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Failed to import CSV');
    }

    const stats = data.stats || {};
    elements.importResultBanner.className = 'import-result-banner text-success';
    elements.importResultBanner.innerHTML = `
      <strong>✓ Import Successful!</strong><br>
      Imported <strong>${stats.total_scraped || 0}</strong> leads under project <strong>'${escapeHtml(projectName)}'</strong>.<br>
      New added: ${stats.inserted || 0} | Updated: ${stats.updated || 0} | Total in Project: ${stats.total_in_project || 0}
    `;

    showToast(`Successfully imported ${stats.total_scraped || 0} leads into '${projectName}'!`, 'success');

    // Refresh projects and prepare lead view
    await loadProjects();
    state.selectedProject = projectName;
    elements.projectSelect.value = projectName;

  } catch (err) {
    elements.importResultBanner.className = 'import-result-banner text-warning';
    elements.importResultBanner.textContent = `Import error: ${err.message}`;
    showToast(err.message, 'error');
  } finally {
    elements.btnRunImport.disabled = false;
    elements.btnRunImport.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="7 10 12 15 17 10"/>
        <line x1="12" y1="15" x2="12" y2="3"/>
      </svg>
      <span>Import File into MongoDB</span>
    `;
  }
}

// ============================================================================
// Modal
// ============================================================================
function openLeadModal(lead) {
  elements.modalProjectBadge.textContent = lead.project_name || state.selectedProject;
  elements.modalLeadTitle.textContent = lead.title || lead.name || 'Lead Details';

  elements.modalLeadBody.innerHTML = '';

  const matchedKws = Array.isArray(lead.matched_keywords) ? lead.matched_keywords.join(', ') : (lead.matched_keywords || lead.search_keyword || '');
  const matchedCities = Array.isArray(lead.matched_cities) ? lead.matched_cities.join(', ') : (lead.matched_cities || lead.search_city || '');

  const displayFields = [
    { label: 'Business Name', val: lead.title || lead.name },
    { label: 'Project Name', val: lead.project_name },
    { label: 'Matched Topics/Keywords', val: matchedKws },
    { label: 'Matched Locations', val: matchedCities },
    { label: 'Lead Fingerprint', val: lead.lead_fingerprint },
    { label: 'Scraped At / Time', val: lead.scraped_at || lead.created_at },
    { label: 'Phone', val: lead.phone || lead.phone_number },
    { label: 'Emails', val: lead.emails },
    { label: 'Website', val: lead.website || lead.site || lead.link },
    { label: 'Category', val: lead.category },
    { label: 'Rating', val: lead.review_rating ? `${lead.review_rating} (${lead.review_count || 0} reviews)` : '' },
    { label: 'Address', val: lead.address },
    { label: 'Summary / Meta Description', val: lead.summary || lead.descriptions || lead.about },
    { label: 'Instagram', val: lead.instagram },
    { label: 'Facebook', val: lead.facebook },
    { label: 'LinkedIn', val: lead.linkedin },
  ];

  displayFields.forEach(f => {
    if (f.val) {
      const fieldDiv = document.createElement('div');
      fieldDiv.className = 'modal-field';
      fieldDiv.innerHTML = `
        <span class="modal-field-label">${escapeHtml(f.label)}</span>
        <div class="modal-field-value">${escapeHtml(String(f.val))}</div>
      `;
      elements.modalLeadBody.appendChild(fieldDiv);
    }
  });

  if (lead.decision_makers && Array.isArray(lead.decision_makers) && lead.decision_makers.length > 0) {
    const dmSection = document.createElement('div');
    dmSection.style.cssText = 'grid-column: 1 / -1; margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--border-color);';
    dmSection.innerHTML = `
      <h4 style="margin: 0 0 10px 0; color: #34d399; font-size: 0.95rem; display: flex; align-items: center; gap: 6px;">
        <span>👔</span> Verified Decision Makers (${lead.decision_makers.length})
      </h4>
      <div style="display: flex; flex-direction: column; gap: 10px;">
        ${lead.decision_makers.map(dm => `
          <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
              <div style="font-weight: 600; color: #fff; font-size: 0.95rem;">${escapeHtml(dm.name)}</div>
              <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                <span class="badge badge-primary" style="font-size: 0.7rem; padding: 2px 6px;">${escapeHtml(dm.role)}</span>
                ${dm.tier ? `<span style="font-size: 0.72rem; color: var(--text-dim);">${escapeHtml(dm.tier)}</span>` : ''}
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;">
              ${dm.email ? `
                <span style="background: rgba(52,211,153,0.15); color: #34d399; border: 1px solid rgba(52,211,153,0.3); border-radius: 6px; padding: 4px 8px; font-size: 0.8rem;" title="${escapeHtml(dm.email_status || 'Verified')}">
                  ✉ ${escapeHtml(dm.email)}
                </span>
              ` : `
                <span style="color: var(--text-dim); font-size: 0.75rem;">(No Verified Email)</span>
              `}
              ${dm.linkedin_url ? `
                <a href="${escapeHtml(dm.linkedin_url)}" target="_blank" class="social-icon-btn in" style="font-size: 0.75rem; text-decoration: none;" title="View LinkedIn Profile">IN</a>
              ` : ''}
              ${dm.confidence_score ? `
                <span style="font-size: 0.75rem; color: #34d399; font-weight: 600;" title="Confidence Score">${dm.confidence_score}%</span>
              ` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;
    elements.modalLeadBody.appendChild(dmSection);
  }

  elements.leadModal.classList.remove('hidden');
}

function closeModal() {
  elements.leadModal.classList.add('hidden');
}

// ============================================================================
// Toast Notification Utility
// ============================================================================
function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  elements.toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ============================================================================
// Helpers
// ============================================================================
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function truncate(str, max = 30) {
  if (!str) return '';
  return str.length > max ? str.substring(0, max) + '...' : str;
}
