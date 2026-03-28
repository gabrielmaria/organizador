# Testes do Sistema de Dois Tipos de Utilizadores

## Checklist de Implementação ✓

### Fase 1: Sistema de Autenticação
- [x] Variáveis `PASSWORD_ADMIN` e `PASSWORD_MEMBRO` criadas
- [x] Decorador `@require_admin()` implementado
- [x] Função `/login` atualizada para validar contra dois passwords
- [x] Session guarda `role` (admin/membro)

### Fase 2: Proteção de Rotas
- [x] `@require_admin()` adicionado a todas as rotas POST/DELETE administrativas
- [x] ROtas administrativas GET protegidas:
  - `/elementos` - admin only
  - `/eventos/novo` - admin only
  - `/backup/pagina` - admin only
  - `/backup` - admin only
  - `/export/excel` - admin only
- [x] Rota `/eventos/<id>/resposta` - **não protegida** (permite membros responder)

### Fase 3: UI Diferenciada
- [x] `base.html`: Menu adaptativo por role
  - Admin vê: Eventos, Ensaios, **Membros**, Stats, **Backup**, Sair
  - Membro vê: Eventos, Ensaios, Stats, Sair
- [x] Indicador de role no menu (admin/membro)

### Fase 4: Passar current_role às Templates
- [x] `current_role=session.get('role', 'membro')` adicionado a todos render_template()

### Fase 5: Condicionalizar Botões
- [x] `evento.html`: Ocultar CSV import e editing para membros
- [x] `elementos.html`: Ocultar form de add/edit para membros, mostrar dados read-only
- [x] `ensaio_detail.html`: Ocultar botões de presença para membros, mostrar badges de status

---

## Testes Manuais a Executar

### 1. Login Duplo
```
URL: http://localhost:5000/login
Admin:    Use password diferente (APP_PASSWORD_ADMIN)
Membro:   Use password diferente (APP_PASSWORD_MEMBRO)
```

**Verificar:**
- Admin login → `session['role'] = 'admin'` → Menu completo
- Membro login → `session['role'] = 'membro'` → Menu reduzido
- URL no browser mostra role na sessão

### 2. Permissões Admin (Login como Admin)
```
✓ Consegue aceder /elementos
✓ Consegue criar evento (/eventos/novo)
✓ Consegue registar presença (/ensaios/<id>)
✓ Consegue aceder /backup
✓ Consegue usar /export/excel
✓ Menu mostra: Eventos, Ensaios, Membros, Stats, Backup
```

### 3. Permissões Membro (Login como Membro)
```
✓ Consegue ver /eventos (list + detalhes)
✓ Consegue ver /ensaios (list + detalhes)
✓ Consegue ver /estatisticas
✓ NÃO consegue aceder /elementos (403 error)
✓ NÃO consegue aceder /eventos/novo (403 error)
✓ NÃO consegue aceder /backup (403 error)
✓ Menu mostra: Eventos, Ensaios, Stats (sem Membros, sem Backup)
✓ Buttons de edição não aparecem
✓ Presença mostra apenas badges (read-only)
```

### 4. Testar POST Diretos (Security)
```bash
# Como membro, tentar POST em endpoint admin
curl -X POST http://localhost:5000/elementos/add \
  -d "nome=Test" \
  -b "session_cookie=..." 
# Esperado: 403 Forbidden
```

### 5. Testar Desconexão
```
✓ Logout limpa session
✓ Redireciona para /login
✓ Tentar aceder página protegida redireciona para login
```

---

## Variáveis de Ambiente Necessárias

Para testar o sistema dual de passwords:

```bash
export APP_PASSWORD_ADMIN="admin123"
export APP_PASSWORD_MEMBRO="membro123"
export SECRET_KEY="seu_secret_key"
```

Ou no `render.yaml` / `.env`:
```yaml
env:
  APP_PASSWORD_ADMIN: "admin123"
  APP_PASSWORD_MEMBRO: "membro123"
```

---

## Backward Compatibility

Se `APP_PASSWORD_ADMIN` ou `APP_PASSWORD_MEMBRO` não estão definidas, o sistema usa `APP_PASSWORD` como fallback:
```python
PASSWORD_ADMIN  = os.environ.get("APP_PASSWORD_ADMIN") or os.environ.get("APP_PASSWORD")
PASSWORD_MEMBRO = os.environ.get("APP_PASSWORD_MEMBRO") or os.environ.get("APP_PASSWORD")
```

Isto permite que a app continue a funcionar com configurações antigas sem quebras.

---

## Notas Importantes

1. **Membros veem TUDO** em termos de dados (eventos, ensaios, stats) - não há restrição de dados
2. **Membros não conseguem EDITAR** nada - UI esconde buttons e rotas bloqueiam POST/DELETE
3. **Admin tem 100% de permissões** - igual ao comportamento anterior
4. **Session em memória** - se reiniciares app, sessions reset (comportamento normal)
5. **Single password system** - não há DB de users individuais, apenas dois tipos globais

---

## Próximas Melhorias (Futuro)

- [ ] Login individual por membro (tabela users na BD)
- [ ] Rate limiting em /login
- [ ] Hashing de passwords (em vez de plaintext)
- [ ] Auditoria de ações por role
- [ ] Restrição de dados por membro (ver apenas seus própios dados)
