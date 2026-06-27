(function () {
    var script = document.currentScript;
    if (!script) {
        var all = document.getElementsByTagName('script');
        script = all[all.length - 1];
    }
    if (!script) {
        return;
    }

    var MESSAGE_TYPE = 'signal-scout-embed-height';

    function measuredHeight() {
        var doc = document.documentElement;
        var body = document.body;
        return Math.ceil(Math.max(
            doc ? doc.scrollHeight : 0,
            doc ? doc.offsetHeight : 0,
            body ? body.scrollHeight : 0,
            body ? body.offsetHeight : 0
        ));
    }

    if (script.getAttribute('data-embed-frame')) {
        var post = function () {
            if (window.parent && window.parent !== window) {
                window.parent.postMessage({ type: MESSAGE_TYPE, height: measuredHeight() }, '*');
            }
        };
        if (document.readyState === 'complete') {
            post();
        } else {
            window.addEventListener('load', post);
        }
        window.addEventListener('resize', post);
        if (window.ResizeObserver && document.body) {
            new ResizeObserver(post).observe(document.body);
        }
        post();
        return;
    }

    var origin;
    try {
        origin = new URL(script.src, window.location.href).origin;
    } catch (e) {
        return;
    }

    var address = (script.getAttribute('data-address') || '').trim();
    var lat = (script.getAttribute('data-lat') || '').trim();
    var lng = (script.getAttribute('data-lng') || '').trim();

    var query = '';
    if (address) {
        query = 'q=' + encodeURIComponent(address);
    } else if (lat && lng) {
        query = 'lat=' + encodeURIComponent(lat) + '&lng=' + encodeURIComponent(lng);
    }

    var iframe = document.createElement('iframe');
    iframe.src = origin + '/embed/coverage' + (query ? '?' + query : '');
    iframe.title = 'Signal-Scout coverage';
    iframe.setAttribute('loading', 'lazy');
    iframe.setAttribute('scrolling', 'no');
    iframe.setAttribute('frameborder', '0');
    iframe.style.width = '100%';
    iframe.style.maxWidth = '520px';
    iframe.style.border = '0';
    iframe.style.height = '340px';
    iframe.style.display = 'block';

    if (script.parentNode) {
        script.parentNode.insertBefore(iframe, script.nextSibling);
    }

    window.addEventListener('message', function (event) {
        if (event.origin !== origin) {
            return;
        }
        if (iframe.contentWindow && event.source !== iframe.contentWindow) {
            return;
        }
        var data = event.data;
        if (!data || data.type !== MESSAGE_TYPE) {
            return;
        }
        var height = parseInt(data.height, 10);
        if (height > 0 && height < 5000) {
            iframe.style.height = height + 'px';
        }
    });
})();
