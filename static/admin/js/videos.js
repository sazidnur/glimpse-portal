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
            btn.classList.add('opacity-50', 'cursor-not-allowed');
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
                    (d.thumbnailurl ? '<br><img src="' + d.thumbnailurl + '" class="max-w-xs mt-3 rounded-lg shadow">' : ''),
                    'success'
                );
                input.value = '';
                setTimeout(function() {
                    var currentPath = window.location.pathname || '';
                    var targetPath = currentPath.replace(/\/add\/?$/, '/' + d.id + '/change/');
                    if (targetPath === currentPath) {
                        targetPath = currentPath.replace(/\/?$/, '/') + d.id + '/change/';
                    }
                    window.location.href = targetPath;
                }, 1500);
            })
            .catch(function(err) {
                showStatus('Network error: ' + err.message, 'error');
            })
            .finally(function() {
                btn.disabled = false;
                btn.textContent = 'Fetch & Save';
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
            });
        });

        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                btn.click();
            }
        });

        function showStatus(msg, type) {
            var classes = {
                info: 'bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800',
                success: 'bg-green-50 text-green-800 border-green-200 dark:bg-green-900/20 dark:text-green-300 dark:border-green-800',
                error: 'bg-red-50 text-red-800 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800'
            };
            status.innerHTML = '<div class="p-3 rounded-lg border text-sm ' + (classes[type] || classes.info) + '">' + msg + '</div>';
        }
    });
})();
