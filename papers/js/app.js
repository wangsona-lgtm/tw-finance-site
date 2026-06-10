/* ===== papers/js/app.js — 論文文獻庫前端邏輯 ===== */

let allPapers = [];
let filteredPapers = [];
let currentTag = 'all';
let currentPage = 1;
const PER_PAGE = 20;

async function loadPapers() {
  try {
    const res = await fetch('papers.json?_=' + Date.now());
    const data = await res.json();
    allPapers = data.papers || [];
    document.getElementById('stat-total').textContent = allPapers.length;
    document.getElementById('stat-date').textContent = data.updated || '—';
    applyFilters();
  } catch (e) {
    document.getElementById('paperList').innerHTML = '<p style="text-align:center;color:var(--muted);padding:40px">⚠️ 論文資料載入失敗</p>';
  }
}

function applyFilters() {
  const q = document.getElementById('searchInput').value.toLowerCase().trim();
  
  filteredPapers = allPapers.filter(p => {
    // Tag filter
    if (currentTag !== 'all') {
      if (currentTag === 'upload') {
        if (p.type !== 'upload') return false;
      } else {
        if (!p.tags || !p.tags.includes(currentTag)) return false;
      }
    }
    
    // Search text
    if (q) {
      const text = (p.title + ' ' + p.authors + ' ' + p.journal + ' ' + p.abstract + ' ' + (p.tags||[]).join(' ')).toLowerCase();
      if (!text.includes(q)) return false;
    }
    
    return true;
  });
  
  currentPage = 1;
  render();
}

function render() {
  const total = filteredPapers.length;
  const totalPages = Math.ceil(total / PER_PAGE);
  const start = (currentPage - 1) * PER_PAGE;
  const pagePapers = filteredPapers.slice(start, start + PER_PAGE);
  
  const list = document.getElementById('paperList');
  
  if (pagePapers.length === 0) {
    list.innerHTML = '<p style="text-align:center;color:var(--muted);padding:60px 20px">📭 沒有符合的論文</p>';
    document.getElementById('pagination').innerHTML = '';
    return;
  }
  
  list.innerHTML = pagePapers.map(p => `
    <div class="paper-card" onclick="openModal('${p.id}')">
      <div class="paper-meta">
        <span class="paper-date">${p.search_date || p.date || ''}</span>
        ${p.type === 'upload' ? '<span class="paper-badge upload">📁 上傳</span>' : ''}
        ${p.year ? `<span>(${p.year})</span>` : ''}
      </div>
      <h3>${escapeHtml(p.title)}</h3>
      ${p.authors ? `<div class="paper-authors">${escapeHtml(p.authors)}</div>` : ''}
      ${p.journal ? `<div class="paper-journal">${escapeHtml(p.journal)}</div>` : ''}
      <div class="paper-tags">
        ${(p.tags||[]).map(t => `<span>${t}</span>`).join('')}
      </div>
    </div>
  `).join('');
  
  // Pagination
  if (totalPages <= 1) {
    document.getElementById('pagination').innerHTML = '';
    return;
  }
  
  let pgHtml = `<button ${currentPage <= 1 ? 'disabled' : ''} onclick="goPage(${currentPage - 1})">‹</button>`;
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || Math.abs(i - currentPage) <= 2) {
      pgHtml += `<button class="${i === currentPage ? 'active' : ''}" onclick="goPage(${i})">${i}</button>`;
    } else if (i === currentPage - 3 || i === currentPage + 3) {
      pgHtml += `<button disabled>…</button>`;
    }
  }
  pgHtml += `<button ${currentPage >= totalPages ? 'disabled' : ''} onclick="goPage(${currentPage + 1})">›</button>`;
  document.getElementById('pagination').innerHTML = pgHtml;
}

function goPage(n) {
  currentPage = n;
  render();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openModal(id) {
  const p = allPapers.find(x => x.id === id);
  if (!p) return;
  
  const body = document.getElementById('modalBody');
  body.innerHTML = `
    <h2>${escapeHtml(p.title)}</h2>
    ${p.authors ? `<div class="meta-line"><strong>作者</strong> ${escapeHtml(p.authors)}</div>` : ''}
    ${p.journal ? `<div class="meta-line"><strong>期刊</strong> ${escapeHtml(p.journal)}</div>` : ''}
    ${p.year ? `<div class="meta-line"><strong>年份</strong> ${p.year}</div>` : ''}
    ${p.search_date ? `<div class="meta-line"><strong>搜尋日期</strong> ${p.search_date}</div>` : ''}
    ${p.date ? `<div class="meta-line"><strong>上傳日期</strong> ${p.date}</div>` : ''}
    ${p.citations ? `<div class="meta-line"><strong>被引次數</strong> ${p.citations}</div>` : ''}
    <div class="tags">${(p.tags||[]).map(t => `<span>${t}</span>`).join('')}</div>
    ${p.abstract ? `
      <div class="section">
        <h4>📄 摘要</h4>
        <p>${escapeHtml(p.abstract)}</p>
      </div>
    ` : ''}
    ${p.doi ? `
      <div class="section">
        <h4>🔗 連結</h4>
        <p><a href="https://doi.org/${p.doi.replace('https://doi.org/','')}" target="_blank" rel="noopener">${p.doi}</a></p>
      </div>
    ` : ''}
    ${p.openalex_url ? `
      <p><a href="${p.openalex_url}" target="_blank" rel="noopener">📖 OpenAlex</a></p>
    ` : ''}
    ${p.pdf ? `
      <div class="section">
        <h4>📁 檔案</h4>
        <p><a href="${p.pdf}" target="_blank">📄 下載 PDF</a></p>
      </div>
    ` : ''}
    ${p.notes && p.notes.length > 0 ? `
      <div class="section">
        <h4>📝 筆記</h4>
        ${p.notes.map(n => `<p style="margin-top:4px">• ${escapeHtml(n)}</p>`).join('')}
      </div>
    ` : ''}
    ${p.type === 'upload' ? `<div class="section"><p style="font-size:12px;color:var(--muted)">📁 使用者上傳文章</p></div>` : ''}
  `;
  
  document.getElementById('paperModal').classList.add('open');
}

function closeModal() {
  document.getElementById('paperModal').classList.remove('open');
}

function escapeHtml(s) {
  if (!s) return '';
  s = String(s);
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  loadPapers();
  
  document.getElementById('searchInput').addEventListener('input', applyFilters);
  
  document.querySelectorAll('.filter-tags .tag').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-tags .tag').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTag = btn.dataset.tag;
      applyFilters();
    });
  });
  
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });
});
