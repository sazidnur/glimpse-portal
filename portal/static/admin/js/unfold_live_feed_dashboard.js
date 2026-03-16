(function() {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  function csrfToken() {
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  function esc(value) {
    var div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  document.addEventListener('DOMContentLoaded', function() {
    var app = $('live-feed-app');
    if (!app) return;

    var API = {
      publish: app.dataset.publishUrl || '',
      token: app.dataset.tokenUrl || '',
      categories: app.dataset.categoriesUrl || '',
      items: app.dataset.itemsUrl || '',
      updateTemplate: app.dataset.categoryUpdateTemplate || '',
      deleteTemplate: app.dataset.categoryDeleteTemplate || ''
    };
    var workerWsUrl = app.dataset.workerWsUrl || '';

    var state = {
      categories: [],
      items: [],
      filterCategory: null,
      ws: null,
      reconnectAttempts: 0,
      reconnectTimer: null,
      pageVisible: true,
      costs: { worker: 0, do: 0, ws: 0 }
    };

    var controls = $('feed-controls');
    var wsLabel = $('ws-label');
    var liveUsers = $('live-users');
    var btnConnect = $('btn-ws-connect');
    var btnDisconnect = $('btn-ws-disconnect');

    function setControlsEnabled(enabled) {
      if (controls) controls.disabled = !enabled;
    }

    function setConnectedStatus(status) {
      if (status === 'connected') {
        wsLabel.textContent = 'Connected';
        btnConnect.disabled = true;
        btnDisconnect.disabled = false;
        setControlsEnabled(true);
        return;
      }
      if (status === 'connecting') {
        wsLabel.textContent = 'Connecting...';
        btnConnect.disabled = true;
        btnDisconnect.disabled = false;
        setControlsEnabled(false);
        return;
      }
      wsLabel.textContent = 'Disconnected';
      btnConnect.disabled = false;
      btnDisconnect.disabled = true;
      liveUsers.textContent = '-';
      setControlsEnabled(false);
    }

    function updateCost(type, amount) {
      state.costs[type] += amount || 1;
      $('cost-worker').textContent = String(state.costs.worker);
      $('cost-do').textContent = String(state.costs.do);
      $('cost-ws').textContent = String(state.costs.ws);
    }

    function log(message, kind) {
      var prefix = { info: '*', success: 'OK', error: 'ERR', ws: 'WS' }[kind] || '*';
      var ts = new Date().toLocaleTimeString();
      var logBox = $('log');
      logBox.textContent = '[' + ts + '] ' + prefix + ' ' + message + '\n' + logBox.textContent;
    }

    async function fetchJson(url, options) {
      updateCost('worker', 1);
      var response = await fetch(url, options || {});
      var data = await response.json().catch(function() { return {}; });
      if (!response.ok) {
        throw new Error(data.error || ('HTTP ' + response.status));
      }
      return data;
    }

    async function api(url, method, body) {
      var opts = {
        method: method || 'GET',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken()
        }
      };
      if (body !== undefined && body !== null) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
      return fetchJson(url, opts);
    }

    function categoryUpdateUrl(id) {
      return API.updateTemplate.replace('__ID__', String(id));
    }

    function categoryDeleteUrl(id) {
      return API.deleteTemplate.replace('__ID__', String(id));
    }

    function renderCategoryDropdowns() {
      var filter = $('filter-cat');
      var publish = $('pub-cat');
      var enabled = state.categories.filter(function(c) {
        return c.enabled && Number(c.live_feed_type || 0) > 0;
      });

      filter.innerHTML = '<option value="">All Categories</option>' + state.categories.map(function(c) {
        return '<option value="' + Number(c.id) + '">' + esc(c.name || ('#' + c.id)) + '</option>';
      }).join('');

      publish.innerHTML = '<option value="">Select category...</option>' + enabled.map(function(c) {
        return '<option value="' + Number(c.id) + '">' + esc(c.name || ('#' + c.id)) + '</option>';
      }).join('');
    }

    function renderCategories() {
      var body = $('cat-list');
      if (!state.categories.length) {
        body.innerHTML = '<tr><td class="px-3 py-2 text-sm" colspan="6">No categories found.</td></tr>';
        return;
      }

      body.innerHTML = state.categories.map(function(c) {
        return '<tr class="odd:bg-base-50/60 dark:odd:bg-base-900/40" data-id="' + Number(c.id) + '">' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + Number(c.id) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + esc(c.name || '') + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + Number(c.live_feed_type || 0) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + (c.enabled ? 'Yes' : 'No') + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + Number(c.order || 0) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' +
            '<button type="button" class="bg-white border border-base-200 cursor-pointer font-medium px-2 py-1 rounded-default shadow-xs text-important text-xs hover:bg-base-100/80 dark:bg-transparent dark:border-base-700 dark:hover:bg-base-800/80" data-action="edit">Edit</button> ' +
            '<button type="button" class="bg-red-600 border border-transparent cursor-pointer font-medium px-2 py-1 rounded-default shadow-xs text-xs text-white hover:bg-red-600/80" data-action="delete">Delete</button>' +
          '</td>' +
        '</tr>';
      }).join('');

      body.querySelectorAll('button[data-action="edit"]').forEach(function(button) {
        button.addEventListener('click', function() {
          var id = button.closest('tr').dataset.id;
          openEditDialog(id);
        });
      });

      body.querySelectorAll('button[data-action="delete"]').forEach(function(button) {
        button.addEventListener('click', function() {
          var id = button.closest('tr').dataset.id;
          deleteCategory(id);
        });
      });
    }

    function categoryName(id) {
      var item = state.categories.find(function(c) { return Number(c.id) === Number(id); });
      return item ? item.name : ('#' + id);
    }

    function renderItems() {
      var filtered = state.filterCategory
        ? state.items.filter(function(i) { return Number(i.category_id) === Number(state.filterCategory); })
        : state.items;

      $('item-count').textContent = filtered.length + ' items';
      var body = $('item-list');
      if (!filtered.length) {
        body.innerHTML = '<tr><td class="px-3 py-2 text-sm" colspan="5">No items yet.</td></tr>';
        return;
      }

      body.innerHTML = filtered.slice(0, 200).map(function(item) {
        return '<tr class="odd:bg-base-50/60 dark:odd:bg-base-900/40">' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + esc(categoryName(item.category_id)) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + Number(item.seq || 0) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + Number(item.impact || 0) + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + esc(item.title || '') + '</td>' +
          '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + esc(item.timestamp || '') + '</td>' +
        '</tr>';
      }).join('');
    }

    function openDialog(id) {
      var dlg = $(id);
      if (!dlg) return;
      if (typeof dlg.showModal === 'function') {
        dlg.showModal();
      }
    }

    function closeDialog(id) {
      var dlg = $(id);
      if (!dlg) return;
      if (typeof dlg.close === 'function') {
        dlg.close();
      }
    }

    function openEditDialog(id) {
      var category = state.categories.find(function(c) { return Number(c.id) === Number(id); });
      if (!category) return;
      $('edit-id').value = String(category.id);
      $('edit-name').value = category.name || '';
      $('edit-type').value = String(Number(category.live_feed_type || 0));
      $('edit-order').value = String(Number(category.order || 0));
      $('edit-enabled').value = category.enabled ? '1' : '0';
      openDialog('modal-edit');
    }

    async function loadCategories() {
      try {
        updateCost('do', 1);
        var data = await api(API.categories, 'GET');
        state.categories = data.items || [];
        renderCategories();
        renderCategoryDropdowns();
        log('Loaded ' + state.categories.length + ' categories.', 'success');
      } catch (err) {
        log('Failed to load categories: ' + err.message, 'error');
      }
    }

    async function createCategory() {
      var name = $('add-name').value.trim();
      if (!name) {
        log('Category name is required.', 'error');
        return;
      }
      try {
        updateCost('do', 1);
        await api(API.categories, 'POST', {
          name: name,
          live_feed_type: Number($('add-type').value || 1),
          order: Number($('add-order').value || 0),
          enabled: $('add-enabled').value === '1'
        });
        closeDialog('modal-add');
        $('add-form').reset();
        $('add-type').value = '1';
        $('add-order').value = '0';
        $('add-enabled').value = '1';
        await loadCategories();
        log('Category created.', 'success');
      } catch (err) {
        log('Create failed: ' + err.message, 'error');
      }
    }

    async function saveCategory() {
      var id = $('edit-id').value;
      if (!id) return;
      try {
        updateCost('do', 1);
        await api(categoryUpdateUrl(id), 'POST', {
          name: $('edit-name').value.trim(),
          live_feed_type: Number($('edit-type').value || 0),
          order: Number($('edit-order').value || 0),
          enabled: $('edit-enabled').value === '1'
        });
        closeDialog('modal-edit');
        await loadCategories();
        log('Category updated.', 'success');
      } catch (err) {
        log('Update failed: ' + err.message, 'error');
      }
    }

    async function deleteCategory(id) {
      if (!confirm('Delete category ' + id + '?')) return;
      try {
        updateCost('do', 1);
        await api(categoryDeleteUrl(id), 'POST', {});
        state.items = state.items.filter(function(item) {
          return Number(item.category_id) !== Number(id);
        });
        renderItems();
        await loadCategories();
        log('Category deleted.', 'success');
      } catch (err) {
        log('Delete failed: ' + err.message, 'error');
      }
    }

    async function publishItem(event) {
      event.preventDefault();
      var categoryId = $('pub-cat').value;
      var title = $('pub-title').value.trim();
      if (!categoryId || !title) {
        log('Category and title are required.', 'error');
        return;
      }
      try {
        updateCost('do', 1);
        await api(API.publish, 'POST', {
          category_id: Number(categoryId),
          title: title,
          impact: Number($('pub-impact').value || 0),
          timestamp: $('pub-ts').value.trim() || undefined
        });
        $('pub-title').value = '';
        $('pub-ts').value = '';
        log('Published item.', 'success');
      } catch (err) {
        log('Publish failed: ' + err.message, 'error');
      }
    }

    function handleWebSocketMessage(msg) {
      if (msg.type === 'connected') {
        log('WebSocket connected.', 'ws');
        return;
      }

      if (msg.type === 'bootstrap') {
        updateCost('do', 1);
        liveUsers.textContent = String(msg.live_users == null ? '-' : msg.live_users);
        var bootstrapCategories = msg.categories || [];
        state.categories = bootstrapCategories.map(function(cat) {
          return {
            id: cat.category_id,
            name: cat.name || ('Category ' + cat.category_id),
            enabled: cat.enabled !== false,
            live_feed_type: cat.live_feed_type || 1,
            order: 0
          };
        });
        renderCategories();
        renderCategoryDropdowns();

        state.items = [];
        bootstrapCategories.forEach(function(cat) {
          (cat.items || []).forEach(function(item) {
            state.items.push(item);
          });
        });
        state.items.sort(function(a, b) {
          return new Date(b.timestamp) - new Date(a.timestamp);
        });
        renderItems();
        log('Bootstrap received.', 'ws');
        return;
      }

      if (msg.type === 'item' && msg.item) {
        if (msg.live_users !== undefined) {
          liveUsers.textContent = String(msg.live_users);
        }
        state.items.unshift(msg.item);
        state.items = state.items.slice(0, 1000);
        renderItems();
        log('New item received.', 'ws');
        return;
      }

      if (msg.type === 'older_items') {
        (msg.items || []).forEach(function(item) {
          var exists = state.items.find(function(existing) {
            return Number(existing.category_id) === Number(item.category_id) && Number(existing.seq) === Number(item.seq);
          });
          if (!exists) state.items.push(item);
        });
        renderItems();
        log('Older items loaded.', 'ws');
      }
    }

    async function getToken() {
      var data = await api(API.token, 'GET');
      return data.token;
    }

    function reconnectDelay() {
      return Math.min(1000 * Math.pow(2, state.reconnectAttempts), 30000);
    }

    function scheduleReconnect() {
      if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
      }
      if (!state.pageVisible) {
        log('Page hidden, reconnect paused.', 'info');
        return;
      }
      var delay = reconnectDelay();
      state.reconnectAttempts += 1;
      log('Reconnect in ' + (delay / 1000) + 's.', 'info');
      state.reconnectTimer = setTimeout(function() {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
          connectWebSocket();
        }
      }, delay);
    }

    async function connectWebSocket() {
      if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
        return;
      }

      setConnectedStatus('connecting');
      try {
        var token = await getToken();
        var wsUrl = workerWsUrl + '?token=' + encodeURIComponent(token);
        state.ws = new WebSocket(wsUrl);
        updateCost('do', 1);

        state.ws.onopen = function() {
          state.reconnectAttempts = 0;
          setConnectedStatus('connected');
          log('Connected to live feed socket.', 'success');
        };

        state.ws.onmessage = function(event) {
          updateCost('ws', 1);
          try {
            handleWebSocketMessage(JSON.parse(event.data));
          } catch (err) {
            log('Invalid WS payload.', 'error');
          }
        };

        state.ws.onclose = function(event) {
          setConnectedStatus('disconnected');
          log('Socket closed (code ' + event.code + ').', event.wasClean ? 'info' : 'error');
          if (!event.wasClean) {
            scheduleReconnect();
          }
        };

        state.ws.onerror = function() {
          log('WebSocket error.', 'error');
        };
      } catch (err) {
        setConnectedStatus('disconnected');
        log('Connect failed: ' + err.message, 'error');
        scheduleReconnect();
      }
    }

    function disconnectWebSocket() {
      if (state.reconnectTimer) {
        clearTimeout(state.reconnectTimer);
        state.reconnectTimer = null;
      }
      if (state.ws) {
        state.ws.onclose = null;
        state.ws.close(1000, 'Closed by user');
        state.ws = null;
      }
      setConnectedStatus('disconnected');
      log('Disconnected.', 'info');
    }

    function loadOlderItems() {
      if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        log('WebSocket not connected.', 'error');
        return;
      }
      var filtered = state.filterCategory
        ? state.items.filter(function(item) { return Number(item.category_id) === Number(state.filterCategory); })
        : state.items;
      if (!filtered.length) {
        log('No items available for pagination.', 'error');
        return;
      }

      var oldestByCategory = {};
      filtered.forEach(function(item) {
        var catId = Number(item.category_id);
        var seq = Number(item.seq || 0);
        if (!oldestByCategory[catId] || seq < oldestByCategory[catId]) {
          oldestByCategory[catId] = seq;
        }
      });

      var catIds = state.filterCategory ? [Number(state.filterCategory)] : Object.keys(oldestByCategory).map(Number);
      catIds.forEach(function(catId) {
        var beforeSeq = oldestByCategory[catId];
        if (!beforeSeq) return;
        state.ws.send(JSON.stringify({
          type: 'load_older',
          category_id: catId,
          before_seq: beforeSeq,
          limit: 50
        }));
      });
      log('Requested older items.', 'info');
    }

    function initEvents() {
      btnConnect.addEventListener('click', function() {
        state.reconnectAttempts = 0;
        connectWebSocket();
      });
      btnDisconnect.addEventListener('click', function() {
        disconnectWebSocket();
      });

      $('btn-add-cat').addEventListener('click', function() { openDialog('modal-add'); });
      $('btn-cancel-add').addEventListener('click', function() { closeDialog('modal-add'); });
      $('btn-create-cat').addEventListener('click', createCategory);

      $('btn-cancel-edit').addEventListener('click', function() { closeDialog('modal-edit'); });
      $('btn-save-edit').addEventListener('click', saveCategory);

      $('form-publish').addEventListener('submit', publishItem);
      $('filter-cat').addEventListener('change', function(event) {
        state.filterCategory = event.target.value || null;
        renderItems();
      });
      $('btn-load-older').addEventListener('click', loadOlderItems);
      $('btn-clear-log').addEventListener('click', function() {
        $('log').textContent = '';
      });

      document.addEventListener('visibilitychange', function() {
        state.pageVisible = !document.hidden;
        if (!state.pageVisible && state.reconnectTimer) {
          clearTimeout(state.reconnectTimer);
          state.reconnectTimer = null;
        }
      });

      window.addEventListener('beforeunload', function() {
        disconnectWebSocket();
      });
    }

    setConnectedStatus('disconnected');
    initEvents();
    loadCategories();
    renderItems();
    log('Ready. Click Connect to start live feed.', 'success');
  });
})();
