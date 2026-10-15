/* Online Exam - browser side.
 * The REAL deadline lives on the server. This script only
 *  - shows a countdown (started from the seconds-left the server sent)
 *  - saves every answer immediately (so nothing is lost if the tab closes)
 *  - auto-submits the form when the countdown reaches 0
 */
(function () {
    'use strict';

    function fmt(total) {
        var m = Math.floor(total / 60);
        var s = total % 60;
        return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }

    function init() {
        var root = document.getElementById('oe_exam_root');
        if (!root) { return; }

        var form = document.getElementById('oe_exam_form');
        var timerEl = document.getElementById('oe_timer');
        var barEl = document.getElementById('oe_timer_bar');
        var saveEl = document.getElementById('oe_save_state');
        var timeoutEl = document.getElementById('oe_timeout');
        var csrf = root.dataset.csrf;
        var answerUrl = root.dataset.answerUrl;
        var deadline = Date.now() + parseInt(root.dataset.remaining, 10) * 1000;
        var done = false;

        function submitNow(isTimeout) {
            if (done) { return; }
            done = true;
            if (isTimeout && timeoutEl) { timeoutEl.value = '1'; }
            form.submit();
        }

        function tick() {
            var left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
            timerEl.textContent = fmt(left);
            if (barEl) {
                barEl.classList.toggle('bg-danger', left <= 30);
                barEl.classList.toggle('bg-warning', left > 30 && left <= 60);
            }
            if (left <= 0) { submitNow(true); }
        }
        setInterval(tick, 500);
        tick();

        form.addEventListener('submit', function () { done = true; });

        root.querySelectorAll('input[type=radio]').forEach(function (radio) {
            radio.addEventListener('change', function () {
                var fd = new FormData();
                fd.append('csrf_token', csrf);
                fd.append('line_id', radio.dataset.lineId);
                fd.append('option', radio.value);
                if (saveEl) { saveEl.textContent = 'Saving...'; }
                fetch(answerUrl, { method: 'POST', body: fd, credentials: 'same-origin' })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d && d.ok) {
                            if (saveEl) { saveEl.textContent = 'Saved'; }
                            if (typeof d.remaining === 'number') {
                                deadline = Date.now() + d.remaining * 1000;   /* re-sync with server */
                            }
                        } else {
                            window.location.reload();   /* time over / attempt closed */
                        }
                    })
                    .catch(function () {
                        if (saveEl) { saveEl.textContent = 'Not saved - check connection'; }
                    });
            });
        });
    }

    /* Works whether the script is loaded before or after the DOM is ready */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
