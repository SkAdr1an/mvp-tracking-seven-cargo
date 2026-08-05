# CheckPoint estável

`CheckPoint` é o marco estável criado antes das mudanças operacionais de maior
risco. A referência oficial é a tag Git anotada `CheckPoint`, salva localmente e
no repositório privado do GitHub.

## Comando de recuperação

Quando o operador disser **"voltar ao CheckPoint"**, preserve primeiro qualquer
trabalho atual em uma branch de recuperação. Depois, crie uma nova branch a
partir da tag, sem reescrever nem apagar o histórico:

```powershell
git switch -c recovery/CheckPoint CheckPoint
```

Se esse nome já existir, use um sufixo de data e hora. Nunca use
`git reset --hard` para voltar ao marco sem autorização explícita e sem antes
preservar o estado atual.

## Verificação

```powershell
git show CheckPoint --no-patch
git rev-parse CheckPoint^{commit}
```

O código recuperado deve ser validado com os testes do backend e frontend antes
de voltar a operar.
