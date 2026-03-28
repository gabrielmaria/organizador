# Guia de Deploy — Tuna Disponibilidades

## O que vais ter no final
Uma app web acessível de **qualquer dispositivo** (telemóvel, tablet, computador) pelo browser,
hospedada gratuitamente no Render.com, com login por password e OCR para ler screenshots do WhatsApp.

---

## Pré-requisitos
- Conta no **GitHub** (gratuita) → https://github.com
- Conta no **Render.com** (gratuita) → https://render.com

---

## Passo 1 — Colocar o código no GitHub

### 1.1 Criar repositório
1. Vai a https://github.com/new
2. Nome: `tuna-disponibilidades`
3. Privado (recomendado) ou público
4. Clica **Create repository**

### 1.2 Enviar os ficheiros
Na pasta do projeto, abre o terminal:

```bash
cd /caminho/para/tuna/
git init
git add .
git commit -m "primeiro commit"
git branch -M main
git remote add origin https://github.com/SEU_USERNAME/tuna-disponibilidades.git
git push -u origin main
```

---

## Passo 2 — Deploy no Render.com

### 2.1 Criar conta
1. Vai a https://render.com
2. Clica **Get Started for Free**
3. Regista com GitHub (mais fácil)

### 2.2 Criar o serviço
1. No dashboard do Render, clica **New +** → **Web Service**
2. Conecta ao teu repositório GitHub (`tuna-disponibilidades`)
3. Preenche:
   - **Name**: `tuna-disponibilidades`
   - **Runtime**: Docker
   - **Plan**: Free
4. Em **Environment Variables**, adiciona:
   - `APP_PASSWORD` = a password que quiseres (ex: `Tuna@2025`)
   - `SECRET_KEY` = qualquer string aleatória longa
5. Clica **Create Web Service**

### 2.3 Aguardar o deploy
- O Render vai construir a app (~3-5 minutos na primeira vez)
- Quando aparecer "Live", o teu URL será algo como:
  `https://tuna-disponibilidades.onrender.com`

---

## Passo 3 — Usar a app

1. Abre o URL no browser (qualquer dispositivo)
2. Entra com a password que definiste
3. Vai a **Membros** → adiciona todos os elementos da tuna
4. Volta a **Eventos** → cria um novo evento com as opções da poll

### Registar votos via screenshot:
1. No WhatsApp, clica na poll → **View votes**
2. Seleciona uma opção (ex: "Sim")
3. Tira screenshot do ecrã com os nomes visíveis
4. Na app, abre o evento → **Carregar screenshot**
5. Escolhe a opção correspondente e faz upload
6. Confirma os nomes detetados

---

## Passo 4 — Partilhar com outros membros

Basta enviares o URL e a password pelo WhatsApp da tuna.
Qualquer pessoa pode aceder e registar respostas.

---

## Atualizar a app no futuro

Sempre que fizeres alterações ao código:

```bash
git add .
git commit -m "descrição da alteração"
git push
```

O Render faz o re-deploy automaticamente.

---

## Mudar a password

No dashboard do Render:
1. Abre o teu serviço
2. Vai a **Environment** → edita `APP_PASSWORD`
3. Clica **Save Changes** (faz re-deploy automático)

---

## Plano gratuito do Render — limitações
- O servidor "adormece" após 15 min sem uso → primeira abertura demora ~30s
- 750 horas/mês grátis (suficiente para uso normal)
- 1 GB de disco para a base de dados

Se precisares de mais, o plano Starter custa $7/mês e mantém sempre ativo.
