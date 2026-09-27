(function () {
    const FIELDS = ['title', 'body', 'image_url'];
    const autofilled = {};

    function previewUrl(newsId) {
        return window.location.pathname.replace(/\/(add|\d+\/change)\/?$/, `/news-preview/${newsId}/`);
    }

    async function fillFromNews(newsId) {
        if (!newsId) return;
        const response = await fetch(previewUrl(newsId), { credentials: 'same-origin' });
        if (!response.ok) return;
        const preview = await response.json();
        FIELDS.forEach((name) => {
            const input = document.getElementById(`id_${name}`);
            if (!input || (input.value && input.value !== autofilled[name])) return;
            input.value = preview[name] || '';
            autofilled[name] = input.value;
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        const select = document.getElementById('id_news');
        if (!select) return;
        const onChange = () => fillFromNews(select.value);
        if (window.django && window.django.jQuery) {
            window.django.jQuery(select).on('change', onChange);
        } else {
            select.addEventListener('change', onChange);
        }
        if (select.value && !document.getElementById('id_title').value) onChange();
    });
})();
