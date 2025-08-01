# ATENÇÃO - PROJETO DE TESTE

_Este projeto constitui uma série de estudos que estou realizando sobre a capacidade das IA's para automatização de serviço ou simplificação de atividades. Este Bot é 100% feito pelo Gemini Pro 2.5, em nenhum momento programei de diretamente ou fiz correções de código._

# Bot de Gestão para Servidores Discord

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg) ![discord.py](https://img.shields.io/badge/discord.py-v2.3+-7289DA.svg)

## Visão Geral do Projeto

Este repositório contém o código-fonte de um bot para Discord, desenvolvido em Python com a biblioteca `discord.py`. O projeto foi concebido como uma solução de back-end modular para automatizar e gerenciar operações complexas em comunidades online, particularmente aquelas com estruturas hierárquicas e necessidade de registros de atividade.

O bot opera através de um núcleo (`init.py`) que carrega dinamicamente múltiplos módulos (cogs). Cada módulo é autônomo, com suas próprias funcionalidades e configurações controladas por arquivos `.json`, permitindo alta customização e manutenibilidade. A persistência de dados é garantida através de bancos de dados SQLite individuais para cada sistema relevante.

## ✨ Funcionalidades Principais

- **Gerenciamento de Módulos (Cogs):** O núcleo do bot permite o carregamento, descarregamento e recarregamento de módulos em tempo real através do comando `/cog`, eliminando a necessidade de reiniciar o serviço para aplicar atualizações.
- **Painéis Interativos Persistentes:** A interação do usuário é primariamente realizada através de painéis com componentes de UI persistentes (botões e modais), garantindo funcionalidade contínua mesmo após reinicializações do bot.
- **Sistema de Progressão Automatizado:** Uma tarefa em segundo plano gerencia a progressão de carreira dos membros com base em tempo de atividade, aplicando e removendo cargos automaticamente de acordo com regras configuráveis.
- **Lógica Orientada por Configuração:** A maioria das funcionalidades, desde a criação de comandos de barra até a definição de hierarquias de cargos, é controlada por arquivos de configuração `.json`, permitindo que administradores modifiquem o comportamento do bot sem interagir com o código-fonte.
- **Sincronização de Estado:** O sistema de promoção valida e corrige ativamente os cargos dos membros no servidor para garantir que eles correspondam ao estado registrado no banco de dados, prevenindo inconsistências.

## 🚀 Instalação e Configuração

Siga os passos abaixo para configurar e rodar o bot em seu ambiente.

### 1. Pré-requisitos
- Python 3.10 ou superior
- Git (opcional, para clonar o repositório)

### 2. Clonando o Repositório
```bash
git clone [https://github.com/seu-usuario/seu-repositorio.git](https://github.com/seu-usuario/seu-repositorio.git)
cd seu-repositorio
```

### 3. Instalando as Dependências
É recomendado criar um ambiente virtual.
```bash
# Para Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Para Windows
python -m venv venv
venv\Scripts\activate
```
Baixe o arquivo `requirements.txt` com o conteúdo e instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configuração dos Módulos
Cada módulo possui seu próprio arquivo `.json` de configuração na pasta principal. Você precisará preencher todos os IDs de cargos (`...ROLE_ID`) e canais (`...CHANNEL_ID`) para que as funcionalidades operem corretamente.

- `config_main.json`: `TOKEN` do bot, `GUILD_ID` principal e `OWNER_ID`.
- `config_ponto.json`: Configurações do sistema de ponto.
- `config_promocao_cog.json`: Onde toda a hierarquia de cargos e tempos de promoção é definida.
- ... e assim por diante para cada módulo.

### 5. Executando o Bot
Após configurar todos os arquivos `.json`, inicie o bot:
```bash
python init.py
```

## 🛠️ Módulos e Comandos

### `ponto_cog.py` - Sistema de Ponto Eletrônico
- **Funcionalidade:** Permite que usuários registrem turnos de serviço.
- **Interface:** Painel com botões para "Bater Ponto" e "Sair de Serviço".
- **Comando:** `/enviar_painel_ponto`
- **Automação:** Registra a saída de um membro automaticamente se ele se desconectar de um canal de voz configurado.
- **Log:** Gera um embed individual em um canal de status para cada sessão ativa, que é atualizado para "Serviço Encerrado" ao final.

### `promocao_cog.py` - Sistema de Promoção Automática
- **Funcionalidade:** Gerencia a progressão de carreira baseada em tempo de serviço.
- **Lógica:** O tempo é acumulado de forma separada para cada "Carreira" (Agente, etc.) e a velocidade da progressão é modificada por multiplicadores. O sistema promove membros automaticamente através de cargos "Padrão" e "Classe" e se "autocorrige", sincronizando os cargos dos membros com o estado do banco de dados.
- **Comandos:**
    - `/promocao status <membro>`
    - `/promocao remover <membro>`
    - `/promocao forcar_verificacao`
    - `/promocao manual ...` (Restrito ao Super Admin)

### `ausencia_cog.py` - Sistema de Registro de Ausência
- **Funcionalidade:** Permite que os próprios membros registrem períodos de ausência.
- **Interface:** Painel com botões para "Registrar Ausência" e "Encerrar Ausência".
- **Comando:** `/painel_ausencia`
- **Automação:** Adiciona e remove um cargo "Ausente" temporário com base nas datas informadas em um formulário.

### `painel_adv_cog.py` - Sistema de Advertências
- **Funcionalidade:** Ferramenta administrativa para aplicar advertências disciplinares.
- **Interface:** Painel com botões que abrem um formulário para detalhar o infrator e o motivo.
- **Comando:** `/painel_adv`
- **Automação:** Aplica cargos de punição temporários. Inclui o comando `/revogar_adv` para cancelar punições.

### `porte_arma_cog.py` e `boletim_cog.py` - Sistemas de Registro
- **Porte de Arma:** Um painel com formulário (`/painel_porte`) para registrar portes de arma. O embed de log resultante é interativo, com botões para "Revogar" ou "Emitir Novamente".
- **Boletim Interno:** Um painel (`/painel_boletim`) para administradores preencherem e publicarem um boletim informativo com seções pré-definidas.

### `dynamic_report_cog.py` - Motor de Relatórios Dinâmicos
- **Funcionalidade:** Um sistema genérico que cria múltiplos painéis e formulários de relatório a partir de "modelos" definidos em um arquivo JSON.
- **Automação:** Gera comandos de barra (ex: `/ocorrencia`, `/viatura`) dinamicamente com base na configuração.

### `relatorio_ponto_cog.py` e `verificar_promocao_cog.py` - Ferramentas de Consulta
- **Relatório de Ponto:** `/relatorio_ponto` gera um arquivo `.txt` detalhado e um gráfico `.png` da atividade de ponto de um membro.
- **Verificar Promoção:** `/verificar_promocao` exibe uma lista paginada de todos os membros no sistema de promoção.

### `status_cog.py` - Módulo de Diagnóstico
- **Funcionalidade:** Exibe um painel persistente (`/painel_status`) que se atualiza automaticamente com métricas de desempenho do bot (uso de RAM, CPU, latência da API, uptime, etc.).

### `units_cog.py` - Sistema de Unidades
- **Funcionalidade:** Permite a criação e gerenciamento de unidades/equipes temporárias.
- **Comando:** `/unidades`
- **Automação:** As unidades são desfeitas automaticamente com base na presença em canais de voz ou tempo de existência.

## 💻 Stack Tecnológica
- **Linguagem:** Python
- **Biblioteca Principal:** `discord.py`
- **Banco de Dados:** `SQLite` (via `aiosqlite`)
- **Análise de Dados e Gráficos:** `pandas` e `matplotlib`
- **Recursos do Sistema:** `psutil`
- **Geração de Documentos:** `python-docx` e `docx-template`
