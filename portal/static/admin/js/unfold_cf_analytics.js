(function() {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  function formatCount(value) {
    return Number(value || 0).toLocaleString();
  }

  function formatTime(iso, unit) {
    var d = new Date(iso);
    if (unit === 'day') {
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    if (unit === 'hour') {
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }

  function drawTimeline(canvas, series) {
    var ctx = canvas.getContext('2d');
    var width = canvas.width;
    var height = canvas.height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    if (!series.length) {
      ctx.fillStyle = '#666666';
      ctx.font = '16px sans-serif';
      ctx.fillText('No data in selected range.', 20, 40);
      return;
    }

    var padding = { top: 20, right: 20, bottom: 40, left: 60 };
    var chartWidth = width - padding.left - padding.right;
    var chartHeight = height - padding.top - padding.bottom;

    var maxY = 0;
    series.forEach(function(point) {
      maxY = Math.max(maxY, Number(point.worker || 0), Number(point.cdn || 0), Number(point.origin || 0));
    });
    if (maxY <= 0) maxY = 1;

    function xAt(index) {
      if (series.length === 1) return padding.left + chartWidth / 2;
      return padding.left + (index * chartWidth / (series.length - 1));
    }

    function yAt(value) {
      return padding.top + (chartHeight - ((value / maxY) * chartHeight));
    }

    ctx.strokeStyle = '#cccccc';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, padding.top + chartHeight);
    ctx.lineTo(padding.left + chartWidth, padding.top + chartHeight);
    ctx.stroke();

    ctx.fillStyle = '#444444';
    ctx.font = '12px sans-serif';
    ctx.fillText(String(maxY), 8, yAt(maxY) + 4);
    ctx.fillText('0', 36, yAt(0) + 4);

    function drawSeries(key, color) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      series.forEach(function(point, index) {
        var x = xAt(index);
        var y = yAt(Number(point[key] || 0));
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();
    }

    drawSeries('worker', '#16a34a');
    drawSeries('cdn', '#2563eb');
    drawSeries('origin', '#dc2626');

    var labelsToShow = Math.min(6, series.length);
    var step = Math.max(1, Math.floor(series.length / labelsToShow));
    ctx.fillStyle = '#555555';
    ctx.font = '11px sans-serif';
    for (var i = 0; i < series.length; i += step) {
      var lx = xAt(i);
      var label = formatTime(series[i].ts, 'minute');
      ctx.fillText(label, lx - 25, padding.top + chartHeight + 18);
    }

    ctx.fillStyle = '#16a34a';
    ctx.fillRect(width - 210, 14, 10, 10);
    ctx.fillStyle = '#111111';
    ctx.fillText('Worker', width - 195, 24);
    ctx.fillStyle = '#2563eb';
    ctx.fillRect(width - 140, 14, 10, 10);
    ctx.fillStyle = '#111111';
    ctx.fillText('CDN', width - 125, 24);
    ctx.fillStyle = '#dc2626';
    ctx.fillRect(width - 90, 14, 10, 10);
    ctx.fillStyle = '#111111';
    ctx.fillText('Origin', width - 75, 24);
  }

  async function fetchData(url, range) {
    var response = await fetch(url + '?range=' + encodeURIComponent(range), {
      credentials: 'same-origin'
    });
    var data = await response.json().catch(function() { return {}; });
    if (!response.ok) {
      throw new Error(data.error || ('HTTP ' + response.status));
    }
    if (data.error) {
      throw new Error(data.error);
    }
    return data;
  }

  function setSummary(totals) {
    var total = Number(totals.total || 0);
    var worker = Number(totals.worker || 0);
    var cdn = Number(totals.cdn || 0);
    var origin = Number(totals.origin || 0);

    $('sum-total').textContent = formatCount(total);
    $('sum-worker').textContent = formatCount(worker);
    $('sum-cdn').textContent = formatCount(cdn);
    $('sum-origin').textContent = formatCount(origin);
  }

  function setTable(series, unit) {
    var body = $('cf-table-body');
    if (!body) return;
    if (!series.length) {
      body.innerHTML = '<tr><td class="px-3 py-2 text-sm" colspan="5">No data in selected range.</td></tr>';
      return;
    }

    body.innerHTML = series.slice().reverse().map(function(item) {
      var worker = Number(item.worker || 0);
      var cdn = Number(item.cdn || 0);
      var origin = Number(item.origin || 0);
      var total = worker + cdn + origin;
      return '<tr class="odd:bg-base-50/60 dark:odd:bg-base-900/40">' +
        '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + formatTime(item.ts, unit) + '</td>' +
        '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + formatCount(worker) + '</td>' +
        '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + formatCount(cdn) + '</td>' +
        '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + formatCount(origin) + '</td>' +
        '<td class="border-b border-base-200 px-3 py-2 text-sm dark:border-base-800">' + formatCount(total) + '</td>' +
      '</tr>';
    }).join('');
  }

  document.addEventListener('DOMContentLoaded', function() {
    var app = $('cf-analytics-app');
    if (!app) return;

    var dataUrl = app.dataset.dataUrl || '';
    var hasCredentials = (app.dataset.hasCredentials || '') === 'true';
    var status = $('cf-status');
    var updated = $('cf-updated');
    var canvas = $('timeline-chart');

    function setStatus(message) {
      if (status) status.textContent = message;
    }

    function markActive(range) {
      app.querySelectorAll('.range-btn').forEach(function(button) {
        if (button.dataset.range === range) {
          button.classList.add('active-range');
          button.classList.add('bg-primary-600', 'text-white', 'border-transparent');
          button.classList.remove('bg-white', 'border-base-200', 'text-important');
        } else {
          button.classList.remove('active-range');
          button.classList.remove('bg-primary-600', 'text-white', 'border-transparent');
          button.classList.add('bg-white', 'border-base-200', 'text-important');
        }
      });
    }

    async function load(range) {
      setStatus('Loading ' + range + ' ...');
      markActive(range);
      try {
        var data = await fetchData(dataUrl, range);
        var series = data.series || [];
        var totals = data.totals || {};
        var unit = data.unit || 'hour';

        setSummary(totals);
        setTable(series, unit);
        drawTimeline(canvas, series);

        setStatus('Loaded ' + range + '.');
        if (updated) updated.textContent = 'Updated: ' + new Date().toLocaleTimeString();
      } catch (err) {
        setStatus('Failed: ' + err.message);
        drawTimeline(canvas, []);
        $('cf-table-body').innerHTML = '<tr><td class="px-3 py-2 text-sm" colspan="5">Failed to load data.</td></tr>';
      }
    }

    app.querySelectorAll('.range-btn').forEach(function(button) {
      button.addEventListener('click', function() {
        load(button.dataset.range);
      });
    });

    if (!hasCredentials) {
      setStatus('Cloudflare credentials missing. Configure CF_ACCOUNT_ID and CF_ANALYTICS_TOKEN.');
      drawTimeline(canvas, []);
      $('cf-table-body').innerHTML = '<tr><td class="px-3 py-2 text-sm" colspan="5">Credentials missing.</td></tr>';
      return;
    }

    load('24h');
  });
})();
