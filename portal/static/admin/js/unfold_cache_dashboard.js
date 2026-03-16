(function() {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  function getCsrfToken() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  function parseResources(raw) {
    try {
      return JSON.parse(raw || '[]');
    } catch (err) {
      return [];
    }
  }

  function setButtonLoading(button, loading, text) {
    if (!button) return;
    if (loading) {
      button.dataset.originalText = button.textContent;
      button.textContent = text || 'Working...';
      button.disabled = true;
      return;
    }
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }

  async function fetchJson(url, options) {
    var response = await fetch(url, options || {});
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) {
      throw new Error(data.error || ('HTTP ' + response.status));
    }
    return data;
  }

  document.addEventListener('DOMContentLoaded', function() {
    var app = $('cache-dashboard-app');
    if (!app) return;

    var resources = parseResources(app.dataset.resources);
    var statsTemplate = app.dataset.statsTemplate || '';
    var warmTemplate = app.dataset.warmTemplate || '';
    var flushTemplate = app.dataset.flushTemplate || '';
    var metadataStatsUrl = app.dataset.metadataStats || '';
    var metadataFlushUrl = app.dataset.metadataFlush || '';
    var metadataRebuildUrl = app.dataset.metadataRebuild || '';
    var csrfToken = getCsrfToken();

    var sectionsRoot = $('resource-sections');
    var globalStatus = $('global-status');
    var lastUpdated = $('last-updated');

    function setStatus(message) {
      if (globalStatus) globalStatus.textContent = message;
    }

    function makeUrl(template, key) {
      return template.replace('__KEY__', key);
    }

    function buildSection(resource) {
      var wrap = document.createElement('div');
      wrap.className = 'bg-white border border-base-200 p-6 rounded-default shadow-xs dark:bg-base-900 dark:border-base-800';
      wrap.id = 'section-' + resource.key;
      wrap.innerHTML =
        '<h2 class="font-semibold text-lg text-font-important-light dark:text-font-important-dark">' + resource.label + '</h2>' +
        '<div class="mt-4 overflow-hidden rounded-default border border-base-200 dark:border-base-800">' +
        '<table class="w-full border-separate border-spacing-0"><tbody>' +
        '<tr><th class="bg-base-50 border-b border-base-200 px-3 py-2 text-left text-sm font-semibold dark:bg-base-900 dark:border-base-800">Cached</th><td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800" id="stat-' + resource.key + '-cached">-</td></tr>' +
        '<tr><th class="bg-base-50 border-b border-base-200 px-3 py-2 text-left text-sm font-semibold dark:bg-base-900 dark:border-base-800">DB Total</th><td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800" id="stat-' + resource.key + '-db">-</td></tr>' +
        '<tr><th class="bg-base-50 border-b border-base-200 px-3 py-2 text-left text-sm font-semibold dark:bg-base-900 dark:border-base-800">Sync</th><td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800" id="stat-' + resource.key + '-sync">-</td></tr>' +
        '<tr><th class="bg-base-50 border-b border-base-200 px-3 py-2 text-left text-sm font-semibold dark:bg-base-900 dark:border-base-800">Redis Memory</th><td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800" id="stat-' + resource.key + '-mem">-</td></tr>' +
        '<tr><th class="bg-base-50 border-base-200 px-3 py-2 text-left text-sm font-semibold dark:bg-base-900 dark:border-base-800">Redis Peak</th><td class="px-3 py-2 text-sm" id="stat-' + resource.key + '-peak">-</td></tr>' +
        '</tbody></table></div>' +
        '<div class="flex flex-wrap gap-2 mt-4">' +
        '<button type="button" class="bg-white border border-base-200 cursor-pointer font-medium px-3 py-2 rounded-default shadow-xs text-important text-sm hover:bg-base-100/80 dark:bg-transparent dark:border-base-700 dark:hover:bg-base-800/80 btn-warm-one" data-key="' + resource.key + '">Warm</button>' +
        '<button type="button" class="bg-red-600 border border-transparent cursor-pointer font-medium px-3 py-2 rounded-default shadow-xs text-sm text-white hover:bg-red-600/80 btn-flush-one" data-key="' + resource.key + '">Flush</button>' +
        '</div>';
      return wrap;
    }

    function formatNumber(value) {
      return Number(value || 0).toLocaleString();
    }

    async function loadStatsFor(key) {
      var data = await fetchJson(makeUrl(statsTemplate, key), {
        headers: { 'X-CSRFToken': csrfToken }
      });

      var cached = Number(data.total_items || 0);
      var dbTotal = Number(data.db_total || 0);
      $('stat-' + key + '-cached').textContent = formatNumber(cached);
      $('stat-' + key + '-db').textContent = formatNumber(dbTotal);
      $('stat-' + key + '-mem').textContent = data.redis_used_memory || '-';
      $('stat-' + key + '-peak').textContent = data.redis_peak_memory || '-';

      var sync = $('stat-' + key + '-sync');
      if (cached === dbTotal) {
        sync.textContent = 'Synced';
      } else if (cached === 0) {
        sync.textContent = 'Cold';
      } else {
        sync.textContent = String(dbTotal - cached) + ' behind';
      }
    }

    async function loadMetadataStatus() {
      var data = await fetchJson(metadataStatsUrl, {
        headers: { 'X-CSRFToken': csrfToken }
      });
      var status = $('metadata-status');
      if (!status) return;
      if (data.cached) {
        var ttl = '';
        if (typeof data.ttl_seconds === 'number' && data.ttl_seconds >= 0) {
          ttl = ' (TTL ' + Math.floor(data.ttl_seconds / 60) + 'm)';
        }
        status.textContent = 'Cached' + ttl;
        return;
      }
      status.textContent = 'Cold';
    }

    async function post(url) {
      return fetchJson(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrfToken }
      });
    }

    async function refreshAll() {
      await Promise.all(resources.map(function(r) { return loadStatsFor(r.key); }));
      await loadMetadataStatus();
      if (lastUpdated) lastUpdated.textContent = 'Last refreshed: ' + new Date().toLocaleTimeString();
    }

    async function onWarmAll(button) {
      if (!confirm('Warm all caches from DB?')) return;
      setButtonLoading(button, true, 'Warming...');
      setStatus('Warming all caches...');
      try {
        var results = await Promise.all(resources.map(function(r) { return post(makeUrl(warmTemplate, r.key)); }));
        var summary = results.map(function(item, index) {
          return resources[index].label + ': ' + Number(item.warmed || 0);
        }).join(', ');
        setStatus('Warmed. ' + summary);
        await refreshAll();
      } catch (err) {
        setStatus('Failed: ' + err.message);
      } finally {
        setButtonLoading(button, false);
      }
    }

    async function onFlushAll(button) {
      if (!confirm('Flush all caches?')) return;
      setButtonLoading(button, true, 'Flushing...');
      setStatus('Flushing all caches...');
      try {
        await Promise.all(resources.map(function(r) { return post(makeUrl(flushTemplate, r.key)); }));
        setStatus('All caches flushed.');
        await refreshAll();
      } catch (err) {
        setStatus('Failed: ' + err.message);
      } finally {
        setButtonLoading(button, false);
      }
    }

    async function onMetadataFlush(button) {
      if (!confirm('Flush metadata cache?')) return;
      setButtonLoading(button, true, 'Flushing...');
      setStatus('Flushing metadata cache...');
      try {
        await post(metadataFlushUrl);
        setStatus('Metadata cache flushed.');
        await loadMetadataStatus();
      } catch (err) {
        setStatus('Failed: ' + err.message);
      } finally {
        setButtonLoading(button, false);
      }
    }

    async function onMetadataRebuild(button) {
      if (!confirm('Rebuild metadata cache from DB?')) return;
      setButtonLoading(button, true, 'Rebuilding...');
      setStatus('Rebuilding metadata cache...');
      try {
        await post(metadataRebuildUrl);
        setStatus('Metadata cache rebuilt.');
        await loadMetadataStatus();
      } catch (err) {
        setStatus('Failed: ' + err.message);
      } finally {
        setButtonLoading(button, false);
      }
    }

    sectionsRoot.innerHTML = '';
    resources.forEach(function(resource) {
      sectionsRoot.appendChild(buildSection(resource));
    });

    document.querySelectorAll('.btn-warm-one').forEach(function(button) {
      button.addEventListener('click', async function() {
        var key = button.dataset.key;
        var label = (resources.find(function(r) { return r.key === key; }) || {}).label || key;
        if (!confirm('Warm ' + label + ' cache from DB?')) return;
        setButtonLoading(button, true, 'Warming...');
        setStatus('Warming ' + label + '...');
        try {
          var data = await post(makeUrl(warmTemplate, key));
          setStatus(label + ' warmed (' + Number(data.warmed || 0) + ').');
          await loadStatsFor(key);
        } catch (err) {
          setStatus('Failed: ' + err.message);
        } finally {
          setButtonLoading(button, false);
        }
      });
    });

    document.querySelectorAll('.btn-flush-one').forEach(function(button) {
      button.addEventListener('click', async function() {
        var key = button.dataset.key;
        var label = (resources.find(function(r) { return r.key === key; }) || {}).label || key;
        if (!confirm('Flush ' + label + ' cache?')) return;
        setButtonLoading(button, true, 'Flushing...');
        setStatus('Flushing ' + label + '...');
        try {
          await post(makeUrl(flushTemplate, key));
          setStatus(label + ' cache flushed.');
          await loadStatsFor(key);
        } catch (err) {
          setStatus('Failed: ' + err.message);
        } finally {
          setButtonLoading(button, false);
        }
      });
    });

    $('btn-refresh-all').addEventListener('click', async function(event) {
      var button = event.currentTarget;
      setButtonLoading(button, true, 'Refreshing...');
      setStatus('Refreshing...');
      try {
        await refreshAll();
        setStatus('Refreshed.');
      } catch (err) {
        setStatus('Failed: ' + err.message);
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('btn-warm-all').addEventListener('click', function(event) {
      onWarmAll(event.currentTarget);
    });
    $('btn-flush-all').addEventListener('click', function(event) {
      onFlushAll(event.currentTarget);
    });
    $('btn-metadata-flush').addEventListener('click', function(event) {
      onMetadataFlush(event.currentTarget);
    });
    $('btn-metadata-rebuild').addEventListener('click', function(event) {
      onMetadataRebuild(event.currentTarget);
    });

    refreshAll().then(function() {
      setStatus('Ready.');
    }).catch(function(err) {
      setStatus('Failed: ' + err.message);
    });
  });
})();
