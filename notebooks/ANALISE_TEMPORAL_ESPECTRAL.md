# Análise Temporal vs Espectral — MPU6050 / Vibração de Ventilador

> Documento técnico gerado a partir das análises executadas nos notebooks
> `01_EDA.ipynb` e `02_Feature_Engineering.ipynb` com o dataset
> `col_20260307_185012_100hz` (212.095 amostras, 7 classes, 100 Hz).

---

## 1. A Pergunta Central

> **Para análise espectral, a média foi tirada das janelas de tempo?**

A resposta é: **depende da seção do notebook**. Cada célula espectral usa uma
abordagem distinta. A tabela abaixo resume:

| Seção | Célula | Método | Usa média de janelas? |
|---|---|---|---|
| B — FFT visualização | `cell ~27` | FFT por janela → média dos espectros | **Sim** |
| B2 — PSD heatmap | `spec_psd_b2` (Parte 1) | Welch PSD sobre sinal completo | Não — Welch segmenta internamente |
| B2 — Espectrograma | `spec_psd_b2` (Parte 2) | STFT sobre sinal completo | Não — mostra evolução temporal |
| C1 — PSD Welch todos eixos | `spec_c1_psd` | Welch sobre sinal completo | Não — Welch segmenta internamente |
| C2 — STFT por classe | `spec_c2_stft` | STFT sobre sinal completo | Não — mostra evolução temporal |
| Feature Engineering | `02_FE cell-7` | FFT por janela, sem média | Não — cada janela é um ponto |

---

## 2. Como Cada Método Funciona

### 2.1 Seção B — Espectro Médio por Classe (média de janelas)

```
Sinal bruto (30.000 amostras, 300s)
    │
    ├─ janela 1 (100 amostras) → FFT → |X₁(f)|
    ├─ janela 2 (100 amostras) → FFT → |X₂(f)|
    ├─ janela 3 (100 amostras) → FFT → |X₃(f)|
    │   ...
    └─ janela N (100 amostras) → FFT → |Xₙ(f)|
                                          │
                              média: S(f) = (1/N) Σ |Xᵢ(f)|
```

**O que produz:** um único espectro de amplitude médio por classe.
**Para que serve:** comparação visual entre classes — mostra quais frequências
são sistematicamente mais energéticas em cada velocidade.
**Limitação:** perde a informação de *quando* cada frequência aparece.
A média suaviza variações temporais (e.g., ruídos transitórios).

---

### 2.2 Seção B2/C1 — PSD Welch (média de periodogramas)

O método de Welch é matematicamente equivalente a "média de janelas", mas com
segmentação interna e janelamento Hann para reduzir o vazamento espectral
(*spectral leakage*):

```
Sinal completo da classe (30.000 amostras)
    │
    scipy.signal.welch(
        nperseg = 256  (janela de 2,56 s a 100 Hz)
        noverlap = 192 (overlap 75%)
        nfft    = 512  (zero-padding → resolução 0,195 Hz/bin)
        window  = 'hann'
        detrend = 'linear'
    )
    │
    Resultado: PSD(f)  [V²/Hz]  → convertido para dB
```

**Diferença em relação à Seção B:**
- Seção B: FFT retangular (sem janelamento), tamanho fixo 100 amostras = 1s
  → resolução frequencial Δf = 100/100 = **1,0 Hz/bin**
- Seção B2 Welch: Hann + zero-padding, nperseg=256, nfft=512
  → resolução Δf = 100/512 = **0,195 Hz/bin** (5× mais fino)

O Welch é o método correto para estimar a **Densidade Espectral de Potência
(PSD)** porque:
1. O janelamento Hann elimina o efeito de borda (leakage)
2. A média de segmentos reduz a variância da estimativa (~√N vezes)
3. O zero-padding aumenta a resolução visual sem aumentar a resolução física

---

### 2.3 Seção B2/C2 — Espectrograma STFT (sem média — evolução temporal)

```
Sinal completo da classe
    │
    scipy.signal.spectrogram() / stft()
    │
    Resultado: Z(tempo, frequência)  → heatmap 2D
```

O STFT (Short-Time Fourier Transform) computa a FFT em janelas deslizantes e
*não* faz média — preserva cada janela como uma coluna do heatmap. O resultado
é uma matriz `frequência × tempo` que mostra como o conteúdo espectral evolui
ao longo dos 300 segundos de coleta.

**Para que serve:** detectar não-estacionariedades — se a vibração muda de
caráter ao longo do tempo (aquecimento do motor, variação de carga).

---

### 2.4 Feature Engineering — Janela Independente (sem média)

No pipeline de ML (`02_Feature_Engineering.ipynb`), cada janela é um ponto de
dado independente no dataset:

```
Sinal da classe
    │
    ├─ janela [0:100]   → FFT → fft_high, fft_mid, fft_low + stats → linha 1 do CSV
    ├─ janela [20:120]  → FFT → fft_high, fft_mid, fft_low + stats → linha 2 do CSV
    ├─ janela [40:140]  → FFT → ...                                 → linha 3
    │   (step=20, overlap=80%)
    └─ janela [N-100:N] → FFT → ...                                 → linha N
```

**Parâmetros da FFT por janela:**
- Tamanho: 100 amostras = 1 segundo a 100 Hz
- Resolução: Δf = fs/N = 100/100 = **1,0 Hz/bin**
- Sem zero-padding (velocidade > resolução para ML)
- Sem janelamento Hann (FFT retangular — aceitável para janelas curtas)

**Por que não há média:** o modelo aprende a classificar *cada janela
individualmente*. Médias destruiriam a variância intra-janela que é justamente
o sinal discriminativo (range, std, kurtosis).

---

## 3. Série Temporal vs Espectro — Qual Informa Mais?

### 3.1 Resultado Quantitativo (d_min mediano por tipo de feature)

| Tipo de Feature | N features | d_min mediano | d_min máximo | Melhor para |
|---|---|---|---|---|
| **Temporal (std, range, rms, p25...)** | 49 | **0,201** | 3,82 | **Separação geral** |
| **FFT energy (fft_high, fft_mid...)** | 24 | 0,105 | 1,31 | Velocidade + ON/OFF |
| **Spectral power bands (sp_p1..p24)** | 84 | 0,109 | 1,09 | Velocidade (L/M/H) |
| **Shape/Higher-order (kurtosis, skew)** | 16 | 0,067 | 0,33 | Forma da distribuição |

> Cohen's d = separação entre duas distribuições em unidades de desvio padrão.
> d < 0,5 = pequeno; d ≥ 0,8 = médio; d ≥ 1,5 = grande.

### 3.2 Por Que a Série Temporal Domina

A vibração mecânica de um ventilador se manifesta como **oscilação de
amplitude** no acelerômetro. Velocidade mais alta → amplitude de oscilação
maior → range, std e RMS crescem monotonicamente:

```
Eixo accel_x_g (janela de 1s):
  FAN_OFF  → std ≈ 0,003 g   range ≈ 0,01 g
  LOW      → std ≈ 0,064 g   range ≈ 0,25 g   (21× mais que OFF)
  MEDIUM   → std ≈ 0,105 g   range ≈ 0,68 g   (1,65× mais que LOW)
  HIGH     → std ≈ 0,273 g   range ≈ 1,05 g   (2,60× mais que MEDIUM)
```

O `accel_x_g_range` captura diretamente a amplitude pico-a-pico da vibração
na janela de 1 segundo. É o descritor físico mais direto do fenômeno e obteve
o maior Cohen's d entre LOW e MEDIUM: **d = 5,04** com sobreposição de
distribuições de apenas **0,1%**.

### 3.3 Onde o Espectro é Insubstituível

**Caso 1: Separar harmônicos físicos do motor**

O FFT de alta frequência (`fft_high`, 15–50 Hz) captura energia em bandas onde
a série temporal não distingue porque a amplitude média pode ser similar, mas
a *distribuição de energia por frequência* difere:

```
Bandas observadas (calibração 2026-02-23, accel_x_g):
  LOW    → pico em ~1,465 Hz
  MEDIUM → pico em ~2,197–2,246 Hz
  HIGH   → pico em ~3,931–5,322 Hz
```

O `gyro_x_dps_fft_high` (15–50 Hz) obteve **d_min_all = 1,31** — o maior
d_min entre todas as 265 features candidatas. Isso significa que a energia de
alta frequência dos giroscópios é um discriminador robusto em todos os 21 pares
de classes simultaneamente.

**Caso 2: Separar ON vs OFF com o mesmo nível de velocidade**

Os pares mais críticos são `ROT_ON vs ROT_OFF` à mesma velocidade. O campo
espectral complementa a série temporal aqui porque a vibração *rotacional*
(ventilador girando) concentra energia em frequências específicas, enquanto a
vibração *sem rotação* (motor ligado, ventilador travado) tem espectro mais
plano:

| Par | Melhor feature | d | Tipo |
|---|---|---|---|
| LOW_ROT_ON vs LOW_ROT_OFF | `vibration_dps_fft_high` | **2,85** | FFT energy |
| MEDIUM_ROT_ON vs MEDIUM_ROT_OFF | `accel_x_g_fft_high` | **4,36** | FFT energy |
| HIGH_ROT_ON vs HIGH_ROT_OFF | `vibration_dps_fft_high` | **3,40** | FFT energy |

Para esses pares, FFT ganha sobre temporal puro — a rotação cria harmônicos
específicos ausentes no estado OFF.

**Caso 3: Diagnóstico de falha (uso futuro)**

Se um rolamento deteriorar, surgirá um pico em frequências características
(BPFO, BPFI, FTF — equações de falha de rolamento). A série temporal verá
apenas aumento de amplitude; o espectro identificará *onde* a energia aumentou,
permitindo diagnóstico específico da falha.

---

## 4. As 16 Features Selecionadas — Análise de Cobertura

### 4.1 Composição do Set Final

```
Features selecionadas (Cohen's d + correlação + pairwise):

  # FFT energy (3 features — domínio frequência):
  01. gyro_x_dps_fft_high      d_min=1,314  ← melhor feature global
  02. accel_x_g_fft_high       d_min=0,949  ← melhor para MEDIUM ON vs OFF (d=4,36)
  03. vibration_dps_fft_high   d_min=0,948  ← melhor para LOW/HIGH ON vs OFF (d=2,85/3,40)

  # Spectral power bands (5 features — momentos espectrais):
  04. accel_z_g_sp_p2          d_min=0,789
  05. accel_z_g_fft_high       d_min=0,786
  08. accel_z_g_sp_p12         d_min=0,498
  11. accel_y_g_sp_p2          d_min=0,432
  12. accel_y_g_sp_p1          d_min=0,427

  # Temporal statistics (8 features — domínio tempo):
  06. accel_x_g_rms            d_min=0,551
  07. gyro_x_dps_p25           d_min=0,515
  09. accel_z_g_range          d_min=0,483
  10. accel_x_g_range          d_min=0,476
  13. accel_x_g_sp_p7          d_min=0,427
  14. gyro_z_dps_std           d_min=0,414
  15. accel_mag_g_std          d_min=0,399
  16. accel_y_g_fft_high       d_min=0,398
```

**Distribuição:** 3 FFT energy + 5 spectral bands + 8 temporal stats.
A combinação é complementar: as features temporais fornecem separação geral
robusta; as espectrais adicionam discriminação de frequência específica.

### 4.2 Cobertura de Pares Críticos (d_max do set)

A métrica relevante para avaliar se o *conjunto* cobre um par não é o d_min
de features individuais, mas o **d_max** — o melhor que qualquer feature do set
consegue para aquele par:

| Par de Classes | d_max no set | Feature responsável | Cobertura |
|---|---|---|---|
| LOW_ROT_ON vs MEDIUM_ROT_ON | **5,04** | `accel_x_g_range` | Excelente |
| MEDIUM_ROT_ON vs HIGH_ROT_ON | **4,23** | `accel_x_g_range` | Excelente |
| LOW_ROT_ON vs LOW_ROT_OFF | **2,85** | `vibration_dps_fft_high` | Boa |
| MEDIUM_ROT_ON vs MEDIUM_ROT_OFF | **4,36** | `accel_x_g_fft_high` | Excelente |
| HIGH_ROT_ON vs HIGH_ROT_OFF | **3,40** | `vibration_dps_fft_high` | Boa |
| FAN_OFF vs qualquer outro | > 2,0 | múltiplas | Excelente |

> **Nota sobre d_min vs d_max:** o algoritmo de seleção usa `d_min_all`
> (mínimo de d em todos os 21 pares) como score de *ranking individual* de
> features. Esse critério pode descartar features com d_min baixo em algum par
> irrelevante mas excelente separação no par crítico. Por isso foi implementado
> o bloco de complemento ON vs OFF na cell-8, que verifica d_max do *conjunto*
> e adiciona features se algum par ficar descoberto.

---

## 5. Impacto da Janela na Análise Espectral

### 5.1 Resolução Frequencial vs Duração da Janela

A resolução de um espectro é determinada pelo comprimento do sinal analisado:

```
Δf = fs / N

Onde:
  fs = taxa de amostragem (Hz)
  N  = número de amostras da janela
```

| Análise | fs | N | Δf (sem padding) | N_fft | Δf (com padding) |
|---|---|---|---|---|---|
| Feature Eng. (FFT por janela) | 100 Hz | 100 | **1,0 Hz/bin** | 100 | 1,0 Hz/bin |
| Seção B (média de janelas) | 100 Hz | 100 | **1,0 Hz/bin** | 100 | 1,0 Hz/bin |
| Seção B2 Welch | 100 Hz | 256 | 0,39 Hz/bin | 512 | **0,195 Hz/bin** |
| Seção C1 Welch | 100 Hz | 256 | 0,39 Hz/bin | 512 | **0,195 Hz/bin** |
| STFT/Espectrograma | 100 Hz | 256 | 0,39 Hz/bin | 512 | **0,195 Hz/bin** |

**Implicação prática:** as features de ML (`fft_high`, `fft_mid`, `fft_low`)
são calculadas com Δf = 1 Hz/bin, o que é suficiente para distinguir as
bandas 0–5 Hz, 5–15 Hz e 15–50 Hz. Para identificar o pico exato de rotação
em 1,465 Hz (LOW) vs 2,197 Hz (MEDIUM) seriam necessárias janelas maiores
(≥ 256 amostras) — mas isso aumenta a latência de inferência em tempo real.

### 5.2 Trade-off Janela vs Latência para Tempo Real

```
Tamanho da janela (amostras)   Latência (100 Hz)   Δf máximo
───────────────────────────────────────────────────────────
      100  (atual)              1,0 s               1,0 Hz
      256                       2,56 s              0,39 Hz
      512                       5,12 s              0,195 Hz
     1000                      10,0 s              0,1 Hz
```

Para inferência em tempo real (backend FastAPI → controle do ventilador),
a janela de 100 amostras = 1 segundo com step=20 (0,2 s) oferece o melhor
equilíbrio: **latência de 0,2 s** com resolução suficiente para as 3 classes
de velocidade.

### 5.3 Por que a Média de Janelas (Seção B) Ainda é Útil

A média de espectros de janelas na Seção B não é usada para ML — é apenas
para **visualização exploratória**. Ela responde: "qual é o espectro típico
desta classe?" eliminando o ruído janela-a-janela e revelando a estrutura
espectral média estacionária.

Isso é diferente do Welch (Seção B2/C1), que faz o mesmo mas com:
- Janelamento Hann (reduz leakage espectral ~13 dB vs janela retangular)
- Maior resolução frequencial (nperseg=256 vs 100)
- Estimativa estatisticamente mais eficiente da PSD verdadeira

---

## 6. Separabilidade entre LOW e MEDIUM — Discussão Aprofundada

### 6.1 Por que Parece Difícil no Sinal Bruto

Olhando as séries temporais brutas, LOW e MEDIUM parecem idênticos:

```
Sinal bruto (1 amostra por vez):
  accel_x_g LOW:    média = 0,2967 g  ← quase igual
  accel_x_g MEDIUM: média = 0,2966 g  ← quase igual

  A diferença está na DISPERSÃO, não na média:
  std LOW:    0,064 g
  std MEDIUM: 0,105 g   (1,65× maior)
```

A média do sinal bruto é determinada principalmente pela **orientação estática
do sensor** (gravidade projetada nos eixos). A vibração do motor aparece como
*flutuações em torno da média*, não como deslocamento da média.

### 6.2 O que Resolve: Estatísticas de Janela

Ao acumular 100 amostras (1 segundo), as estatísticas de janela capturam a
dispersão que a análise ponto-a-ponto esconde:

| Feature | LOW | MEDIUM | Razão M/L | Cohen's d |
|---|---|---|---|---|
| `accel_x_g_range` | 0,245 g | 0,677 g | **2,76×** | **5,04** |
| `gyro_z_dps_std` | 6,76 dps | 14,90 dps | **2,20×** | **4,86** |
| `accel_x_g_fft_high` | 0,736 | 2,026 | **2,75×** | **4,82** |
| `accel_mag_g_std` | 0,020 g | 0,049 g | **2,50×** | **3,71** |

### 6.3 O Espectro Acrescenta Informação Independente

A feature `accel_z_g_sp_p12` (momento espectral P12 — kurtosis do centroide
de frequência, drift-resistant) obteve d=4,28 entre LOW e MEDIUM. Esta feature
captura se o espectro está concentrado em torno de uma frequência específica
(ventilador bem sincronizado) ou distribuído (motor irregular). Esta informação
é *ortogonal* ao range temporal — captura a *forma* do espectro, não a amplitude.

Isso confirma que **série temporal e espectro são complementares**, não
redundantes, para este problema específico.

---

## 7. Variabilidade Intra-Classe vs Inter-Classe

### 7.1 Coeficiente de Variação (CV = std/|média|) no Sinal Bruto

| Eixo | CV LOW | CV MEDIUM | CV HIGH | Interpretação |
|---|---|---|---|---|
| `accel_x_g` | 0,214 | 0,352 | 0,916 | Amplitude cresce com velocidade |
| `gyro_x_dps` | 3,110 | 8,381 | 13,456 | Jitter angular muito maior em HIGH |
| `gyro_z_dps` | 20,687 | 25,597 | 22,958 | Alta variabilidade em todas as classes |
| `accel_z_g` | 0,020 | 0,027 | 0,058 | Pequeno (eixo dominado por gravidade) |

O `gyro_z_dps` tem CV > 20 em todas as classes — isso indica que o sinal
é muito ruidoso *em relação à média*. Isso é esperado: o giroscópio Z mede
rotação em torno do eixo vertical, que é instável em um ventilador com
desequilíbrio mecânico. Mas precisamente essa instabilidade (*std*) é o
sinal discriminativo.

### 7.2 Relação Sinal/Ruído Inter-classe (SNR)

```
SNR = |μ₁ - μ₂| / sqrt(σ₁² + σ₂²)
```

Para LOW vs MEDIUM nas features selecionadas:

| Feature | SNR | Qualidade |
|---|---|---|
| `accel_x_g_range` | **3,56** | Excelente |
| `gyro_z_dps_std` | **3,44** | Excelente |
| `accel_x_g_fft_high` | **3,41** | Excelente |
| `accel_z_g_sp_p12` | **3,03** | Excelente |
| `gyro_x_dps_p25` | 0,54 | Bom (feature mais fraca do set) |

SNR > 1,0 em 15 das 16 features significa que a separação entre LOW e MEDIUM
*ao nível de features* é muito maior do que a variabilidade intra-classe.

---

## 8. Performance dos Modelos — Evidência Empírica

| Modelo | Features | CV Accuracy | Observação |
|---|---|---|---|
| GNB espectral v5.0 (fev/26) | 4 FFT simples | 96,23% | Confusão LOW↔MEDIUM documentada |
| GNB ensemble distilled v6.0 | 25 temporais | ~100% | Sem erros LOW/MEDIUM |
| GNB atual (mar/26) | 16 (range+FFT) | **98,49%** | Bom equilíbrio |
| RF atual (mar/26) | 16 (range+FFT) | **99,95%** | Praticamente perfeito |
| LogReg atual (mar/26) | 16 (range+FFT) | ~99,98% (treino) | Alta confiança |

A evolução histórica confirma a análise teórica:
- **4 features FFT simples → 96,23%:** FFT de frequência fundamental é bom
  mas insuficiente sozinho para 7 classes
- **25 features temporais → ~100%:** amplitude estatística resolve bem, mas
  25 features são excessivas para GNB (viola premissa de independência)
- **16 features mistas (range + FFT + spectral moments) → 99,95%:** o
  conjunto ideal combina domínio tempo e frequência com seleção rigorosa

---

## 9. Recomendações para Próximas Coletas

### 9.1 Se a Separabilidade LOW/MEDIUM Degradar

Checar primeiro:
1. `accel_x_g_range` — se d(L,M) < 2,0, a coleta tem problema de amplitude
2. `gyro_z_dps_std` — se d(L,M) < 2,0, a fixação física do sensor mudou
3. Taxa de amostragem — se caiu abaixo de 80 Hz, a banda `fft_high` (15–50 Hz) perde energia

### 9.2 Se ON vs OFF Ficarem Confusos

A cobertura atual é excelente (`vibration_dps_fft_high` cobre L e H; `accel_x_g_fft_high` cobre M). Se degradar:
1. Verificar se o ventilador está fisicamente rotacionando (mecânica)
2. Aumentar tempo de coleta por classe (mínimo recomendado: 120 s)
3. Adicionar `vibration_dps_range` (d_ON_OFF_avg = 3,88) ao set de features

### 9.3 Para Diagnóstico de Falha (futuro)

Quando o objetivo for detectar falhas de rolamento ou desbalanceamento:
- Aumentar janela para 512 amostras (Δf = 0,195 Hz → resolve harmônicos de rolamento)
- Adicionar features espectrais de alta resolução: centroide, spread, flatness
- Usar kurtosis temporal (já disponível no pipeline) como indicador precoce

---

## 10. Glossário

| Termo | Definição |
|---|---|
| **Cohen's d** | `|μ₁ - μ₂| / σ_pooled` — separação entre classes em σ. d≥0,8=médio, d≥1,5=grande |
| **d_min_all** | Mínimo de d de 1 feature em todos os pares de classes (critério de seleção) |
| **d_max (do set)** | Máximo de d entre todas as features do set para 1 par (cobertura real) |
| **PSD** | Power Spectral Density — energia por Hz, estimada pelo método de Welch |
| **STFT** | Short-Time Fourier Transform — espectro 2D: frequência × tempo |
| **Spectral leakage** | Vazamento de energia entre bins FFT causado por descontinuidades nas bordas da janela |
| **Hann window** | Função de suavização de borda que reduz o leakage em ~13 dB |
| **Zero-padding** | Adicionar zeros ao sinal antes da FFT para aumentar resolução visual (não física) |
| **fft_high** | Energia RMS na banda 15–50 Hz (alta frequência) de uma janela de 1 segundo |
| **sp_p12** | Momento espectral P12 — kurtosis do centroide de frequência (drift-resistant) |
| **vibration_dps** | `sqrt(gx² + gy² + gz²)` — magnitude total do giroscópio |
| **accel_mag_g** | `sqrt(ax² + ay² + az²)` — magnitude total do acelerômetro |
| **CV** | Coeficiente de Variação = `std / |média|` — variabilidade relativa intra-classe |
| **SNR inter-classe** | `|μ₁ - μ₂| / sqrt(σ₁² + σ₂²)` — separação normalizada pela variância combinada |
| **ON vs OFF** | Pares `*_ROT_ON vs *_ROT_OFF` — ventilador girando vs motor rodando sem rotação |

---

*Gerado em 2026-03-07. Referência: dataset `col_20260307_185012_100hz`,
feature config v5.19, notebooks 01_EDA.ipynb e 02_Feature_Engineering.ipynb.*
