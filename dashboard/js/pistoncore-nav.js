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
 *    EXCEPTION: piston.module.js's resumeImport() also routes to "/" from
 *    an open piston, but to open the list page's own native "+New" import
 *    dialog (webCoRE's real import-review UI, confirmed 2026-07-12 --
 *    only exists on that native screen, nowhere else). When
 *    $rootScope.dashboardResumeImport is set, this hook steps aside and
 *    lets that in-app route change proceed instead of hijacking it.
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
        'justify-content: center; font: 14px system-ui, sans-serif; }' +
        // LOGO: PistonCore is the product identity users see; webCoRE's own
        // branding (top-of-content <logo> element, dashboard.module.html:2,
        // and the sidebar's <li class="logo"> mark+wordmark, :104) is hidden
        // everywhere in the sealed app, not just during the import detour --
        // additive CSS only, no sealed file touched (Jeremy, 2026-07-12).
        'logo, li.logo { display: none !important; }';
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

            // resumeImport() (piston.module.js) sets this then routes to "/"
            // itself to open the list page's own "+New" import dialog --
            // that dialog only exists on webCoRE's native list screen, so
            // this exit hook must not hijack it to the PistonCore front door.
            if ($rootScope.dashboardResumeImport) return;

            var cameFromPiston = current && current.$$route && current.$$route.originalPath === '/piston/:pistonId';
            if (cameFromPiston) {
                event.preventDefault();
                window.location.href = '/';
            }
        });

        // STAGED JSON IMPORT (import/export page): feed the pasted piston into
        // webCoRE's OWN import flow so its Rebuild-piston-items dialog forces a
        // device remap before anything is saved — imported pistons can never
        // land (or display) raw hash ids (house rule: friendly names only).
        $rootScope.$on('$routeChangeSuccess', function (event, current) {
            var staged = window.sessionStorage.getItem('pistoncore_stage_import');
            var isListRoute = current && current.$$route && current.$$route.originalPath === '/';
            if (!staged || !isListRoute) return;
            window.sessionStorage.removeItem('pistoncore_stage_import');
            var obj;
            try { obj = JSON.parse(staged); } catch (e) { return; }
            var entry = {
                meta: { id: 'pcimport' + Date.now(), name: obj.name, author: '' },
                piston: obj.piston, warnings: [], warningLevel: 0
            };
            var attempts = 0;
            function pollStage() {
                attempts++;
                var el = document.querySelector('[ng-click="newPiston();"]');
                if (loadRequestFinished() && el && window.angular) {
                    var scope = angular.element(el).scope();
                    if (scope && scope.resumeImport) {
                        dataService.setImportedData([entry]).then(function () {
                            scope.$applyAsync(function () { scope.resumeImport(); });
                        });
                        return;
                    }
                }
                if (attempts < 100) $timeout(pollStage, 100);
            }
            pollStage();
        });

        // NEW-PISTON DIALOG: the front door's "+ New Piston" sets this flag —
        // once the list route's bootstrap finishes, open webCoRE's own
        // New-Piston dialog (native blank/Duplicate/restore-code/import-file
        // paths; there is no other menu that reaches it in PistonCore). The
        // list page stays visible behind the dialog — pass-through per
        // CLAUDE.md. Cancelling the dialog exits back to the front door.
        $rootScope.$on('$routeChangeSuccess', function (event, current) {
            var wantDialog = window.sessionStorage.getItem('pistoncore_open_newpiston');
            var isListRoute = current && current.$$route && current.$$route.originalPath === '/';
            if (!wantDialog || !isListRoute) return;
            window.sessionStorage.removeItem('pistoncore_open_newpiston');

            var attempts = 0;
            function pollDialog() {
                attempts++;
                // the sidebar's own New Piston control exists once the list
                // controller has rendered; its scope carries newPiston()
                var el = document.querySelector('[ng-click="newPiston();"]');
                if (loadRequestFinished() && el && window.angular) {
                    var scope = angular.element(el).scope();
                    if (scope && scope.newPiston) {
                        scope.$applyAsync(function () { scope.newPiston(); });
                        return;
                    }
                }
                if (attempts < 100) $timeout(pollDialog, 100);
            }
            pollDialog();
        });

        // Leaving the New-Piston dialog without creating anything (Cancel/X)
        // strands the user on webCoRE's list page — exit to the front door
        // instead. createPiston() navigates to /piston/<id> ~100ms after
        // closing the dialog, so wait long enough to tell the two apart.
        $rootScope.$on('ngDialog.closed', function () {
            $timeout(function () {
                var onListRoute = $location.path() === '/' || $location.path() === '';
                var dialogStillOpen = !!document.querySelector('.ngdialog');
                if (onListRoute && !dialogStillOpen) window.location.href = '/';
            }, 600);
        });

        // DEVICE-GLOBAL PROMPT: changing a device global's devices leaves the
        // pistons that use it compiled against the OLD list. The save
        // response names them; ask whether to update now or leave it for a
        // manual save (Jeremy 2026-07-19: prompt, auto or manual — never
        // silent, and never a block on saving the variable itself).
        (function () {
            var origOpen = XMLHttpRequest.prototype.open;
            var origSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function (m, url) {
                this.__pcUrl = url;
                return origOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function () {
                var xhr = this;
                var NL = String.fromCharCode(10);
                if (String(xhr.__pcUrl || "").indexOf("variable/set") !== -1) {
                    xhr.addEventListener("load", function () {
                        var m = /callback\((.*)\)/s.exec(xhr.responseText || "");
                        if (!m) return;
                        var data;
                        try { data = JSON.parse(m[1]); } catch (e) { return; }
                        var list = data && data.affected;
                        if (!list || !list.length) return;
                        var names = list.map(function (p) { return p.name || p.id; });
                        var msg = list.length + " piston" + (list.length > 1 ? "s use " : " uses ") +
                            (data.variable || "this variable") + ":" + NL + NL +
                            names.join(NL) + NL + NL +
                            "Home Assistant is still running them with the previous " +
                            "devices. Update them now?" + NL + NL +
                            "OK = update now.  Cancel = leave them (each updates on its next save).";
                        if (!window.confirm(msg)) return;
                        var ids = list.map(function (p) { return p.id; }).join(",");
                        var s = document.createElement("script");
                        s.src = "/intf/dashboard/variable/recompile?ids=" +
                                encodeURIComponent(ids) + "&callback=pcRecompiled";
                        window.pcRecompiled = function (res) {
                            var bad = (res.recompiled || []).filter(function (r) {
                                return r.status !== "deployed";
                            });
                            window.alert(bad.length
                                ? "Updated with problems:" + NL + NL + bad.map(function (b) {
                                      return "- " + (b.message || b.status);
                                  }).join(NL)
                                : "Updated " + (res.recompiled || []).length +
                                  " piston(s) in Home Assistant.");
                        };
                        document.body.appendChild(s);
                    });
                }
                return origSend.apply(this, arguments);
            };
        })();

        // COMPILE BANNER: the piston status screen is announcement surface #2
        // (CLAUDE.md UI split — same screen as Status/Quick Facts, where a
        // webCoRE user expects a piston's problems). Injected as a sibling of
        // the template's own hardcoded .alert banners (piston.module.html
        // :129-133) — additive DOM only, no sealed file touched. Polls while
        // on the piston page so a save's compile result appears in seconds
        // (and survives the view->edit->view mode switch, which rebuilds the
        // container without a route change).
        var compilePoll = null;
        function clearCompileBanner() {
            if (compilePoll) { clearInterval(compilePoll); compilePoll = null; }
            var old = document.getElementById('pistoncore-compile-banner');
            if (old && old.parentNode) old.parentNode.removeChild(old);
        }
        function renderCompileBanner(rec) {
            var container = document.querySelector('div.container[ng-if="mode==\'view\'"]');
            var old = document.getElementById('pistoncore-compile-banner');
            if (!container) { if (old && old.parentNode) old.parentNode.removeChild(old); return; }
            var isError = rec && rec.status === 'error';
            var isDeployed = rec && rec.status === 'deployed';
            if (!isError && !isDeployed) { if (old && old.parentNode) old.parentNode.removeChild(old); return; }
            var div = document.createElement('div');
            div.id = 'pistoncore-compile-banner';
            div.className = 'alert ' + (isError ? 'alert-danger' : 'alert-success');
            var strong = document.createElement('strong');
            strong.textContent = isError ? 'PistonCore compile error: ' : 'PistonCore: ';
            div.appendChild(strong);
            var span = document.createElement('span');
            span.textContent = isError
                ? (rec.message || rec.code || 'compile failed')
                : ('compiled & deployed to Home Assistant'
                   + (rec.file ? ' (' + rec.file + ')' : '')
                   + (rec.band === 'pyscript' ? ' [PyScript]' : ''));
            div.appendChild(span);
            if (isError) {
                div.appendChild(document.createTextNode(' '));
                var link = document.createElement('a');
                link.href = '/help/compiler-debug';
                link.className = 'alert-link';
                link.textContent = 'Help →';
                // real browser navigation — Angular's router otherwise hijacks
                // the click and dumps the user on its own default list page
                link.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    window.location.href = '/help/compiler-debug';
                }, true);
                div.appendChild(link);
            }
            if (old && old.parentNode) old.parentNode.removeChild(old);
            container.insertBefore(div, container.firstChild);

            // TRUTH FIX: the sealed Status card's "active and humming happily"
            // only knows webCoRE save-state, not HA reality — override the
            // sentence while the compile is failed, restore it once fixed.
            var statusP = document.querySelector('#collapseCards div[ng-if="meta.active"] > p');
            if (statusP) {
                if (!statusP.dataset.pistoncoreOriginal) {
                    statusP.dataset.pistoncoreOriginal = statusP.textContent;
                }
                statusP.textContent = isError
                    ? 'This piston is saved and active, but its compile to Home ' +
                      'Assistant FAILED — it is NOT currently running. See the ' +
                      'error above.'
                    : statusP.dataset.pistoncoreOriginal;
            }
        }
        $rootScope.$on('$routeChangeSuccess', function (event, current) {
            clearCompileBanner();
            var onPiston = current && current.$$route && current.$$route.originalPath === '/piston/:pistonId';
            if (!onPiston || !current.params) return;
            var pid = current.params.pistonId;
            function refresh() {
                fetch('/api/compile-status/' + encodeURIComponent(pid))
                    .then(function (r) { return r.json(); })
                    .then(renderCompileBanner)
                    .catch(function () {});
            }
            refresh();
            compilePoll = setInterval(refresh, 5000);
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
