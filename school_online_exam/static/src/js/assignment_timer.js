/* Countdown for timed assignments. The server decides the real deadline;
 * when the time is over the page reloads and the upload form disappears. */
(function () {
    'use strict';
    function fmt(t) {
        var h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
        var two = function (n) { return (n < 10 ? '0' : '') + n; };
        return (h ? h + ':' : '') + two(m) + ':' + two(s);
    }
    function init() {
        var box = document.getElementById('oe_as_timer');
        if (!box) { return; }
        var deadline = Date.now() + parseInt(box.dataset.remaining, 10) * 1000;
        var done = false;
        function tick() {
            var left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
            box.textContent = fmt(left);
            if (left <= 0 && !done) { done = true; window.location.reload(); }
        }
        setInterval(tick, 500);
        tick();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
