"""Stealth injection scripts for anti-bot fingerprint bypass.

All scripts are plain JavaScript strings injected via Playwright's
``add_init_script``. They run before any page JavaScript executes.

No external dependencies. No playwright-stealth. Vanilla JS only.
"""

from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# User-Agent pool — recent Chrome versions, multiple OS variants.
# Rotated per session restart for consistency within one persistent context.
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

# Matching navigator.platform per UA substring
_PLATFORM_MAP = {
    "Windows NT": "Win32",
    "Macintosh": "MacIntel",
    "Linux": "Linux x86_64",
}

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1680, "height": 1050},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
]


def pick_user_agent() -> str:
    """Return a random UA from the pool."""
    return random.choice(_USER_AGENTS)


def pick_viewport() -> dict[str, int]:
    """Return a random viewport from the pool."""
    return random.choice(_VIEWPORTS)


def _platform_for_ua(ua: str) -> str:
    for key, platform in _PLATFORM_MAP.items():
        if key in ua:
            return platform
    return "Win32"


def build_stealth_script(ua: str) -> str:
    """Build the comprehensive stealth init script for a given UA.

    The script patches browser fingerprint APIs to avoid detection by
    Cloudflare, DataDome, and similar anti-bot services.
    """
    platform = _platform_for_ua(ua)

    return """
// ================================================================
// navigator.webdriver — remove automation flag
// ================================================================
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// ================================================================
// navigator.plugins — mock real PluginArray with named objects
// ================================================================
(function() {
    const pluginData = [
        {
            name: 'PDF Viewer',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            mimeTypes: [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'text/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ],
        },
        {
            name: 'Chrome PDF Viewer',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            mimeTypes: [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ],
        },
        {
            name: 'Chromium PDF Viewer',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            mimeTypes: [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ],
        },
        {
            name: 'Microsoft Edge PDF Viewer',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            mimeTypes: [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ],
        },
        {
            name: 'WebKit built-in PDF',
            filename: 'internal-pdf-viewer',
            description: 'Portable Document Format',
            mimeTypes: [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            ],
        },
    ];

    function makeMimeType(mt, enabledPlugin) {
        const proto = typeof MimeType !== 'undefined' ? MimeType.prototype : Object.prototype;
        return Object.create(proto, {
            type: { value: mt.type, enumerable: true },
            suffixes: { value: mt.suffixes, enumerable: true },
            description: { value: mt.description, enumerable: true },
            enabledPlugin: { value: enabledPlugin, enumerable: true },
        });
    }

    function makePlugin(data) {
        const proto = typeof Plugin !== 'undefined' ? Plugin.prototype : Object.prototype;
        const plugin = Object.create(proto, {
            name: { value: data.name, enumerable: true },
            filename: { value: data.filename, enumerable: true },
            description: { value: data.description, enumerable: true },
            length: { value: data.mimeTypes.length, enumerable: true },
        });
        data.mimeTypes.forEach((mt, i) => {
            const mimeType = makeMimeType(mt, plugin);
            plugin[i] = mimeType;
        });
        return plugin;
    }

    const plugins = pluginData.map(makePlugin);

    // Build mimeTypes array from all plugins
    const allMimeTypes = [];
    plugins.forEach(p => {
        for (let i = 0; i < p.length; i++) {
            allMimeTypes.push(p[i]);
        }
    });

    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = plugins;
            arr.item = (i) => plugins[i] || null;
            arr.namedItem = (n) => plugins.find(p => p.name === n) || null;
            arr.refresh = () => {};
            return arr;
        },
        configurable: true,
    });

    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const arr = allMimeTypes;
            arr.item = (i) => allMimeTypes[i] || null;
            arr.namedItem = (t) => allMimeTypes.find(m => m.type === t) || null;
            return arr;
        },
        configurable: true,
    });
})();

// ================================================================
// navigator.languages
// ================================================================
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
    configurable: true,
});

// ================================================================
// navigator.platform — must match UA
// ================================================================
Object.defineProperty(navigator, 'platform', {
    get: () => '__PLATFORM__',
    configurable: true,
});

// ================================================================
// navigator.hardwareConcurrency / deviceMemory
// ================================================================
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: true,
});
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
    configurable: true,
});

// ================================================================
// navigator.connection
// ================================================================
if (!navigator.connection) {
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
            saveData: false,
            addEventListener: () => {},
            removeEventListener: () => {},
        }),
        configurable: true,
    });
}

// ================================================================
// window.chrome — full mock
// ================================================================
if (!window.chrome) {
    window.chrome = {};
}
window.chrome.runtime = window.chrome.runtime || {
    OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', UPDATE: 'update'},
    PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd'},
    ConnectError: { INCOGNITO: 'incognito', MISSING: 'missing', PERMISSIONS: 'permissions'},
    PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64'},
};
window.chrome.app = window.chrome.app || { isInstalled: false, InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'}, RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}, getDetails: () => null, getIsInstalled: () => false};
window.chrome.csi = window.chrome.csi || (() => ({ onloadT: Date.now(), startE: Date.now(), pageT: 0, tran: 15 }));
window.chrome.loadTimes = window.chrome.loadTimes || (() => ({
    commitLoadTime: Date.now() / 1000 - 5,
    connectionInfo: 'h2',
    connectionreused: true,
    finishDocumentLoadTime: Date.now() / 1000 - 2,
    finishLoadTime: Date.now() / 1000 - 1,
    firstPaintAfterLoadTime: 0,
    firstPaintTime: Date.now() / 1000 - 4,
    navigationType: 'Other',
    npnNegotiatedProtocol: 'h2',
    requestTime: Date.now() / 1000 - 10,
    startLoadTime: Date.now() / 1000 - 8,
    wasAlternateProtocolAvailable: false,
    wasFetchedViaSpdy: true,
    wasNpnNegotiated: true,
}));

// ================================================================
// Permissions API — override Notification permission query
// ================================================================
if (navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) => {
        if (params && params.name === 'notifications') {
            return Promise.resolve({ state: 'prompt', onchange: null });
        }
        return origQuery(params);
    };
}

// ================================================================
// WebGL — spoof renderer and vendor
// ================================================================
(function() {
    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    const getParameterOverride = function(parameter) {
        // UNMASKED_VENDOR_WEBGL
        if (parameter === 37445) return 'Google Inc. (Intel)';
        // UNMASKED_RENDERER_WEBGL
        if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameterProto.call(this, parameter);
    };
    WebGLRenderingContext.prototype.getParameter = getParameterOverride;
    if (typeof WebGL2RenderingContext !== 'undefined') {
        WebGL2RenderingContext.prototype.getParameter = getParameterOverride;
    }
})();

// ================================================================
// AudioContext — add subtle noise to prevent fingerprinting
// ================================================================
(function() {
    const origCreateOscillator = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function() {
        const result = origCreateOscillator.apply(this, arguments);
        // Add tiny noise to first sample block only (enough to change hash)
        if (result.length > 0) {
            result[0] = result[0] + (Math.random() - 0.5) * 1e-7;
        }
        return result;
    };
})();

// ================================================================
// Canvas — inject noise into toDataURL / getImageData / toBlob
// Upgraded: multi-pixel random noise (ported from Scrapling/patchright approach)
// ================================================================
(function() {
    // Deterministic per-session noise seed
    const noiseSeed = Math.floor(Math.random() * 1000) + 1;

    function addNoiseToImageData(imageData) {
        const data = imageData.data;
        // Add subtle noise to multiple random pixels (not just 1)
        const pixelCount = data.length / 4;
        const noisePixels = Math.min(10, Math.max(1, Math.floor(pixelCount / 100)));
        for (let i = 0; i < noisePixels; i++) {
            const idx = (Math.floor(Math.random() * pixelCount)) * 4;
            // XOR each channel with a small random value (1-3)
            data[idx]     = (data[idx]     ^ ((noiseSeed + i) % 3 + 1)) & 0xFF;
            data[idx + 1] = (data[idx + 1] ^ ((noiseSeed + i * 2) % 3 + 1)) & 0xFF;
            data[idx + 2] = (data[idx + 2] ^ ((noiseSeed + i * 3) % 3 + 1)) & 0xFF;
        }
    }

    // Patch toDataURL
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d');
        if (ctx) {
            const width = this.width;
            const height = this.height;
            if (width > 0 && height > 0) {
                try {
                    const imageData = ctx.getImageData(0, 0, Math.min(width, 100), Math.min(height, 100));
                    addNoiseToImageData(imageData);
                    ctx.putImageData(imageData, 0, 0);
                } catch(e) { /* CORS or small canvas */ }
            }
        }
        return origToDataURL.apply(this, arguments);
    };

    // Patch toBlob (used by some fingerprinters)
    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    if (origToBlob) {
        HTMLCanvasElement.prototype.toBlob = function() {
            const ctx = this.getContext('2d');
            if (ctx) {
                const width = this.width;
                const height = this.height;
                if (width > 0 && height > 0) {
                    try {
                        const imageData = ctx.getImageData(0, 0, Math.min(width, 100), Math.min(height, 100));
                        addNoiseToImageData(imageData);
                        ctx.putImageData(imageData, 0, 0);
                    } catch(e) { /* CORS or small canvas */ }
                }
            }
            return origToBlob.apply(this, arguments);
        };
    }

    // Patch getImageData (used directly by fingerprinters)
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function() {
        const imageData = origGetImageData.apply(this, arguments);
        try {
            addNoiseToImageData(imageData);
        } catch(e) { /* read-only */ }
        return imageData;
    };
})();

// ================================================================
// WebRTC — prevent local IP leakage
// ================================================================
(function() {
    const origRTC = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (origRTC) {
        const patchedRTC = function(config, constraints) {
            if (config && config.iceServers) {
                config.iceTransportPolicy = 'relay';
            }
            return new origRTC(config, constraints);
        };
        patchedRTC.prototype = origRTC.prototype;
        window.RTCPeerConnection = patchedRTC;
        if (window.webkitRTCPeerConnection) {
            window.webkitRTCPeerConnection = patchedRTC;
        }
    }
})();

// ================================================================
// Notification.permission
// ================================================================
if (window.Notification) {
    Object.defineProperty(Notification, 'permission', {
        get: () => 'default',
        configurable: true,
    });
}
""".replace("__PLATFORM__", platform)


# ---------------------------------------------------------------------------
# Launch args — Chromium flags for stealth + stability
# ---------------------------------------------------------------------------

STEALTH_LAUNCH_ARGS = [
    # Core anti-detection (from patchright)
    "--disable-blink-features=AutomationControlled",
    # WebRTC leak prevention (from Scrapling)
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--force-webrtc-ip-handling-policy",
    # Canvas fingerprint noise (from Scrapling)
    "--fingerprinting-canvas-image-data-noise",
    # Speed + stability
    "--no-sandbox",
    "--no-first-run",
    "--no-pings",
    "--no-default-browser-check",
    "--no-service-autorun",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-hang-monitor",
    "--disable-search-engine-choice-screen",
    "--disable-session-crashed-bubble",
    # Anti-detection stealth flags (from Scrapling STEALTH_ARGS)
    "--disable-features=IsolateOrigins,site-per-process",
    "--start-maximized",
    "--window-position=0,0",
    "--mute-audio",
    "--disable-sync",
    "--disable-translate",
    "--disable-logging",
    "--disable-crash-reporter",
    "--disable-domain-reliability",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--disable-client-side-phishing-detection",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--metrics-recording-only",
    "--force-color-profile=srgb",
    "--password-store=basic",
    "--use-mock-keychain",
    "--autoplay-policy=user-gesture-required",
    "--homepage=about:blank",
]

# ──────────────────────────────────────────────────────────────────────────────
# HARMFUL_ARGS — Chromium flags that leak automation (from Scrapling/patchright)
# These must be REMOVED from Playwright's default args before launch.
# ──────────────────────────────────────────────────────────────────────────────
HARMFUL_ARGS = (
    "--enable-automation",              # Sets navigator.webdriver = true
    "--disable-popup-blocking",         # Popup crashing abuse detection
    "--disable-component-update",       # Detected as stealth driver
    "--disable-default-apps",           # Enables default apps check
    "--disable-extensions",             # Enables extensions (needed for stealth)
)


def filter_harmful_args(default_args: list[str]) -> list[str]:
    """Remove harmful automation flags from Playwright's default launch args."""
    return [arg for arg in default_args if not any(harmful in arg for harmful in HARMFUL_ARGS)]
