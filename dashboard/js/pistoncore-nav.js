/* PistonCore navigation hook — approved neutralization, SHIM_API_SPEC.md §9.
 * Does NOT modify app.js/dashboard.module.js/piston.module.js. Registers an
 * additional run-block on the EXISTING "webCoRE" Angular module (a standard,
 * first-class Angular API for extending an app from outside its own source)
 * so PistonCore's own front door (served at "/", outside this sealed app)
 * can jump into a specific piston, and so leaving a piston lands back on
 * the front door instead of this app's own list page.
 *
 * Two things happen here, both confirmed necessary by testing 2026-07-12:
 *
 * 1. IN: the list page's own controller is not just a view -- it performs
 *    the session bootstrap (intf/dashboard/load) the piston page depends
 *    on. Redirecting before that call finishes leaves the session empty
 *    and crashes piston.module.js ("data is not defined"). So the real
 *    load must still run; a full-screen overlay (this file's own DOM,
 *    nothing borrowed from the app) just covers the screen while it does,
 *    and lifts once the piston route lands.
 *
 * 2. OUT: the dashboard's own close/save-exit paths navigate to its
 *    internal "/" route via $location.path() -- a client-side Angular
 *    route change, invisible to the server and to PistonCore's front door.
 *    When that happens FROM an already-open piston (not as part of this
 *    hook's own bootstrap pass-through), this cancels that in-app route
 *    change and does a real browser navigation to "/" instead, which exits
 *    the SPA entirely and lands on the real PistonCore front door.
 *
 * 3. BACKUP: three webCoRE UI entry points embed the same cloud-bin-style
 *    import code, which PistonCore doesn't back with a real bins service --
 *    confirmed dead end for PistonCore (Jeremy, 2026-07-12): the dashboard
 *    sidebar's "Backup Piston(s)" links (full + collapsed variants, both
 *    ng-click="backup();") and the piston-view's Snapshot / Anonymized
 *    Snapshot buttons (ng-click="snapshot();" / "snapshot(true);"). All
 *    three are intercepted at the document level in the capture phase
 *    (before Angular's own click binding fires) and redirected to
 *    PistonCore's own /backup page instead -- the underlying functions
 *    never run. "Copy Piston" (textSnapshot()) is untouched -- that one
 *    is CLAUDE.md's own deliberate copy/paste replacement for cloud bins
 *    and already works with no cloud dependency.
 *
 * 4. THEME: syncs PistonCore's own dark/light toggle (static/pistoncore/
 *    theme.js, localStorage "pistoncore_theme") into this app's OWN real
 *    dark mode -- confirmed genuinely vendored and working (the sidebar's
 *    "Toggle Dark Mode" link -> colorSchemeService.toggleDarkMode() ->
 *    $rootScope.setDashboardTheme()/dataService.setDashboardTheme() ->
 *    <body data-theme="{{theme}}"> (index.html:61) -> real CSS variables
 *    in dashboard/css/app.css). Calls those same functions instead of
 *    reimplementing the app's encrypted storage -- no stock file touched,
 *    no new dependency loaded. Waits on dataService.whenReady() and
 *    attaches after colorSchemeService.initialize()'s own callback (both
 *    are .then() on the same promise, so registration order = fire order),
 *    so this always wins if the two disagree.
 */
(function () {
    var MASK_CLASS = 'pistoncore-masking';

    var style = document.createElement('style');
    style.textContent =
        '.' + MASK_CLASS + '-overlay { position: fixed; inset: 0; z-index: 999999; ' +
        'background: #1a1d23; color: #d4dae8; display: flex; align-items: center; ' +
        'justify-content: center; font: 14px system-ui, sans-serif; }';
    document.documentElement.appendChild(style);

    var overlay = null;
    function showOverlay() {
        if (overlay) return;
        overlay = document.createElement('div');
        overlay.className = MASK_CLASS + '-overlay';
        overlay.textContent = 'Loading piston…';
        (document.body || document.documentElement).appendChild(overlay);
    }
    function hideOverlay() {
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        overlay = null;
    }

    // Show immediately if a redirect is already pending from the front door,
    // before Angular has bootstrapped or painted anything.
    if (window.sessionStorage.getItem('pistoncore_open_piston')) {
        if (document.body) showOverlay();
        else document.addEventListener('DOMContentLoaded', showOverlay);
    }

    // BACKUP: see file header, item 3. Pure DOM, no Angular dependency --
    // works regardless of bootstrap timing.
    var BACKUP_SELECTOR = '[ng-click="backup();"], [ng-click="snapshot();"], [ng-click="snapshot(true);"]';
    document.addEventListener('click', function (event) {
        var el = event.target.closest && event.target.closest(BACKUP_SELECTOR);
        if (!el) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        window.location.href = '/backup';
    }, true);

    if (!window.angular || !window.angular.module) return;

    function loadRequestFinished() {
        return window.performance.getEntriesByType('resource')
            .some(function (e) { return e.name.indexOf('intf/dashboard/load') !== -1 && e.responseEnd > 0; });
    }

    angular.module('webCoRE').run(['$rootScope', '$location', '$timeout', 'dataService', function ($rootScope, $location, $timeout, dataService) {

        // THEME: see file header, item 3.
        dataService.whenReady().then(function () {
            var pcTheme = window.localStorage.getItem('pistoncore_theme');
            if (pcTheme && dataService.getDashboardTheme() !== pcTheme) {
                $rootScope.setDashboardTheme(pcTheme);
                dataService.setDashboardTheme(pcTheme);
            }
        });

        // OUT: leaving an already-open piston back to "/" -> exit the SPA
        // for real instead of landing on webCoRE's own list page.
        $rootScope.$on('$routeChangeStart', function (event, next, current) {
            var nextIsList = next && next.$$route && next.$$route.originalPath === '/';
            if (!nextIsList) return;

            var bootstrapPending = window.sessionStorage.getItem('pistoncore_open_piston');
            if (bootstrapPending) return; // this hook's own IN flow, let it proceed

            var cameFromPiston = current && current.$$route && current.$$route.originalPath === '/piston/:pistonId';
            if (cameFromPiston) {
                event.preventDefault();
                window.location.href = '/';
            }
        });

        // IN: jump straight to a specific piston once the list route's own
        // session bootstrap has genuinely finished (see file header).
        $rootScope.$on('$routeChangeSuccess', function (event, current) {
            var target = window.sessionStorage.getItem('pistoncore_open_piston');
            var isListRoute = current && current.$$route && current.$$route.originalPath === '/';
            if (!target || !isListRoute) return;

            showOverlay();
            var attempts = 0;
            function poll() {
                attempts++;
                if (loadRequestFinished()) {
                    window.sessionStorage.removeItem('pistoncore_open_piston');
                    $location.path('/piston/' + target);
                } else if (attempts < 100) {
                    $timeout(poll, 100);
                } else {
                    hideOverlay(); // safety valve: don't hide the app forever
                }
            }
            poll();
        });

        $rootScope.$on('$routeChangeSuccess', function (event, current) {
            var onPistonPage = current && current.$$route && current.$$route.originalPath === '/piston/:pistonId';
            if (onPistonPage) hideOverlay();
        });
    }]);
})();
