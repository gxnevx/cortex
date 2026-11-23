"""Piloto manual do navegador do CORTEX (perfil data/navegador), um passo por vez.

Uso (cwd = raiz do projeto):
  python tests/nav.py abrir <url>            abre/reutiliza o Chrome do CORTEX em modo controlado e vai para a url
  python tests/nav.py print <arquivo.png>    tira print da aba atual
  python tests/nav.py texto                  mostra os textos clicaveis/campos da aba atual
  python tests/nav.py clicar "<texto ou css>"
  python tests/nav.py preencher "<css>" "<texto>"
  python tests/nav.py fechar                 fecha o Chrome controlado
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica.config import load_config  # noqa: E402
from fabrica.publish import browser as br  # noqa: E402


def connect():
    from playwright.sync_api import sync_playwright

    cfg = load_config()
    port = br.devtools_port()
    if not port:
        br._launch_debug_browser(cfg, headless=False)
        for _ in range(40):
            port = br.devtools_port()
            if port:
                break
            time.sleep(0.5)
    pw = sync_playwright().start()
    b = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", is_local=True, no_defaults=True)
    ctx = b.contexts[0]
    page = ctx.pages[-1] if ctx.pages else ctx.new_page()
    return pw, b, page


def main():
    cmd = sys.argv[1]
    if cmd == "fechar":
        port = br.devtools_port()
        if port:
            br._close_debug_browser(port)
        print("fechado")
        return
    pw, b, page = connect()
    try:
        if cmd == "abrir":
            page.goto(sys.argv[2], wait_until="domcontentloaded", timeout=60000)
            time.sleep(4)
            print("url:", page.url)
        elif cmd == "print":
            page.screenshot(path=sys.argv[2])
            print("print:", sys.argv[2], "| url:", page.url)
        elif cmd == "texto":
            info = page.evaluate("""() => {
              const out = [];
              for (const el of document.querySelectorAll('button, a[role=button], [role=button], input, textarea, [contenteditable=true]')) {
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                const t = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 60);
                const id = el.id ? '#' + el.id : '';
                const de = el.getAttribute('data-e2e') ? '[data-e2e=' + el.getAttribute('data-e2e') + ']' : '';
                out.push(el.tagName.toLowerCase() + id + de + ' | ' + t.replace(/\\s+/g, ' '));
              }
              return out.slice(0, 80);
            }""")
            print("\n".join(info))
        elif cmd == "clicar":
            alvo = sys.argv[2]
            loc = page.locator(alvo) if alvo[:1] in "#.[" or alvo.startswith(("button", "textarea", "input", "div")) \
                else page.get_by_text(alvo, exact=False)
            loc.first.click(timeout=15000)
            time.sleep(2)
            print("clicou:", alvo)
        elif cmd == "preencher":
            loc = page.locator(sys.argv[2]).first
            loc.click(timeout=15000)
            loc.fill("")
            loc.type(sys.argv[3], delay=25)
            time.sleep(1)
            print("preencheu:", sys.argv[2], "| valor:", json.dumps(loc.input_value() if loc.evaluate("e => 'value' in e") else loc.inner_text())[:200])
    finally:
        b.close() if False else None  # nao fecha o Chrome: so desconecta
        pw.stop()


if __name__ == "__main__":
    main()
