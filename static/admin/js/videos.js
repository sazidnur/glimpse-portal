(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        var btn = document.getElementById('fetch-youtube-btn');
        if (!btn) return;

        var input = document.getElementById('youtube-url-input');
        var status = document.getElementById('youtube-fetch-status');
        var csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

        btn.addEventListener('click', function() {
            var url = input.value.trim();
            if (!url) {
                showStatus('Please paste a YouTube URL', 'error');
                return;
            }

            btn.disabled = true;
            btn.textContent = 'Fetching...';
            showStatus('Fetching video data from YouTube...', 'info');

            fetch(window.__YOUTUBE_FETCH_URL || '/portal/api/youtube/fetch/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({ url: url }),
            })
            .then(function(resp) { return resp.json().then(function(d) { return { ok: resp.ok, data: d }; }); })
            .then(function(result) {
                if (!result.ok) {
                    showStatus(result.data.error || 'Failed to fetch', 'error');
                    return;
                }
                var d = result.data;
                showStatus(
                    '<strong>Saved!</strong> ' + d.title +
                    (d.thumbnailurl ? '<br><img src="' + d.thumbnailurl + '" style="max-width:320px;margin-top:8px;border-radius:6px;">' : ''),
                    'success'
                );
                input.value = '';
                setTimeout(function() {
                    window.location.href = '/portal/supabase/videos/' + d.id + '/change/';
                }, 1500);
            })
            .catch(function(err) {
                showStatus('Network error: ' + err.message, 'error');
            })
            .finally(function() {
                btn.disabled = false;
                btn.textContent = 'Fetch & Save';
            });
        });

        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                btn.click();
            }
        });

        function showStatus(msg, type) {
            var colors = { info: '#417690', success: '#28a745', error: '#dc3545' };
            status.innerHTML = '<div style="padding:10px;border-radius:6px;color:#fff;background:' +
                (colors[type] || colors.info) + ';">' + msg + '</div>';
        }
    });
})();
