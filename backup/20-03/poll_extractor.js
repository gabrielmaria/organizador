(function () {

  function sleep(ms) {
    return new Promise(function(resolve) { setTimeout(resolve, ms); });
  }

  function getPollResultsPanel() {
    var found = null;
    document.querySelectorAll('*').forEach(function(el) {
      if (el.childNodes.length === 1 && el.innerText && el.innerText.trim() === 'Poll results') {
        found = el;
      }
    });
    if (!found) return null;
    var node = found;
    for (var i = 0; i < 10; i++) {
      node = node.parentElement;
      if (node.innerText && node.innerText.includes('votes') && node.innerText.length > 100) {
        return node;
      }
    }
    return null;
  }

  async function run() {
    var header = document.querySelector('[title="Poll details"]');
    if (!header) {
      alert('❌ Abre o painel da sondagem primeiro!');
      return;
    }

    var parent = header.parentElement.parentElement.parentElement;
    var contentPanel = parent.children[1];

    // 1. Zoom out logo para tudo ficar visível
    var originalZoom = document.body.style.zoom || '100%';
    document.body.style.zoom = '20%';
    await sleep(800);

    // 2. Agora ler o painel todo (com tudo visível)
    function parseMainPanel() {
      var fullText = contentPanel.innerText;
      var lines = fullText.split('\n').map(function(l){ return l.trim(); }).filter(Boolean);
      var timeRegex = /^(Today|Yesterday|\d{1,2}\/\d{1,2}\/\d{4})/i;
      var votesRegex = /^\d+\s+votes?$/i;
      var membersRegex = /^\d+\s+of\s+\d+\s+members/i;
      var seeAllRegex = /^See all \(\d+ more\)/;
      var atTimeRegex = /^at \d{2}:\d{2}/i;

      var pollTitle = '';
      var titleDone = false;
      var options = [];
      var currentOption = null;

      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        var next = lines[i+1] || '';

        if (membersRegex.test(line)) { titleDone = true; continue; }
        if (timeRegex.test(line) || atTimeRegex.test(line)) continue;
        if (votesRegex.test(line)) continue;
        if (seeAllRegex.test(line)) continue;

        if (!titleDone) {
          pollTitle = pollTitle ? pollTitle + ' ' + line : line;
          continue;
        }

        if (votesRegex.test(next)) {
          currentOption = { name: line, voters: [] };
          options.push(currentOption);
          continue;
        }

        if (currentOption) {
          // Ignorar se o nome do votante é igual ao nome da opção (WhatsApp repete-o)
          if (line === currentOption.name) continue;
          currentOption.voters.push(line);
        }
      }

      return { pollTitle: pollTitle, options: options };
    }

    var parsed = parseMainPanel();
    console.log('Opções encontradas:', parsed.options.map(function(o){ return o.name + '(' + o.voters.length + ')'; }).join(', '));

    // 3. Expandir "See all" um a um, re-encontrando botões após cada volta
    async function expandAll() {
      var expanded = {}; // registo de opções já expandidas

      while (true) {
        // Re-encontrar o contentPanel a cada iteração (o DOM muda após voltar atrás)
        var freshHeader = document.querySelector('[title="Poll details"]');
        if (!freshHeader) break;
        contentPanel = freshHeader.parentElement.parentElement.parentElement.children[1];

        // Re-encontrar botões a cada iteração (o DOM pode ter mudado)
        var buttons = [];
        contentPanel.querySelectorAll('button').forEach(function(btn) {
          if (btn.innerText && /^See all \(\d+ more\)$/.test(btn.innerText.trim())) {
            buttons.push(btn);
          }
        });

        if (buttons.length === 0) break;

        // Descobrir a que opção pertence cada botão e pegar o primeiro não expandido
        var allText = contentPanel.innerText;
        var btn = null;
        var optionName = null;

        for (var b = 0; b < buttons.length; b++) {
          var btnIdx = allText.indexOf(buttons[b].innerText.trim());
          var textBefore = allText.slice(0, btnIdx);
          var candidateOption = null;

          // A opção mais próxima ANTES do botão (a última que aparece no textBefore)
          parsed.options.forEach(function(opt) {
            var optIdx = textBefore.lastIndexOf(opt.name);
            if (optIdx !== -1) candidateOption = opt.name;
          });

          if (candidateOption && !expanded[candidateOption]) {
            btn = buttons[b];
            optionName = candidateOption;
            break;
          }
        }

        // Se não há botões por expandir, sair
        if (!btn) break;
        expanded[optionName] = true;

        console.log('A expandir: ' + (optionName || '?'));
        btn.click();
        await sleep(1500);

        // Ler painel Poll results
        var panel = getPollResultsPanel();
        if (panel) {
          var panelLines = panel.innerText.split('\n').map(function(l){ return l.trim(); }).filter(Boolean);
          var timeRe = /^(Today|Yesterday|\d{1,2}\/\d{1,2}\/\d{4})/i;
          var votesRe = /^\d+\s+votes?$/i;
          var atRe = /^at \d{2}:\d{2}/i;
          var collecting = false;
          var newVoters = [];

          for (var p = 0; p < panelLines.length; p++) {
            var pl = panelLines[p];
            if (pl === 'Poll results') { collecting = true; continue; }
            if (!collecting) continue;
            if (votesRe.test(pl) || timeRe.test(pl) || atRe.test(pl)) continue;
            // Ignorar se é o nome da própria opção
            if (pl === optionName) continue;
            newVoters.push(pl);
          }

          if (newVoters.length > 0 && optionName) {
            console.log('Votantes lidos para ' + optionName + ':', newVoters);
            parsed.options.forEach(function(opt) {
              if (opt.name === optionName) {
                opt.voters = newVoters;
                console.log('✅ ' + opt.name + ': ' + newVoters.length + ' votos');
              }
            });
          }
        }

        // Voltar atrás
        var backBtn = document.querySelector('button[aria-label="Back"]') ||
                      document.querySelector('button[title="Back"]');
        if (backBtn) { backBtn.click(); await sleep(800); }
        else break;
      }
    }

    await expandAll();

    // 4. Repor zoom
    document.body.style.zoom = originalZoom;

    // 5. Gerar CSV
    var totalFound = parsed.options.reduce(function(s, o){ return s + o.voters.length; }, 0);

    var rows = [
      ['Sondagem', parsed.pollTitle, '', ''],
      ['', '', '', ''],
      ['Opção', 'Nome', 'Posição', 'Total Votos']
    ];

    parsed.options.forEach(function(opt) {
      if (opt.voters.length === 0) {
        rows.push([opt.name, '(sem votos)', '', 0]);
      } else {
        opt.voters.forEach(function(name, i) {
          rows.push([opt.name, name, i + 1, i === 0 ? opt.voters.length : '']);
        });
      }
    });

    var csv = '\uFEFF' + rows.map(function(row) {
      return row.map(function(c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(',');
    }).join('\n');

    var blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    var safeName = parsed.pollTitle.replace(/[^\w\sÀ-ÿ-]/g, '').trim().replace(/\s+/g, '_');
    a.href = url;
    a.download = 'sondagem_' + safeName + '_' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    var summary = parsed.options.map(function(opt) {
      return opt.name + ': ' + opt.voters.length + ' votos';
    }).join('\n');

    console.log('✅ ' + parsed.pollTitle + '\n' + summary);
    alert('✅ Exportado!\n\n' + summary + '\n\nTotal: ' + totalFound + ' votantes\n📥 CSV descarregado!');
  }

  run().catch(function(err) {
    console.error(err);
    alert('❌ Erro: ' + err.message);
  });

})();