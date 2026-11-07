<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Conecte Gemini Spark / aplicativos personalizados

O recurso **aplicativos conectados personalizados** do Gemini (anteriormente descrito como **Spark**) permite que um usuário qualificado do Gemini conecte um servidor MCP remoto. O LSM pode fornecer o endpoint MCP. Esta é uma **conexão de cliente alternativa** para [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) e outros clientes MCP; ele não substitui nem implanta o Controlador LSM.

Atualmente, o Google restringe aplicativos personalizados a **usuários com 18 anos ou mais nos Estados Unidos**, conectados com uma **Conta do Google pessoal** e **Manter atividade ativada**. O recurso está disponível em **inglês**. As conexões devem ser criadas no aplicativo web Gemini, embora os aplicativos conectados possam ser usados ​​posteriormente no celular. A disponibilidade e os rótulos da IU podem mudar; consulte o [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137).

## Antes de conectar

- Inicie um tempo de execução LSM, por exemplo, com [Docker Compose](../installation/docker.md), e verifique seu funcionamento.
- Exponha seu endpoint MCP por **HTTPS publicamente acessível** e mantenha o OAuth ativado.
- Conheça os detalhes de autenticação do Controlador e aprove apenas os escopos necessários.
- Use um espaço de trabalho ou contêiner restrito. Gemini pode solicitar operações com efeitos reais em arquivos, máquinas e terminais.

O ponto final para entrar no Gemini é:

```text
https://your-public-host.example.com/mcp
```

Não insira a UI da web (`/ui`), o URL do LibreChat ou a origem do site sem `/mcp`. As implantações públicas não devem desabilitar a autenticação para contornar erros de conexão.

## Conecte-se em Gêmeos

1. Em um computador, abra [Gemini](https://gemini.google.com/) e faça login com uma conta pessoal qualificada.
2. Abra **Configurações e ajuda → Aplicativos conectados**. Dependendo da interface atual, pode estar em **Inteligência Pessoal → Aplicativos Conectados**.
3. Em **Aplicativos personalizados**, selecione **Adicionar um aplicativo personalizado** ou use o campo URL do aplicativo personalizado.
4. Cole o URL `/mcp` do LSM HTTPS e escolha **Próximo**.
5. Conclua o OAuth e o fluxo de consentimento com o Controlador LSM. O LSM oferece suporte à descoberta OAuth e ao registro dinâmico de clientes. Se o Gemini solicitar credenciais manuais do cliente OAuth, verifique suas opções avançadas e a configuração do LSM OAuth antes de continuar.
6. Em uma conversa do Gemini, digite `@` e selecione o aplicativo personalizado conectado para solicitar uma ferramenta LSM.

Comece com: "Use o aplicativo LSM conectado para inspecionar o ambiente e listar os arquivos do espaço de trabalho. Não modifique nada." Verifique os resultados da ferramenta e a auditoria do Controlador antes de tentar operações de gravação.

## Limites e solução de problemas

- **Sem opção de aplicativos personalizados:** confirme a elegibilidade da conta, região, idade, idioma e Keep Activity. Esta é uma restrição de disponibilidade do lado Gemini, não um erro de configuração do LSM.
- **URL rejeitado:** use um endpoint HTTPS `/mcp` acessível externamente; verifique a descoberta do OAuth e seu proxy reverso.
- **Falha no OAuth:** verifique a tela de autorização do LSM, registro do cliente, URL de retorno de chamada e escopos concedidos. Não publique um endpoint MCP não autenticado.
- **Uma ferramenta está faltando ou falha:** o suporte à ferramenta/esquema MCP do lado do cliente pode ser diferente. Experimente uma chamada simples somente leitura e inspecione a auditoria e os logs do LSM; a compatibilidade total com todos os recursos do cliente Gemini não é garantida.
- **Desconectando:** volte para **Aplicativos conectados** para desativar, desvincular ou remover o LSM quando ele não for mais necessário.

O [official guide](https://support.google.com/gemini/answer/17209137) do Google descreve o fluxo e a disponibilidade mais recentes dos aplicativos personalizados. Para uma integração Gemini baseada em CLI local, consulte [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/). O LSM [ChatGPT connector tutorial](chatgpt-connector.md) permanece disponível de forma independente.
