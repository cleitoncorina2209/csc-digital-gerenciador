"""
gerenciador_produtos.py
------------------------
Versao com interface visual do montar_produtos.py - roda no navegador
em vez do terminal preto e branco.

COMO USAR
---------
pip install flask requests beautifulsoup4
python gerenciador_produtos.py

Abre sozinho uma aba no seu navegador em http://127.0.0.1:5000
Deixa esse terminal aberto rodando por trás (pode minimizar) enquanto
usa a tela no navegador. Pra fechar, volta no terminal e aperta Ctrl+C.

Salva tudo em "produtos.json", igual antes - continua funcionando
com o achadinhos.html sem precisar mudar nada la.
"""

import json
import os
import threading
import time
import webbrowser
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS

PASTA = Path(__file__).parent
ARQ_SAIDA_JSON = PASTA / "produtos.json"

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

app = Flask(__name__)
CORS(app)  # libera o Netlify (ou qualquer site) buscar os produtos daqui

# Plano B pra quando a pagina nao tiver a categoria oficial do ML (raro, mas
# pode acontecer). Baseado em palavras que costumam aparecer no titulo.
CATEGORIAS_PALAVRAS = {
    "Eletrônicos": ["tv", "smart tv", "fone", "bluetooth", "celular", "smartphone",
                     "notebook", "câmera", "carregador", "caixa de som", "controle",
                     "mouse", "teclado", "monitor", "tablet", "smartwatch"],
    "Casa e Decoração": ["organizador", "luminária", "cortina", "tapete", "panela",
                          "utensílio", "cama", "travesseiro", "toalha", "cozinha"],
    "Beleza e Cuidados": ["shampoo", "creme", "perfume", "maquiagem", "escova",
                           "hidratante", "protetor solar", "batom"],
    "Esporte e Fitness": ["creatina", "whey", "suplemento", "halter", "tênis",
                           "academia", "proteína", "yoga", "musculação"],
    "Brinquedos": ["boneca", "brinquedo", "lego", "pelúcia", "infantil"],
}


def categoria_por_palavras(titulo):
    if not titulo:
        return "Outros"
    titulo_lower = titulo.lower()
    for categoria, palavras in CATEGORIAS_PALAVRAS.items():
        if any(p in titulo_lower for p in palavras):
            return categoria
    return "Outros"


def extrair_categoria_oficial(soup):
    """O Mercado Livre coloca a categoria do produto (Eletronicos > TVs > ...)
    num JSON-LD do tipo BreadcrumbList. Pegamos o primeiro nivel (o mais
    generico), que fica bom pra usar como categoria principal do site."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        itens = dados if isinstance(dados, list) else [dados]
        for item in itens:
            if isinstance(item, dict) and item.get("@type") == "BreadcrumbList":
                elementos = item.get("itemListElement", [])
                elementos = sorted(elementos, key=lambda x: x.get("position", 0))
                for el in elementos:
                    nome = el.get("name")
                    if not nome and isinstance(el.get("item"), dict):
                        nome = el["item"].get("name")
                    if nome:
                        return nome.strip()
    return None


# ============================================================
# LOGICA (igual ao montar_produtos.py)
# ============================================================

def limpar_preco(texto):
    if texto is None:
        return ""
    texto = str(texto).replace("R$", "").replace("r$", "").strip()
    if "." in texto and "," in texto:
        texto = texto.replace(".", "")
    return texto.replace(".", ",")


def corrigir_ordem_precos(preco_atual, preco_antigo):
    if not preco_antigo:
        return preco_atual, preco_antigo
    try:
        atual_num = float(str(preco_atual).replace(",", "."))
        antigo_num = float(str(preco_antigo).replace(",", "."))
    except (ValueError, AttributeError):
        return preco_atual, preco_antigo
    if antigo_num < atual_num:
        return preco_antigo, preco_atual
    return preco_atual, preco_antigo


def buscar_dados_pagina(url):
    try:
        resposta = requests.get(url, headers=CABECALHOS, timeout=10)
    except requests.RequestException as e:
        return {"erro": f"Nao consegui abrir o link: {e}"}

    if resposta.status_code != 200:
        return {"erro": f"A pagina respondeu {resposta.status_code} (pode estar bloqueando)"}

    soup = BeautifulSoup(resposta.text, "html.parser")

    titulo = None
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        titulo = og_title["content"].strip()
    if not titulo:
        h1 = soup.find("h1")
        if h1:
            titulo = h1.get_text(strip=True)

    imagem = None
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        imagem = og_image["content"].strip()

    preco = None
    for script in soup.find_all("script", type="application/ld+json"):
        if preco:
            break
        try:
            dados = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        itens = dados if isinstance(dados, list) else [dados]
        for item in itens:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict) and offers.get("price"):
                preco = offers["price"]
                break
            if isinstance(offers, list):
                for oferta in offers:
                    if isinstance(oferta, dict) and oferta.get("price"):
                        preco = oferta["price"]
                        break
            if preco:
                break
    if preco is not None:
        try:
            preco = f"{float(preco):.2f}"
        except (TypeError, ValueError):
            preco = str(preco)

    preco_antigo_json = None  # caso o JSON-LD tambem informe o preco "de antes"

    if not preco:
        preco, preco_antigo_json = extrair_precos_da_pagina(soup)

    if not (titulo or imagem or preco):
        return {"erro": "Nao encontrei nada nessa pagina."}

    categoria = extrair_categoria_oficial(soup) or categoria_por_palavras(titulo)

    return {
        "titulo": titulo or "",
        "imagem": imagem or "",
        "preco": limpar_preco(preco) if preco else "",
        "precoAntigo": limpar_preco(preco_antigo_json) if preco_antigo_json else "",
        "categoria": categoria,
    }


def extrair_precos_da_pagina(soup):
    """Le os precos direto do HTML da pagina, diferenciando o preco
    RISCADO (antigo/original) do preco ATUAL (o que realmente se paga).

    O Mercado Livre mostra os dois preços com a mesma classe CSS
    (andes-money-amount__fraction), entao pegar so o primeiro que
    aparece no codigo da pagina pega errado (o riscado costuma vir
    primeiro). Aqui a gente verifica se o preco esta dentro de uma
    tag <s>/<del> ou de um elemento com classe "previous" - isso
    indica que e o preco riscado, nao o atual.
    """
    atual = None
    antigo = None

    for frac in soup.find_all(class_="andes-money-amount__fraction"):
        eh_riscado = False
        for ancestral in frac.parents:
            if getattr(ancestral, "name", None) in ("s", "del"):
                eh_riscado = True
                break
            classes = ancestral.get("class", []) if hasattr(ancestral, "get") else []
            if classes and any("previous" in c for c in classes):
                eh_riscado = True
                break

        valor = frac.get_text(strip=True)
        container = frac.find_parent(class_=lambda c: bool(c) and "andes-money-amount" in c)
        if container:
            cents_el = container.find(class_="andes-money-amount__cents")
            if cents_el:
                valor = f"{valor},{cents_el.get_text(strip=True)}"

        if eh_riscado and antigo is None:
            antigo = valor
        elif not eh_riscado and atual is None:
            atual = valor

        if atual and antigo:
            break

    return atual, antigo


def carregar_catalogo():
    if ARQ_SAIDA_JSON.exists():
        try:
            with open(ARQ_SAIDA_JSON, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def salvar_catalogo(catalogo):
    with open(ARQ_SAIDA_JSON, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)


# ============================================================
# ROTAS DA API
# ============================================================

@app.route("/api/buscar", methods=["POST"])
def rota_buscar():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"erro": "Cole um link primeiro."}), 400
    resultado = buscar_dados_pagina(url)
    return jsonify(resultado)


@app.route("/api/produtos", methods=["GET"])
def rota_listar():
    return jsonify(carregar_catalogo())


@app.route("/api/produtos", methods=["POST"])
def rota_adicionar():
    dados = request.json or {}
    catalogo = carregar_catalogo()

    preco_atual = limpar_preco(dados.get("precoAtual", ""))
    preco_antigo = limpar_preco(dados.get("precoAntigo", ""))
    preco_atual, preco_antigo = corrigir_ordem_precos(preco_atual, preco_antigo)

    produto = {
        "titulo": dados.get("titulo", "").strip(),
        "imagem": dados.get("imagem", "").strip(),
        "precoAtual": preco_atual,
        "precoAntigo": preco_antigo,
        "selo": dados.get("selo", "").strip(),
        "link": dados.get("link", "").strip(),
        "categoria": dados.get("categoria", "").strip() or "Outros",
    }

    if not produto["titulo"] or not produto["link"]:
        return jsonify({"erro": "Titulo e link sao obrigatorios."}), 400

    catalogo.append(produto)
    salvar_catalogo(catalogo)
    return jsonify(carregar_catalogo())


@app.route("/api/produtos/<int:indice>", methods=["DELETE"])
def rota_remover(indice):
    catalogo = carregar_catalogo()
    if 0 <= indice < len(catalogo):
        catalogo.pop(indice)
        salvar_catalogo(catalogo)
        return jsonify(catalogo)
    return jsonify({"erro": "Produto nao encontrado."}), 404


# ============================================================
# PAGINA (HTML embutido, mesma linha visual do achadinhos.html)
# ============================================================

PAGINA_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gerenciar Produtos · CSC.Digital</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  :root{
    --amarelo:#FFE600; --azul:#3483FA; --azul-escuro:#2968C8;
    --verde:#00A650; --vermelho:#E53935; --fundo:#EBEBEB;
    --card:#FFFFFF; --texto:#333333; --texto-claro:#666666; --borda:#E0E0E0;
  }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ background:var(--fundo); color:var(--texto); font-family:'Inter',sans-serif; }
  .topbar{ background:var(--amarelo); padding:16px 24px; display:flex; align-items:center; gap:12px; }
  .topbar .logo{ font-weight:800; font-size:19px; }
  .topbar .logo span{ color:var(--azul-escuro); }
  .container{ max-width:960px; margin:0 auto; padding:28px 20px 80px; }

  .painel{ background:var(--card); border:1px solid var(--borda); border-radius:10px; padding:22px; margin-bottom:28px; }
  .painel h2{ font-size:16px; font-weight:700; margin-bottom:16px; }

  .linha{ display:flex; gap:10px; margin-bottom:12px; }
  .linha input{ flex:1; }
  input, select{
    width:100%; padding:10px 12px; border:1px solid var(--borda); border-radius:6px;
    font-size:14px; font-family:'Inter',sans-serif; color:var(--texto);
  }
  input:focus{ outline:none; border-color:var(--azul); }
  label{ font-size:12.5px; color:var(--texto-claro); font-weight:600; display:block; margin-bottom:4px; }
  .campo{ margin-bottom:12px; }
  .grupo-2{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }

  button{
    border:none; border-radius:6px; font-weight:600; font-size:13.5px;
    padding:10px 18px; cursor:pointer; font-family:'Inter',sans-serif;
  }
  .btn-azul{ background:var(--azul); color:#fff; }
  .btn-azul:hover{ background:var(--azul-escuro); }
  .btn-verde{ background:var(--verde); color:#fff; }
  .btn-verde:hover{ filter:brightness(0.95); }
  .btn-ghost{ background:transparent; color:var(--texto-claro); border:1px solid var(--borda); }
  button:disabled{ opacity:0.5; cursor:not-allowed; }

  .preview{ display:flex; gap:14px; align-items:center; background:#FAFAFA; border:1px dashed var(--borda); border-radius:8px; padding:12px; margin-bottom:12px; }
  .preview img{ width:56px; height:56px; object-fit:contain; background:#fff; border-radius:4px; }
  .preview.oculto{ display:none; }

  .aviso{ font-size:13px; padding:10px 12px; border-radius:6px; margin-bottom:12px; }
  .aviso.erro{ background:#FDECEA; color:var(--vermelho); }
  .aviso.sucesso{ background:#E8F8EE; color:var(--verde); }
  .aviso.oculto{ display:none; }

  .grid{ display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:14px; }
  .card{ background:var(--card); border:1px solid var(--borda); border-radius:8px; position:relative; overflow:hidden; }
  .card img{ width:100%; aspect-ratio:1/1; object-fit:contain; padding:14px; background:#fff; }
  .card-body{ padding:0 14px 14px; }
  .card-categoria{ font-size:10.5px; color:var(--azul); font-weight:700; text-transform:uppercase; letter-spacing:0.02em; margin-bottom:3px; }
  .card-titulo{ font-size:13px; line-height:1.35; min-height:34px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:4px; }
  .card-preco{ font-size:17px; font-weight:700; }
  .card-preco-antigo{ font-size:11.5px; color:#999; text-decoration:line-through; margin-right:6px; }
  .btn-remover{
    position:absolute; top:8px; right:8px; width:26px; height:26px; border-radius:50%;
    background:var(--vermelho); color:#fff; font-weight:700; font-size:14px; line-height:1;
    display:flex; align-items:center; justify-content:center; border:none; cursor:pointer;
  }
  .vazio{ text-align:center; color:#999; padding:40px 0; grid-column:1/-1; }
  .contador{ font-size:13px; color:var(--texto-claro); margin-bottom:14px; }
</style>
</head>
<body>

<div class="topbar"><div class="logo">CSC<span>.Digital</span> · Gerenciar Produtos</div></div>

<div class="container">

  <div class="painel">
    <h2>Adicionar produto</h2>

    <div class="campo">
      <label>Link do produto (pode ser o de afiliado, funciona igual)</label>
      <div class="linha">
        <input id="input-link" type="text" placeholder="https://...">
        <button class="btn-azul" id="btn-buscar" onclick="buscarDados()">Buscar dados</button>
      </div>
    </div>

    <div class="aviso erro oculto" id="aviso-erro"></div>

    <div class="preview oculto" id="preview">
      <img id="preview-img" src="" alt="">
      <div id="preview-texto" style="font-size:13px;"></div>
    </div>

    <div class="campo">
      <label>Titulo</label>
      <input id="input-titulo" type="text">
    </div>
    <div class="campo">
      <label>Link da imagem</label>
      <input id="input-imagem" type="text">
    </div>
    <div class="grupo-2">
      <div class="campo">
        <label>Preco atual (ex: 89,90)</label>
        <input id="input-preco-atual" type="text">
      </div>
      <div class="campo">
        <label>Preco antigo (opcional)</label>
        <input id="input-preco-antigo" type="text">
      </div>
    </div>
    <div class="campo">
      <label>Selo (opcional, ex: MENOR PRECO)</label>
      <input id="input-selo" type="text">
    </div>
    <div class="campo">
      <label>Categoria (detectada automatico, edite se quiser)</label>
      <input id="input-categoria" type="text" list="lista-categorias" placeholder="Ex: Eletrônicos">
      <datalist id="lista-categorias"></datalist>
    </div>

    <button class="btn-verde" onclick="salvarProduto()">Salvar produto</button>
  </div>

  <div class="contador" id="contador">Carregando...</div>
  <div class="grid" id="grid"></div>

</div>

<script>
  function mostrarErro(msg) {
    const el = document.getElementById('aviso-erro');
    el.textContent = msg;
    el.classList.remove('oculto');
  }
  function esconderErro() {
    document.getElementById('aviso-erro').classList.add('oculto');
  }

  async function buscarDados() {
    esconderErro();
    const link = document.getElementById('input-link').value.trim();
    if (!link) { mostrarErro('Cola um link primeiro.'); return; }

    const btn = document.getElementById('btn-buscar');
    btn.disabled = true;
    btn.textContent = 'Buscando...';

    try {
      const resp = await fetch('/api/buscar', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({url: link})
      });
      const dados = await resp.json();

      if (dados.erro) {
        mostrarErro(dados.erro + ' - preencha os campos abaixo manualmente.');
      } else {
        document.getElementById('input-titulo').value = dados.titulo || '';
        document.getElementById('input-imagem').value = dados.imagem || '';
        document.getElementById('input-preco-atual').value = dados.preco || '';
        document.getElementById('input-preco-antigo').value = dados.precoAntigo || '';
        document.getElementById('input-categoria').value = dados.categoria || '';

        const preview = document.getElementById('preview');
        if (dados.imagem) {
          document.getElementById('preview-img').src = dados.imagem;
          preview.classList.remove('oculto');
          document.getElementById('preview-texto').textContent = 'Confere se os dados batem antes de salvar.';
        }
      }
    } catch (e) {
      mostrarErro('Erro de conexao: ' + e);
    }

    btn.disabled = false;
    btn.textContent = 'Buscar dados';
  }

  async function salvarProduto() {
    esconderErro();
    const produto = {
      titulo: document.getElementById('input-titulo').value.trim(),
      imagem: document.getElementById('input-imagem').value.trim(),
      precoAtual: document.getElementById('input-preco-atual').value.trim(),
      precoAntigo: document.getElementById('input-preco-antigo').value.trim(),
      selo: document.getElementById('input-selo').value.trim(),
      categoria: document.getElementById('input-categoria').value.trim(),
      link: document.getElementById('input-link').value.trim(),
    };

    if (!produto.titulo || !produto.link) {
      mostrarErro('Preencha pelo menos o titulo e o link.');
      return;
    }

    const resp = await fetch('/api/produtos', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(produto)
    });
    const dados = await resp.json();

    if (dados.erro) { mostrarErro(dados.erro); return; }

    limparFormulario();
    renderizarGrid(dados);
  }

  function limparFormulario() {
    ['input-link','input-titulo','input-imagem','input-preco-atual','input-preco-antigo','input-selo','input-categoria']
      .forEach(id => document.getElementById(id).value = '');
    document.getElementById('preview').classList.add('oculto');
  }

  async function removerProduto(indice) {
    if (!confirm('Remover esse produto?')) return;
    const resp = await fetch('/api/produtos/' + indice, { method: 'DELETE' });
    const dados = await resp.json();
    renderizarGrid(dados);
  }

  function renderizarGrid(produtos) {
    const grid = document.getElementById('grid');
    document.getElementById('contador').textContent = produtos.length + ' produto(s) no catalogo';

    atualizarListaCategorias(produtos);

    if (produtos.length === 0) {
      grid.innerHTML = '<div class="vazio">Nenhum produto ainda. Adicione o primeiro ali em cima.</div>';
      return;
    }

    grid.innerHTML = produtos.map((p, i) => `
      <div class="card">
        <button class="btn-remover" onclick="removerProduto(${i})">×</button>
        <img src="${p.imagem}" alt="${p.titulo}">
        <div class="card-body">
          ${p.categoria ? `<div class="card-categoria">${p.categoria}</div>` : ''}
          <div class="card-titulo">${p.titulo}</div>
          ${p.precoAntigo ? `<span class="card-preco-antigo">R$ ${p.precoAntigo}</span>` : ''}
          <span class="card-preco">R$ ${p.precoAtual}</span>
        </div>
      </div>
    `).join('');
  }

  function atualizarListaCategorias(produtos) {
    const categorias = [...new Set(produtos.map(p => p.categoria).filter(Boolean))].sort();
    const datalist = document.getElementById('lista-categorias');
    datalist.innerHTML = categorias.map(c => `<option value="${c}">`).join('');
  }

  async function carregarInicial() {
    const resp = await fetch('/api/produtos');
    const dados = await resp.json();
    renderizarGrid(dados);
  }

  carregarInicial();
</script>
</body>
</html>
"""


@app.route("/")
def rota_index():
    return PAGINA_HTML


def abrir_navegador():
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    rodando_na_nuvem = "PORT" in os.environ  # Render (e a maioria dos servicos) define isso

    if not rodando_na_nuvem:
        threading.Thread(target=abrir_navegador, daemon=True).start()
        print(f"Abrindo em http://127.0.0.1:{porta} ...")
        print("Deixe esta janela aberta enquanto usa. Ctrl+C pra fechar.")

    app.run(host="0.0.0.0", port=porta, debug=False)
