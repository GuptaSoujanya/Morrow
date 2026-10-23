/* The hosted course shares the dashboard's durable learning progress. */
(function () {
  if (!location.pathname.startsWith('/course/')) return;
  const style = document.createElement('style');
  style.textContent = '.morrow-progress{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:16px 20px;margin-bottom:28px;border:1px solid #b9a5ff60;border-radius:16px;background:#1b1d24;color:#f2f3f7;font:14px/1.5 system-ui}.morrow-progress a{color:#c9b9ff!important;font-weight:600}.morrow-progress p{flex:1;margin:0!important;min-width:160px;font-size:13px!important}.morrow-progress button{border:1px solid #b9a5ff70;border-radius:10px;min-height:44px;padding:10px 16px;background:#b9a5ff;color:#241b3a;font:600 14px system-ui;cursor:pointer}.morrow-progress button:disabled{opacity:.6;cursor:wait}.morrow-progress :focus-visible{outline:2px solid #b9a5ff;outline-offset:4px}';
  document.head.append(style);
  async function request(path, body) {
    const response = await fetch(path, {method:body ? 'POST' : 'GET', headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined, signal:AbortSignal.timeout(15000)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Please try again.');
    return data;
  }
  window.$docsify.plugins.push(function (hook) {
    hook.doneEach(async function () {
      const hash = location.hash;
      const target = document.querySelector('.markdown-section');
      if (!target) return;
      target.querySelector('.morrow-progress')?.remove();
      const bar = document.createElement('section');bar.className = 'morrow-progress';bar.setAttribute('aria-label','Learning progress');
      const back = document.createElement('a');back.href = '/#/study';back.textContent = '← Learning path';
      const status = document.createElement('p');status.setAttribute('role','status');status.textContent = 'Loading saved progress…';
      const button = document.createElement('button');button.type = 'button';button.hidden = true;
      bar.append(back, status, button);target.prepend(bar);
      async function load() {
        button.disabled = true;
        try {
          const data = await request('/api/course');
          if (location.hash !== hash || !bar.isConnected) return;
          const route = decodeURIComponent(hash.replace(/^#\/?/, '').split('?')[0]);
          const lesson = data.tracks.flatMap(t => t.modules).find(m => m.route === route);
          if (!lesson) { status.textContent = 'Explore your courses and saved progress in Learning path.';button.hidden = true;return; }
          function ready() { button.textContent = lesson.read ? 'Reopen lesson' : 'Mark complete';button.hidden = false;button.disabled = false; }
          status.textContent = lesson.read ? 'Completed · saved in .memory' : 'Finish this lesson, then save your progress.';
          ready();
          button.onclick = async function () {
            button.disabled = true;button.textContent = 'Saving…';status.textContent = 'Saving your progress…';
            try { await request('/api/course/read', {path:lesson.path,read:!lesson.read});lesson.read = !lesson.read;status.textContent = lesson.read ? 'Completed · saved in .memory. Your progress stays after restart.' : 'Reopened · saved in .memory.'; }
            catch (error) { status.textContent = 'Could not save. ' + error.message; }
            finally { ready(); }
          };
        } catch (error) { status.textContent = 'Could not load progress. ' + error.message;button.textContent = 'Try again';button.hidden = false;button.disabled = false;button.onclick = load; }
      }
      load();
    });
  });
})();
