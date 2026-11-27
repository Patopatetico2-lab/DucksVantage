## Resumo da mudança
- Descreva o que foi alterado ou corrigido.

## Checklist
- [ ] Executei os testes unitários: `QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v`
- [ ] Não introduzi escrita automática sem `allow_elevation=False` em timers de segundo plano
- [ ] Mudanças de hardware foram validadas em `/sys/` real ou com mocks fiéis em `tests/`
