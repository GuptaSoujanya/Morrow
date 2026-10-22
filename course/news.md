# Live AI & Tech News

This page fetches **fresh headlines from the internet** every time you open it — no setup needed. Sources: [Hacker News](https://news.ycombinator.com) (via the free Algolia API) and [dev.to](https://dev.to).

> Tip: before an interview, skim this page for 10 minutes. Mentioning one recent development ("I saw yesterday that…") is a strong seniority signal.

<div id="news-app">
  <div class="news-tabs">
    <button class="news-tab active" data-tab="ai">AI News</button>
    <button class="news-tab" data-tab="top">Top Tech (HN)</button>
    <button class="news-tab" data-tab="ml">LLM / ML</button>
    <button class="news-tab" data-tab="dev">Dev Articles</button>
  </div>
  <button class="news-refresh" id="news-refresh" onclick="window.__loadNews(window.__newsTab, true)"><span id="news-refresh-icon">↻</span> <span>Refresh</span></button>
  <div class="news-status" id="news-status">Loading latest news…</div>
  <div id="news-list" aria-live="polite"></div>
</div>

<script>
(function () {
  var FEEDS = {
    ai:  { kind: 'hn', url: 'https://hn.algolia.com/api/v1/search_by_date?query=%22AI%22&tags=story&numericFilters=points%3E30&hitsPerPage=25' },
    top: { kind: 'hn', url: 'https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=25' },
    ml:  { kind: 'hn', url: 'https://hn.algolia.com/api/v1/search_by_date?query=LLM&tags=story&numericFilters=points%3E10&hitsPerPage=25' },
    dev: { kind: 'devto', url: 'https://dev.to/api/articles?top=7&per_page=25&tag=ai' }
  };
  window.__newsTab = window.__newsTab || 'ai';
  window.__newsCache = window.__newsCache || {};   // per-tab results: tab switches render instantly
  var requestSeq = 0;                              // guards against out-of-order responses

  function timeAgo(dateStr) {
    var s = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
    if (s < 3600) return Math.max(1, Math.floor(s / 60)) + ' min ago';
    if (s < 86400) return Math.floor(s / 3600) + ' hours ago';
    return Math.floor(s / 86400) + ' days ago';
  }
  // innerHTML escapes & < > but not quotes, and these strings land in attributes.
  function esc(t) {
    var d = document.createElement('div'); d.textContent = t || '';
    return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Feed links only: a javascript: or data: href would run on this origin.
  function safeUrl(u) {
    return /^https?:\/\//i.test(u || '') ? u : '#';
  }

  function render(items) {
    var list = document.getElementById('news-list');
    if (!list) return;
    if (!items.length) {
      list.innerHTML =
        '<div class="news-state">' +
          '<div class="ns-icon"><svg xmlns=\'http://www.w3.org/2000/svg\' width=\'28\' height=\'28\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'currentColor\' stroke-width=\'1.8\' stroke-linecap=\'round\' stroke-linejoin=\'round\' aria-hidden=\'true\'><path d=\'M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2\'/><path d=\'M18 14h-8\'/><path d=\'M15 18h-5\'/><path d=\'M10 6h8v4h-8V6Z\'/></svg></div>' +
          '<h4>No stories right now</h4>' +
          '<p>This feed came back empty. Try another tab, or refresh in a minute.</p>' +
          '<button class="news-refresh" onclick="window.__loadNews(window.__newsTab, true)">↻ Refresh</button>' +
        '</div>';
      return;
    }
    list.innerHTML = items.map(function (it) {
      return '<div class="news-card">' +
        '<a class="title" href="' + esc(safeUrl(it.url)) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a>' +
        '<div class="news-meta">' + esc(it.meta) + '</div>' +
      '</div>';
    }).join('');
  }

  function renderSkeleton() {
    var list = document.getElementById('news-list');
    if (!list) return;
    var card = '<div class="news-skeleton"><div class="sk-line"></div><div class="sk-line w70"></div><div class="sk-line w40"></div></div>';
    list.innerHTML = card + card + card + card + card;
  }

  function renderError(message) {
    var list = document.getElementById('news-list');
    if (!list) return;
    list.innerHTML =
      '<div class="news-state">' +
        '<div class="ns-icon"><svg xmlns=\'http://www.w3.org/2000/svg\' width=\'28\' height=\'28\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'currentColor\' stroke-width=\'1.8\' stroke-linecap=\'round\' stroke-linejoin=\'round\' aria-hidden=\'true\'><circle cx=\'12\' cy=\'12\' r=\'10\'/><line x1=\'12\' y1=\'8\' x2=\'12\' y2=\'12\'/><line x1=\'12\' y1=\'16\' x2=\'12.01\' y2=\'16\'/></svg></div>' +
        '<h4>Could not fetch the news</h4>' +
        '<p>' + esc(message) + ' — check your internet connection.</p>' +
        '<button class="news-refresh" onclick="window.__loadNews(window.__newsTab, true)">↻ Try again</button>' +
      '</div>';
  }

  function setLoading(isLoading) {
    var btn = document.getElementById('news-refresh');
    var icon = document.getElementById('news-refresh-icon');
    if (btn) { btn.disabled = isLoading; }
    if (icon) { icon.innerHTML = isLoading ? '<span class="im-spinner"></span>' : '↻'; }
    document.querySelectorAll('.news-tab').forEach(function (b) { b.disabled = isLoading; });
  }

  window.__loadNews = function (tab, force) {
    window.__newsTab = tab;
    var status = document.getElementById('news-status');
    var feed = FEEDS[tab];
    var seq = ++requestSeq;
    document.querySelectorAll('.news-tab').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });

    var cached = window.__newsCache[tab];
    if (cached && cached.length) {
      // We have data: keep it on screen, update quietly (never blank out a refresh).
      render(cached);
      if (status) status.textContent = force ? 'Refreshing…' : 'Showing cached stories · updating…';
    } else {
      // No data yet: skeleton placeholders, never a blank page.
      renderSkeleton();
      if (status) status.textContent = 'Fetching latest headlines…';
    }
    setLoading(true);

    // Note: HN Algolia rejects unknown query params (HTTP 400), so bypass
    // the HTTP cache with cache:'no-store' instead of a ?_=timestamp buster.
    fetch(feed.url, force ? { cache: 'no-store' } : undefined)
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        if (seq !== requestSeq) return; // a newer request superseded this one
        var items = [];
        if (feed.kind === 'hn') {
          items = (data.hits || []).filter(function (h) { return h.title; }).map(function (h) {
            return {
              title: h.title,
              url: h.url || ('https://news.ycombinator.com/item?id=' + h.objectID),
              meta: '▲ ' + (h.points || 0) + ' points · ' + (h.num_comments || 0) + ' comments · ' + timeAgo(h.created_at) + ' · Hacker News'
            };
          });
        } else {
          items = (data || []).map(function (a) {
            return {
              title: a.title,
              url: a.url,
              meta: (a.public_reactions_count || 0) + ' reactions · by ' + (a.user ? a.user.name : 'unknown') + ' · ' + timeAgo(a.published_at) + ' · dev.to'
            };
          });
        }
        window.__newsCache[tab] = items;
        if (status) status.textContent = items.length + ' stories · updated ' + new Date().toLocaleTimeString() + ' · live from the internet';
        render(items);
        setLoading(false);
      })
      .catch(function (e) {
        if (seq !== requestSeq) return;
        console.error('news fetch failed:', e);
        setLoading(false);
        var stale = window.__newsCache[tab];
        if (stale && stale.length) {
          // Keep showing the stories we have; surface the error in the status line.
          render(stale);
          if (status) status.textContent = 'Update failed (' + e.message + '). Showing previously loaded stories.';
        } else {
          if (status) status.textContent = 'Could not fetch news.';
          renderError(e.message);
        }
      });
  };

  document.querySelectorAll('.news-tab').forEach(function (btn) {
    btn.addEventListener('click', function () { window.__loadNews(btn.getAttribute('data-tab'), false); });
  });

  window.__loadNews(window.__newsTab, false);
})();
</script>

---

## More free sources worth bookmarking

| Source | What it is good for |
|---|---|
| [Hacker News](https://news.ycombinator.com) | What engineers are actually talking about today |
| [Hugging Face Papers](https://huggingface.co/papers) | Trending ML papers, daily |
| [The Batch (DeepLearning.AI)](https://www.deeplearning.ai/the-batch/) | Weekly AI newsletter, plain English |
| [Anthropic News](https://www.anthropic.com/news) / [OpenAI News](https://openai.com/news/) | Frontier model releases |
| [InfoQ](https://www.infoq.com) | Architecture & engineering practice news |

Also see **[4.11 Latest AI Trends (2025–26)](04-ml-genai-agents/11-latest-ai-trends.md)** for a curated, interview-ready summary.
