"""Gera config.exemplo.yaml a partir do config.yaml SEM dados pessoais (contas, e-mail, @, marca)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    src = (ROOT / "config.yaml").read_text(encoding="utf-8")
    out = src
    # contas: zera nome, @ e e-mail; criada_em vazia
    out = re.sub(r'(\n\s+youtube:\s*)\{criada_em:[^}]*\}', r'\1{criada_em: ""}', out)
    out = re.sub(r'(\n\s+tiktok:\s*)\{criada_em:[^}]*\}', r'\1{criada_em: ""}', out)
    out = re.sub(r'\n\s+instagram:\s*\{criada_em:[^}]*\}', '\n    instagram: {criada_em: ""}', out)
    out = out.replace("plataformas: [youtube, tiktok, instagram]", "plataformas: [youtube, tiktok]   # + instagram para postar Reels")
    # indicacoes do dono: so o formato
    out = re.sub(r'(\n  indicados:)\n(?:    .*\n)+', r'\1 []                   # ex.: - {canal: "@handle", nome: "NOME", gosto: "que momentos cortar"}\n', out)
    # marca
    out = re.sub(r'(\n\s+marca_dagua:\s*)"[^"]*"', r'\1""', out)
    # qualquer e-mail ou @ que tenha escapado em comentarios/valores
    out = re.sub(r'[\w.+-]+@gmail\.com', '', out)
    (ROOT / "config.exemplo.yaml").write_text(out, encoding="utf-8")
    sobra = re.findall(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+[.][a-z]+|handle: "@[^"]+"', out)
    print("config.exemplo.yaml gerado" + (f" (ATENCAO, sobrou: {set(sobra)})" if sobra else " sem dados pessoais"))


if __name__ == "__main__":
    main()
