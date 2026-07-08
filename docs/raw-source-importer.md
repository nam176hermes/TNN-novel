# Raw Source Importer

Novel-TNN can import public raw Chinese novel chapters from supported source domains, then translate them through the existing provider pipeline.

Supported first-pass sources:
- 69shuba / 69shux
- biquge / 22biqu
- uukanshu
- 17k

Workflow:
1. Open the app.
2. Go to Import.
3. Choose URL mode.
4. Paste the book URL.
5. Preview metadata and chapter list.
6. Select chapters or ranges.
7. Start import.
8. Translate imported chapters from Jobs or Workbench.

If a source shows captcha, cooldown, or anti-spam text, the app reports a blocked source state instead of saving that page as raw novel text. Open the page manually and use the browser helper to send visible text into Novel-TNN.

This importer does not bypass captcha, rotate proxies, evade anti-bot systems, unlock paywalled chapters, or bypass DRM.
