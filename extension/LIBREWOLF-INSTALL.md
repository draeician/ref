# Firefox / LibreWolf install (Copy Tab URLs)

## Build the package

From the repo root:

```bash
./scripts/build-firefox.sh
```

Produces (example):

```text
dist/ref-copy-tab-urls-firefox-v1.1.0.xpi
```

The XPI is an **uncompressed** zip (Gecko-friendly) with a MV2 manifest using
`background.scripts` and `browser_specific_settings.gecko`.

## Temporary install (easiest for testing)

1. Open LibreWolf or Firefox  
2. Go to `about:debugging#/runtime/this-firefox`  
3. **Load Temporary Add-on…**  
4. Select the `.xpi` (or `extension/manifest.json` for unpacked)  

Temporary add-ons are removed when the browser restarts.

## Permanent local install (unsigned)

1. `about:config` → set `xpinstall.signatures.required` to **false**  
2. `about:addons` → gear → **Install Add-on From File…**  
3. Choose the `.xpi`  

## Chrome / Chromium

Load `extension/` as an unpacked extension (`chrome://extensions` → Developer mode).
No XPI required.

## Notes

- Use this Firefox XPI for LibreWolf — do not expect a Chrome-only zip to install cleanly.  
- Rebuild the XPI after any change to `extension/` before release commits.
