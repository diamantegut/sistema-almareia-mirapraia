INSTRUÇÕES DE ATUALIZAÇÃO - SISTEMA MIRAPRAIA
DATA: 02/02/2026

Para atualizar o servidor "Back of the House" (Estável):

1. Copie a pasta inteira "Update_Package_20260202" para a pasta raiz do sistema no servidor.
   (Geralmente onde fica o arquivo app.py e a pasta data).

2. Entre na pasta "Update_Package_20260202".

3. Execute o arquivo "instalar_atualizacao.bat" (clique duplo).

4. Siga as instruções na tela. O script irá:
   - Atualizar o código do servidor (app.py)
   - Atualizar a interface de gerenciamento (menu_management.html)
   - Migrar o banco de dados (menu_items.json) para suportar o status "Pausado" corretamente.

5. IMPORTANTE: Após a atualização, REINICIE o servidor para que as alterações surtam efeito.

Conteúdo da Atualização:
- Correção crítica no filtro de "Pausados" no Gerenciamento de Cardápio.
- Correção na persistência do status de pausa dos produtos.
- Adição de ferramentas de diagnóstico no filtro.
